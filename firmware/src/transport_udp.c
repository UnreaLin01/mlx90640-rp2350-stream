/*
 * UDP transport over the W6300 Ethernet chip. See transport.h.
 *
 * One packet per UDP datagram (packets are at most 1052 bytes, so they fit
 * in one Ethernet frame).
 *
 * Where to send is learned from the PC: the PC sends a REQUEST packet to
 * this board's UDP port about once per second, and the answers go back to
 * that address and port (docs/protocol.md). So the PC's address may change
 * (DHCP) without reflashing, and its firewall lets the answers through.
 * If no REQUEST arrives for REQUEST_TIMEOUT_US, the board stops sending.
 */

#include "transport.h"

#include <string.h>

#include "pico/stdlib.h"

#include "socket.h"
#include "wizchip_conf.h"

#include "log.h"
#include "net.h"
#include "protocol.h"
#include "stream.h"

#define UDP_SOCKET		0
#define UDP_PORT		5005
#define REQUEST_TIMEOUT_US	3000000

/* The board's own address. The PC's address is learned, not set here. */
static const struct net_config NET_CONFIG = {
	.ip = { 192, 168, 1, 200 },
	.mask = { 255, 255, 255, 0 },
	.gateway = { 192, 168, 1, 1 },
};

static uint8_t rx_buf[PROTO_PACKET_MAX];
static uint8_t peer_ip[4];
static uint16_t peer_port;
static uint64_t last_request_us;
static bool socket_ready;

void transport_init(void) {
	if (!net_init(&NET_CONFIG)) {
		return;
	}
	net_log_status();
	if (socket(UDP_SOCKET, Sn_MR_UDP4, UDP_PORT, 0) != UDP_SOCKET) {
		LOG("udp: socket failed\r\n");
		return;
	}
	socket_ready = true;
	LOG("udp: listening on port %u, waiting for a REQUEST from the PC\r\n", UDP_PORT);
}

void transport_poll(void) {
	uint8_t addr[16];
	uint16_t port;
	uint8_t addrlen = 4;
	int32_t len;
	struct proto_packet pkt;

	if (!socket_ready || getSn_RX_RSR(UDP_SOCKET) == 0) {
		return;
	}
	len = recvfrom_W6x00(UDP_SOCKET, rx_buf, sizeof(rx_buf), addr, &port, &addrlen);
	if (len <= 0 || !proto_parse(rx_buf, (size_t)len, &pkt)) {
		return;				/* not ours, or damaged */
	}
	if (pkt.type != PROTO_TYPE_REQUEST) {
		return;
	}

	if (memcmp(peer_ip, addr, 4) != 0 || peer_port != port) {
		memcpy(peer_ip, addr, 4);
		peer_port = port;
		LOG("udp: sending to %u.%u.%u.%u:%u\r\n",
		    addr[0], addr[1], addr[2], addr[3], port);
	}
	last_request_us = time_us_64();

	if (pkt.payload_len >= 4) {
		uint32_t flags = (uint32_t)pkt.payload[0] | ((uint32_t)pkt.payload[1] << 8) |
		                 ((uint32_t)pkt.payload[2] << 16) | ((uint32_t)pkt.payload[3] << 24);

		if (flags & PROTO_REQ_SEND_EEPROM) {
			stream_request_eeprom();
		}
	}
}

bool transport_connected(void) {
	return socket_ready && peer_port != 0 &&
	       time_us_64() - last_request_us < REQUEST_TIMEOUT_US;
}

bool transport_send(const uint8_t *packet, size_t len) {
	if (!transport_connected()) {
		return false;
	}
	/* Only send when the chip has room, so this never waits. */
	if (getSn_TX_FSR(UDP_SOCKET) < len) {
		return false;
	}
	return sendto_W6x00(UDP_SOCKET, (uint8_t *)packet, (uint16_t)len,
	                    peer_ip, peer_port, 4) == (int32_t)len;
}
