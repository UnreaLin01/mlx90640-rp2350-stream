/*
 * Ethernet (W6300) setup. See net.h.
 */

#include "net.h"

#include <string.h>

#include "pico/stdlib.h"
#include "pico/unique_id.h"

#include "w6300.h"
#include "wizchip_conf.h"
#include "wizchip_spi.h"

#include "log.h"

/* The W6300 reports this chip ID; anything else means the QSPI link to
 * the chip is not working. */
#define W6300_CHIP_ID	0x6300

static uint8_t mac[6];
static wiz_NetInfo net_info;

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

	memset(&net_info, 0, sizeof(net_info));
	memcpy(net_info.mac, mac, 6);
	memcpy(net_info.ip, cfg->ip, 4);
	memcpy(net_info.sn, cfg->mask, 4);
	memcpy(net_info.gw, cfg->gateway, 4);
	net_info.ipmode = NETINFO_STATIC_ALL;
	wizchip_setnetinfo(&net_info);
	return true;
}

bool net_link_up(void) {
	uint8_t link = 0;

	ctlwizchip(CW_GET_PHYLINK, &link);
	return link == PHY_LINK_ON;
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
	LOG("net: IP %u.%u.%u.%u mask %u.%u.%u.%u gw %u.%u.%u.%u\r\n",
	    now.ip[0], now.ip[1], now.ip[2], now.ip[3],
	    now.sn[0], now.sn[1], now.sn[2], now.sn[3],
	    now.gw[0], now.gw[1], now.gw[2], now.gw[3]);
}
