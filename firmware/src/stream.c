/*
 * Stream: sensor data -> protocol packets -> transport. See stream.h.
 */

#include "stream.h"

#include "mlx90640.h"
#include "transport.h"

/* SUBPAGE block: 768 pixels + 64 aux + control register. */
#define SUBPAGE_WORDS		(MLX90640_PIXEL_NUM + MLX90640_AUX_NUM + 1)

static uint8_t packet[PROTO_PACKET_MAX];
static uint32_t seq[4];			/* next block number, per type */
static uint32_t dropped;

void stream_init(void) {
	proto_init();
}

/* Split one block into parts and send them. Stops at the first part the
 * transport cannot take: the PC then sees an incomplete block. */
static void send_block(enum proto_type type, uint8_t subpage, uint64_t t_us,
                       const void *data, size_t len) {
	const uint8_t *bytes = data;
	uint8_t parts = (uint8_t)((len + PROTO_PART_MAX - 1) / PROTO_PART_MAX);
	uint32_t block_seq = seq[type]++;

	if (!transport_connected()) {
		return;
	}
	for (uint8_t p = 0; p < parts; p++) {
		size_t off = (size_t)p * PROTO_PART_MAX;
		size_t n = len - off < PROTO_PART_MAX ? len - off : PROTO_PART_MAX;
		size_t plen = proto_build(packet, type, subpage, p, parts, block_seq,
		                          t_us, bytes + off, n);

		if (!transport_send(packet, plen)) {
			dropped += parts - p;
			return;
		}
	}
}

void stream_send_subpage(const uint16_t *frame, int subpage, uint64_t t_us) {
	/* The MCU is little-endian, so the words are already in wire order. */
	send_block(PROTO_TYPE_SUBPAGE, (uint8_t)subpage, t_us, frame, SUBPAGE_WORDS * 2);
}

void stream_send_eeprom(const uint16_t *ee, uint64_t t_us) {
	send_block(PROTO_TYPE_EEPROM, PROTO_SUBPAGE_NONE, t_us, ee,
	           MLX90640_EEPROM_DUMP_NUM * 2);
}

void stream_send_status(const struct proto_status *st, uint64_t t_us) {
	/* struct proto_status is six uint32 with no padding, little-endian. */
	send_block(PROTO_TYPE_STATUS, PROTO_SUBPAGE_NONE, t_us, st, sizeof(*st));
}

uint32_t stream_dropped(void) {
	return dropped;
}
