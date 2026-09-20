/*
 * UDP transport over the W6300 Ethernet chip, running on core 1.
 * See transport.h.
 *
 * Why core 1
 * ----------
 * Network calls can block: the first packet to a new PC waits for an ARP
 * reply (about 80 ms was measured over Wi-Fi), and link setup waits for the
 * cable. On one core that stalls the sensor loop and subpages are missed.
 * So core 1 does all the network work, and core 0 only reads the sensor.
 *
 * How the two cores work together
 * -------------------------------
 *   core 0 (main.c)                 core 1 (this file, net_task)
 *   ----------------                ----------------------------
 *   transport_send(packet) ──push──> tx_queue ──> sendto() over QSPI
 *                          <──flag── "a PC is asking for data"
 *
 * The queue (pico/util/queue.h) is protected by a hardware spin lock, so
 * both cores may use it at the same time. transport_send() only copies the
 * packet into the queue and returns; it never waits for the network. If the
 * queue is full the packet is dropped as a whole and counted, so a slow or
 * missing network can never slow down the sensor.
 *
 * Where to send is learned from the PC: it sends a REQUEST packet about
 * once per second, and the answers go back to that address and port
 * (docs/protocol.md). If no REQUEST arrives for REQUEST_TIMEOUT_US, the
 * board stops sending.
 */

#include "transport.h"

#include <string.h>

#include "pico/multicore.h"
#include "pico/stdlib.h"
#include "pico/util/queue.h"

#include "socket.h"
#include "wizchip_conf.h"

#include "log.h"
#include "net.h"
#include "protocol.h"
#include "stream.h"

#define UDP_SOCKET		0
#define UDP_PORT		5005
#define REQUEST_TIMEOUT_US	3000000
/* Packets waiting to be sent. One subpage is 2 packets at about 31 Hz, so
 * 16 slots hold a quarter second of data. */
#define TX_QUEUE_SLOTS		16

/*
 * The board's own address: DHCP first, and this fixed address if no DHCP
 * server answers. Either way the PC finds the board, because it searches
 * for it and then remembers the address (host/mlxstream/udp_source.py).
 * The PC's address is learned from its REQUEST packets, never set here.
 */
static const struct net_config NET_CONFIG = {
	.use_dhcp = true,
	/* Long enough for one retry by the DHCP library (it waits 10 s). */
	.dhcp_timeout_ms = 15000,
	.ip = { 192, 168, 1, 200 },
	.mask = { 255, 255, 255, 0 },
	.gateway = { 192, 168, 1, 1 },
};

struct tx_packet {
	uint16_t len;
	uint8_t data[PROTO_PACKET_MAX];
};

static queue_t tx_queue;
static uint8_t rx_buf[PROTO_PACKET_MAX];

/*
 * Written by core 1, read by core 0.
 *
 * Both are single 32-bit words, which this CPU reads and writes in one go,
 * so core 0 can never see a half-written value. A 64-bit time would be
 * written in two halves and could be read while half updated, so the time
 * is kept in 32 bits. It wraps every ~71 minutes; the subtraction in
 * transport_connected() gives the right answer across a wrap.
 */
static volatile bool peer_known;
static volatile uint32_t last_request_us;
/* Packets taken out of the queue but refused by the chip. */
static volatile uint32_t send_failed;
/* Set once when the chip or the socket did not come up. From then on
 * nothing can ever be sent, and core 1 has stopped. */
static volatile bool net_fault;

/* Core 1 only. */
static uint8_t peer_ip[4];
static uint16_t peer_port;

/* ------------------------------------------------------------------------
 * Core 1: the network task
 * ------------------------------------------------------------------------ */

