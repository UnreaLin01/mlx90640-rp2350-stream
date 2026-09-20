/*
 * USB CDC transport. See transport.h.
 *
 * Uses TinyUSB directly (not the SDK's stdio_usb): the CDC channel carries
 * only protocol packets, never log text. Settings are in tusb_config.h and
 * the USB descriptors in usb_descriptors.c.
 */

#include "transport.h"

#include "tusb.h"

void transport_init(void) {
	tusb_init();
}

void transport_poll(void) {
	tud_task();
}

bool transport_connected(void) {
	/* "Connected" means a program on the PC opened the port (DTR set).
	 * Without that, packets would only fill the buffer with old data. */
	return tud_cdc_connected();
}

bool transport_send(const uint8_t *packet, size_t len) {
	if (!tud_cdc_connected()) {
		return false;
	}
	/* Only queue whole packets. */
	if (tud_cdc_write_available() < len) {
		return false;
	}
	tud_cdc_write(packet, (uint32_t)len);
	tud_cdc_write_flush();
	return true;
}

uint32_t transport_dropped(void) {
	/* Nothing is queued behind transport_send(): a packet that fits in
	 * the FIFO is always sent, so there is nothing to lose later. */
	return 0;
}

bool transport_fault(void) {
	/* The USB block is part of the MCU; there is no separate chip that
	 * could fail to start. */
	return false;
}
