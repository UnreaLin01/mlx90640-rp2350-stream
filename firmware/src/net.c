/*
 * Ethernet (W6300) setup. See net.h.
 */

#include "net.h"

#include <string.h>

#include "pico/stdlib.h"
#include "pico/unique_id.h"

#include "dhcp.h"
#include "socket.h"
#include "w6300.h"
#include "wizchip_conf.h"

/*
 * WIZnet's header declares several static functions it never defines,
 * which -Wall reports six times. The header is third-party and stays
 * unmodified, so the warning is turned off here instead.
 *
 * It has to stay off for the rest of this file. GCC checks for "declared
 * static but never defined" only when the whole file is done, so wrapping
 * just the include in push/pop does not catch it (tried and measured).
 * Only this one warning is affected; every other check still runs.
 */
#pragma GCC diagnostic ignored "-Wunused-function"
#include "wizchip_spi.h"

#include "log.h"

/* The W6300 reports this chip ID; anything else means the QSPI link to
 * the chip is not working. */
#define W6300_CHIP_ID	0x6300

/* Socket 0 carries the data stream, so DHCP uses socket 1. */
#define DHCP_SOCKET	1
/* A DHCP message is at most 548 bytes; this is the library's work buffer. */
static uint8_t dhcp_buf[1024];

static uint8_t mac[6];
static wiz_NetInfo net_info;
static bool dhcp_active;
static uint32_t last_dhcp_tick_ms;

/* Build a MAC address from the chip's unique ID.
 * First byte 0x02: "locally administered", not a registered address. */
static void make_mac(void) {
	pico_unique_board_id_t id;

	pico_get_unique_board_id(&id);
	mac[0] = 0x02;
	for (int i = 0; i < 5; i++) {
		mac[i + 1] = id.id[i + 3];
	}
}

/* The DHCP library needs a 1 second tick. */
static void dhcp_tick(void) {
	uint32_t now = to_ms_since_boot(get_absolute_time());

	if (now - last_dhcp_tick_ms >= 1000) {
		last_dhcp_tick_ms = now;
		DHCP_time_handler();
	}
}

/*
 * Wait after the link comes up before speaking. A switch port needs a
 * moment before it forwards, and the first DHCP request would be lost.
 * WIZnet's own example waits 2 s here as well.
 */
#define LINK_SETTLE_MS	2000

/* Ask a DHCP server for an address. Returns true if one was given.
 * The library writes the address into the chip itself.
 *
 * Note the timeout should cover at least one retry by the library
 * (DHCP_WAIT_TIME, 10 s), in case the first request is lost.
 */
static bool run_dhcp(uint32_t timeout_ms) {
	absolute_time_t deadline;

	sleep_ms(LINK_SETTLE_MS);
	deadline = make_timeout_time_ms(timeout_ms);
	LOG("net: asking for an address by DHCP (up to %u ms)\r\n", timeout_ms);
	DHCP_init(DHCP_SOCKET, dhcp_buf);
	last_dhcp_tick_ms = to_ms_since_boot(get_absolute_time());

	uint8_t last_state = 0xFF;
	uint32_t rx_seen = 0;

	while (!time_reached(deadline)) {
		uint8_t state;

		/* Count bytes arriving on the DHCP socket, to tell "nobody
		 * answered" apart from "the answer was not understood". */
		rx_seen += getSn_RX_RSR(DHCP_SOCKET);
		state = DHCP_run();
		if (state != last_state) {
			LOG("net: DHCP state %u -> %u (socket status 0x%02X, rx seen %u)\r\n",
			    last_state, state, getSn_SR(DHCP_SOCKET), (unsigned)rx_seen);
			last_state = state;
		}

		dhcp_tick();
		if (state == DHCP_IP_ASSIGN || state == DHCP_IP_LEASED) {
			return true;
		}
		if (state == DHCP_FAILED) {
			LOG("net: DHCP failed (rx seen %u)\r\n", (unsigned)rx_seen);
			break;
		}
	}
	LOG("net: DHCP timed out (rx seen %u bytes)\r\n", (unsigned)rx_seen);
	DHCP_stop();
	close(DHCP_SOCKET);
	return false;
}

bool net_init(const struct net_config *cfg) {
	uint16_t chip_id;

	make_mac();

	/* QSPI pins, PIO program and the chip's reset line. */
	wizchip_spi_initialize();
	wizchip_cris_initialize();
	wizchip_reset();

	/* WIZnet's setup: it registers the functions that read and write the
	 * chip's registers, sets the socket buffer sizes, and then WAITS FOR
	 * THE ETHERNET CABLE - it does not return until the link is up. */
	LOG("net: waiting for the Ethernet link (cable must be connected)\r\n");
	wizchip_initialize();
	LOG("net: link up\r\n");

	/* Only now can the chip's registers be read. */
	chip_id = getCIDR();
	if (chip_id != W6300_CHIP_ID) {
		LOG("net: W6300 not answering (chip id 0x%04X, expected 0x%04X)\r\n",
		    chip_id, W6300_CHIP_ID);
		return false;
	}

	/* The MAC must be set before DHCP: the server answers to it. */
	memset(&net_info, 0, sizeof(net_info));
	memcpy(net_info.mac, mac, 6);
	net_info.ipmode = NETINFO_STATIC_ALL;
	wizchip_setnetinfo(&net_info);

	dhcp_active = cfg->use_dhcp && run_dhcp(cfg->dhcp_timeout_ms);
	if (!dhcp_active) {
		LOG("net: using the fixed address\r\n");
		memcpy(net_info.ip, cfg->ip, 4);
		memcpy(net_info.sn, cfg->mask, 4);
		memcpy(net_info.gw, cfg->gateway, 4);
		wizchip_setnetinfo(&net_info);
	}
	return true;
}

void net_poll(void) {
	if (!dhcp_active) {
		return;
	}
	/* Keeps the lease: the library renews it when it is about to run out.
	 * Both calls are cheap when there is nothing to do. */
	dhcp_tick();
	DHCP_run();
}

bool net_link_up(void) {
	uint8_t link = 0;

	ctlwizchip(CW_GET_PHYLINK, &link);
	return link == PHY_LINK_ON;
}

bool net_dhcp_active(void) {
	return dhcp_active;
}

const uint8_t *net_mac(void) {
	return mac;
}

void net_log_status(void) {
	wiz_NetInfo now;

	wizchip_getnetinfo(&now);
	LOG("net: chip id 0x%04X, version 0x%02X, link %s\r\n", getCIDR(), getVER(),
	    net_link_up() ? "up" : "down");
	LOG("net: MAC %02X:%02X:%02X:%02X:%02X:%02X\r\n",
	    now.mac[0], now.mac[1], now.mac[2], now.mac[3], now.mac[4], now.mac[5]);
	LOG("net: IP %u.%u.%u.%u mask %u.%u.%u.%u gw %u.%u.%u.%u (%s)\r\n",
	    now.ip[0], now.ip[1], now.ip[2], now.ip[3],
	    now.sn[0], now.sn[1], now.sn[2], now.sn[3],
	    now.gw[0], now.gw[1], now.gw[2], now.gw[3],
	    dhcp_active ? "DHCP" : "fixed");
}
