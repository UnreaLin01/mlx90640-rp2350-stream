#ifndef NET_H
#define NET_H

/*
 * Ethernet (W6300) setup and status.
 *
 * The W6300 is on the board and talks to the RP2350 over QSPI driven by
 * PIO on GPIO15-22. The driver is WIZnet's (third_party/WIZnet-PICO-C);
 * this file only sets it up and reports what it finds.
 *
 * The MAC address is made from the chip's unique ID, with the "locally
 * administered" bit set, so every board gets its own address without
 * needing a registered one.
 */

#include <stdbool.h>
#include <stdint.h>

struct net_config {
	uint8_t ip[4];
	uint8_t mask[4];
	uint8_t gateway[4];
};

/* Set up the chip and the network settings. Returns false if the chip does
 * not answer. */
bool net_init(const struct net_config *cfg);

/* True while the Ethernet cable is connected and the link is up. */
bool net_link_up(void);

/* The MAC address that net_init() used (6 bytes). */
const uint8_t *net_mac(void);

/* Print chip version, MAC, IP and link state to the log. */
void net_log_status(void);

#endif
