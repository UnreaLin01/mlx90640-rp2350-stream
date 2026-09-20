/*
 * USB descriptors: one CDC interface (shows up as a COM port on Windows).
 *
 * The PC finds the board by VID/PID plus the product string below
 * (host/mlxstream/sources.py). VID 0x2E8A / PID 0x0009 are the ones the
 * Pico SDK uses for its own USB serial port.
 *
 * There is a second interface: the Raspberry Pi "reset" interface. It lets
 * picotool restart the board into BOOTSEL mode by itself, so flashing over
 * USB does not need the BOOTSEL button (scripts/flash_usb.ps1). The work is
 * done by the SDK's pico_usb_reset library; here we only add the interface
 * to the descriptors. It also needs bcdUSB 0x0210 plus a Microsoft OS 2.0
 * descriptor (the library provides it), so Windows binds a driver to it
 * without anything being installed.
 */

#include <string.h>

#include "pico/unique_id.h"
#include "pico/usb_reset.h"
#include "tusb.h"

#define USB_VID		0x2E8A
#define USB_PID		0x0009
/* 0x0210: needed for the Microsoft OS 2.0 descriptor of the reset interface. */
#define USB_BCD		0x0210

#define PRODUCT_NAME	"MLX90640 Thermal Stream"

/* ------------------------------------------------------------------------
 * Device descriptor
 * ------------------------------------------------------------------------ */

static const tusb_desc_device_t desc_device = {
	.bLength = sizeof(tusb_desc_device_t),
	.bDescriptorType = TUSB_DESC_DEVICE,
	.bcdUSB = USB_BCD,
	/* CDC uses two interfaces, grouped by an Interface Association
	 * Descriptor, which needs this class/subclass/protocol. */
	.bDeviceClass = TUSB_CLASS_MISC,
	.bDeviceSubClass = MISC_SUBCLASS_COMMON,
	.bDeviceProtocol = MISC_PROTOCOL_IAD,
	.bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
	.idVendor = USB_VID,
	.idProduct = USB_PID,
	.bcdDevice = 0x0100,
	.iManufacturer = 1,
	.iProduct = 2,
	.iSerialNumber = 3,
	.bNumConfigurations = 1,
};

const uint8_t *tud_descriptor_device_cb(void) {
	return (const uint8_t *)&desc_device;
}

/* ------------------------------------------------------------------------
 * Configuration descriptor
 * ------------------------------------------------------------------------ */

enum {
	ITF_NUM_CDC = 0,
	ITF_NUM_CDC_DATA,
	ITF_NUM_RESET,		/* picotool's reset interface */
	ITF_NUM_TOTAL,
};

/* The reset interface number must match what the library puts in the
 * Microsoft OS 2.0 descriptor. */
static_assert(ITF_NUM_RESET == PICO_USB_RESET_MS_OS_20_DESCRIPTOR_ITF,
              "ITF_NUM_RESET must equal PICO_USB_RESET_MS_OS_20_DESCRIPTOR_ITF");

#define EPNUM_CDC_NOTIF		0x81
#define EPNUM_CDC_OUT		0x02
#define EPNUM_CDC_IN		0x82

#define CONFIG_TOTAL_LEN	(TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_RPI_RESET_DESC_LEN)

static const uint8_t desc_configuration[] = {
	/* config number, interface count, string index, total length,
	 * attributes, power (mA) */
	TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
	/* interface number, string index, notify EP + size, data EPs + size */
	TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
	/* interface number, string index */
	TUD_RPI_RESET_DESCRIPTOR(ITF_NUM_RESET, 5),
};

const uint8_t *tud_descriptor_configuration_cb(uint8_t index) {
	(void)index;
	return desc_configuration;
}

/* ------------------------------------------------------------------------
 * String descriptors
 * ------------------------------------------------------------------------ */

enum {
	STRID_LANGID = 0,
	STRID_MANUFACTURER,
	STRID_PRODUCT,
	STRID_SERIAL,
	STRID_CDC,
	STRID_RESET,
	STRID_COUNT,
};

static const char *const string_desc[STRID_COUNT] = {
	[STRID_MANUFACTURER] = "LabBEST",
	[STRID_PRODUCT] = PRODUCT_NAME,
	[STRID_SERIAL] = NULL,		/* filled from the chip's unique ID */
	[STRID_CDC] = PRODUCT_NAME " data",
	[STRID_RESET] = "Reset",
};

/* USB strings are UTF-16. Longest string here is well below 32 chars. */
static uint16_t desc_str[33];

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
	char serial[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
	const char *str;
	size_t len;

	(void)langid;
	if (index == STRID_LANGID) {
		desc_str[1] = 0x0409;	/* English (US) */
		len = 1;
	} else {
		if (index >= STRID_COUNT) {
			return NULL;
		}
		if (index == STRID_SERIAL) {
			pico_get_unique_board_id_string(serial, sizeof(serial));
			str = serial;
		} else {
			str = string_desc[index];
		}
		len = strlen(str);
		if (len > 32) {
			len = 32;
		}
		for (size_t i = 0; i < len; i++) {
			desc_str[1 + i] = (uint8_t)str[i];
		}
	}
	/* First word: descriptor type and total length in bytes. */
	desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * len + 2));
	return desc_str;
}
