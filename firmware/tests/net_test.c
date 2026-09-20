/*
 * Ethernet bring-up test (M6).
 *
 * 1. Sets up the W6300 with a static IP, so the PC can ping the board.
 * 2. Waits on UDP port 5005. When a packet arrives, it sends UDP packets
 *    back to that sender as fast as it can for BLAST_SECONDS, so the PC
 *    can measure the throughput (host/net_test.py).
 *
 * The sender's address is learned from the incoming packet, so the PC's
 * address does not have to be known in advance, and the PC's firewall
 * lets the answers through (they belong to a connection the PC started).
 *
 * No sensor data here; that is M7.
 */

#include <string.h>

#include "pico/stdlib.h"

#include "socket.h"
#include "wizchip_conf.h"

#include "board.h"
#include "log.h"
#include "net.h"

#define UDP_SOCKET	0
#define UDP_PORT	5005
#define BLAST_SECONDS	5
#define PAYLOAD_LEN	1024		/* fits in one Ethernet frame */

static const struct net_config CONFIG = {
	.ip = { 192, 168, 1, 200 },
	.mask = { 255, 255, 255, 0 },
	.gateway = { 192, 168, 1, 1 },
};

static uint8_t rx_buf[1536];
static uint8_t tx_buf[PAYLOAD_LEN];

/* Send packets as fast as the chip takes them, for a few seconds.
 * Each packet starts with a 4-byte counter so the PC can spot losses. */
static void blast(const uint8_t *addr, uint16_t port) {
	uint32_t count = 0, sent = 0, errors = 0;
	absolute_time_t end = make_timeout_time_ms(BLAST_SECONDS * 1000);
	uint32_t t0 = time_us_32();

	LOG("blast: to %u.%u.%u.%u:%u for %u s\r\n",
	    addr[0], addr[1], addr[2], addr[3], port, BLAST_SECONDS);
	gpio_put(PIN_MARK_A, 1);
	while (!time_reached(end)) {
		int32_t ret;

		memcpy(tx_buf, &count, 4);
		ret = sendto_W6x00(UDP_SOCKET, tx_buf, PAYLOAD_LEN,
		                   (uint8_t *)addr, port, 4);
		if (ret == PAYLOAD_LEN) {
			sent++;
		} else {
			errors++;
		}
		count++;
	}
	gpio_put(PIN_MARK_A, 0);
	uint32_t dt = time_us_32() - t0;
	LOG("blast: %u packets, %u errors, %u us -> %u kB/s\r\n",
	    (unsigned)sent, (unsigned)errors, (unsigned)dt,
	    (unsigned)((uint64_t)sent * PAYLOAD_LEN * 1000u / dt));
}

int main(void) {
	uint32_t seconds = 0;
	bool ready = false;

	log_init();
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);
	gpio_init(PIN_MARK_A);
	gpio_set_dir(PIN_MARK_A, GPIO_OUT);

	LOG("M6 net test\r\n");
	if (!net_init(&CONFIG)) {
		while (1) {			/* fast blink: no chip */
			gpio_xor_mask(1u << PIN_LED);
			sleep_ms(100);
		}
	}
	net_log_status();

	if (socket(UDP_SOCKET, Sn_MR_UDP4, UDP_PORT, 0) != UDP_SOCKET) {
		LOG("net: socket failed\r\n");
	} else {
		ready = true;
		LOG("net: listening on UDP %u\r\n", UDP_PORT);
	}

	while (1) {
		if (ready && getSn_RX_RSR(UDP_SOCKET) > 0) {
			uint8_t addr[16] = { 0 };
			uint16_t port = 0;
			uint8_t addrlen = 4;
			int32_t len = recvfrom_W6x00(UDP_SOCKET, rx_buf, sizeof(rx_buf),
			                             addr, &port, &addrlen);

			if (len > 0) {
				LOG("net: %d bytes from %u.%u.%u.%u:%u\r\n", (int)len,
				    addr[0], addr[1], addr[2], addr[3], port);
				blast(addr, port);
			}
		}

		/* Once per second: blink and report the link state. */
		static absolute_time_t next;
		if (time_reached(next)) {
			next = make_timeout_time_ms(1000);
			gpio_xor_mask(1u << PIN_LED);
			LOG("alive %u s, link %s\r\n", (unsigned)seconds++,
			    net_link_up() ? "up" : "down");
		}
		tight_loop_contents();
	}
}
