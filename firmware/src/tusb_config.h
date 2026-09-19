#ifndef TUSB_CONFIG_H
#define TUSB_CONFIG_H

/*
 * TinyUSB settings: one CDC (virtual COM port) interface, device only.
 */

/* The Pico SDK build usually sets these already. */
#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS		OPT_OS_PICO
#endif

/* USB port 0 works as a device (same setting as the SDK's stdio_usb). */
#define CFG_TUSB_RHPORT0_MODE	(OPT_MODE_DEVICE)
#define CFG_TUD_ENDPOINT0_SIZE	64

#define CFG_TUD_CDC		1
#define CFG_TUD_MSC		0
#define CFG_TUD_HID		0
#define CFG_TUD_MIDI		0
#define CFG_TUD_VENDOR		0

/* Full speed: 64-byte USB packets. */
#define CFG_TUD_CDC_EP_BUFSIZE	64
#define CFG_TUD_CDC_RX_BUFSIZE	64
/* Transmit buffer: room for a few seconds' worth of bursts. One subpage is
 * 2 packets (about 1.7 KB); 8 KB leaves room for EEPROM and status too. */
#define CFG_TUD_CDC_TX_BUFSIZE	8192

#endif