/* Handle one incoming packet: only REQUEST from the PC is expected. */
static void handle_request(void) {
	uint8_t addr[16];
	uint16_t port;
	uint8_t addrlen = 4;
	int32_t len;
	struct proto_packet pkt;

	len = recvfrom_W6x00(UDP_SOCKET, rx_buf, sizeof(rx_buf), addr, &port, &addrlen);
	if (len <= 0 || !proto_parse(rx_buf, (size_t)len, &pkt) ||
	    pkt.type != PROTO_TYPE_REQUEST) {
		return;				/* not ours, or damaged */
	}

	if (!peer_known || memcmp(peer_ip, addr, 4) != 0 || peer_port != port) {
		memcpy(peer_ip, addr, 4);
		peer_port = port;
		LOG("udp: sending to %u.%u.%u.%u:%u\r\n",
		    addr[0], addr[1], addr[2], addr[3], port);
	}
	last_request_us = time_us_32();
	peer_known = true;

	if (pkt.payload_len >= 4) {
		uint32_t flags = (uint32_t)pkt.payload[0] | ((uint32_t)pkt.payload[1] << 8) |
		                 ((uint32_t)pkt.payload[2] << 16) | ((uint32_t)pkt.payload[3] << 24);

		if (flags & PROTO_REQ_SEND_EEPROM) {
			stream_request_eeprom();
		}
	}
}

/*
 * Stop core 1 for good and tell core 0 why.
 *
 * Returning from the entry function of core 1 is not defined, so every
 * failure ends here instead: raise the flag, then spin. Core 0 keeps
 * reading the sensor and shows the fault on the LED.
 */
static void net_give_up(const char *what) {
	LOG("udp: %s, core 1 stopping (nothing can be sent)\r\n", what);
	net_fault = true;
	while (1) {
		tight_loop_contents();
	}
}

static void net_task(void) {
	static struct tx_packet packet;		/* static: too big for the stack */

	if (!net_init(&NET_CONFIG)) {
		net_give_up("the W6300 did not start");
	}
	net_log_status();
	if (socket(UDP_SOCKET, Sn_MR_UDP4, UDP_PORT, 0) != UDP_SOCKET) {
		net_give_up("opening the socket failed");
	}
	LOG("udp: core 1 listening on port %u, waiting for a REQUEST\r\n", UDP_PORT);

	while (1) {
		net_poll();			/* keep the DHCP lease alive */
		if (getSn_RX_RSR(UDP_SOCKET) > 0) {
			handle_request();
		}
		if (transport_connected() && queue_try_remove(&tx_queue, &packet)) {
			/* This may wait (ARP, chip buffers), which is fine:
			 * core 0 keeps reading the sensor meanwhile. */
			int32_t sent = sendto_W6x00(UDP_SOCKET, packet.data, packet.len,
			                            peer_ip, peer_port, 4);

			/* The chip refuses to send while the link is down or its
			 * buffer is full. Count it, so the PC sees the loss in the
			 * STATUS packet instead of just missing a subpage. */
			if (sent != (int32_t)packet.len) {
				send_failed++;
			}
		} else {
			tight_loop_contents();
		}
	}
}

/* ------------------------------------------------------------------------
 * Core 0: the transport interface
 * ------------------------------------------------------------------------ */

void transport_init(void) {
	queue_init(&tx_queue, sizeof(struct tx_packet), TX_QUEUE_SLOTS);

	/*
	 * Stop core 1 before starting it. multicore_launch_core1() does not
	 * do this, and its handshake never finishes if core 1 is already
	 * running. That happens after a debugger reset (J-Link resets core 0
	 * only, so core 1 keeps running code from the flash that was just
	 * overwritten) - the firmware would hang here at boot.
	 */
	multicore_reset_core1();
	multicore_launch_core1(net_task);
	LOG("udp: network task started on core 1\r\n");
}

void transport_poll(void) {
	/* Nothing to do: core 1 does the network work. */
}

bool transport_connected(void) {
	return peer_known && time_us_32() - last_request_us < REQUEST_TIMEOUT_US;
}

bool transport_send(const uint8_t *packet, size_t len) {
	static struct tx_packet slot;		/* core 0 only */

	if (!transport_connected() || len > PROTO_PACKET_MAX) {
		return false;
	}
	slot.len = (uint16_t)len;
	memcpy(slot.data, packet, len);
	/* Never waits: a full queue means the packet is dropped and counted. */
	return queue_try_add(&tx_queue, &slot);
}

uint32_t transport_dropped(void) {
	return send_failed;
}

bool transport_fault(void) {
	return net_fault;
}
