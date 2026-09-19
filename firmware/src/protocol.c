/*
 * Stream protocol v1: packet building and CRC. See protocol.h and
 * docs/protocol.md.
 */

#include "protocol.h"

#include <string.h>

static uint32_t crc_table[256];

/* Build the lookup table for the standard CRC-32 (reflected, polynomial
 * 0xEDB88320). One table lookup per byte instead of 8 shift steps. */
void proto_init(void) {
	for (uint32_t i = 0; i < 256; i++) {
		uint32_t c = i;

		for (int k = 0; k < 8; k++) {
			c = (c & 1u) ? (c >> 1) ^ 0xEDB88320u : (c >> 1);
		}
		crc_table[i] = c;
	}
}

uint32_t proto_crc32(const uint8_t *data, size_t len) {
	uint32_t c = 0xFFFFFFFFu;

	for (size_t i = 0; i < len; i++) {
		c = crc_table[(c ^ data[i]) & 0xFFu] ^ (c >> 8);
	}
	return c ^ 0xFFFFFFFFu;
}

/* Little-endian writers. The MCU is little-endian too, but writing byte by
 * byte keeps the layout explicit and independent of struct packing. */
static void put_u16(uint8_t *p, uint16_t v) {
	p[0] = v & 0xFF;
	p[1] = v >> 8;
}

static void put_u32(uint8_t *p, uint32_t v) {
	put_u16(p, v & 0xFFFF);
	put_u16(p + 2, v >> 16);
}

static void put_u64(uint8_t *p, uint64_t v) {
	put_u32(p, (uint32_t)v);
	put_u32(p + 4, (uint32_t)(v >> 32));
}

size_t proto_build(uint8_t *out, enum proto_type type, uint8_t subpage,
                   uint8_t part, uint8_t part_count, uint32_t seq,
                   uint64_t timestamp_us, const void *payload, size_t len) {
	memcpy(out, PROTO_MAGIC, 4);
	out[4] = PROTO_VERSION;
	out[5] = (uint8_t)type;
	out[6] = subpage;
	out[7] = part;
	out[8] = part_count;
	out[9] = 0;
	put_u16(out + 10, (uint16_t)len);
	put_u32(out + 12, seq);
	put_u64(out + 16, timestamp_us);
	memcpy(out + PROTO_HEADER_LEN, payload, len);
	put_u32(out + PROTO_HEADER_LEN + len, proto_crc32(out, PROTO_HEADER_LEN + len));
	return PROTO_HEADER_LEN + len + PROTO_CRC_LEN;
}
