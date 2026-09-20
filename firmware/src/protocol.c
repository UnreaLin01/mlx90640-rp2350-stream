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

static uint16_t get_u16(const uint8_t *p) {
	return (uint16_t)(p[0] | (p[1] << 8));
}

static uint32_t get_u32(const uint8_t *p) {
	return (uint32_t)get_u16(p) | ((uint32_t)get_u16(p + 2) << 16);
}

bool proto_parse(const uint8_t *data, size_t len, struct proto_packet *out) {
	uint16_t payload_len;

	if (len < PROTO_HEADER_LEN + PROTO_CRC_LEN) {
		return false;
	}
	if (memcmp(data, PROTO_MAGIC, 4) != 0 || data[4] != PROTO_VERSION) {
		return false;
	}
	payload_len = get_u16(data + 10);
	if (payload_len > PROTO_PART_MAX ||
	    len < (size_t)PROTO_HEADER_LEN + payload_len + PROTO_CRC_LEN) {
		return false;
	}
	if (data[8] == 0 || data[7] >= data[8]) {	/* part / part_count */
		return false;
	}
	if (proto_crc32(data, PROTO_HEADER_LEN + payload_len) !=
	    get_u32(data + PROTO_HEADER_LEN + payload_len)) {
		return false;
	}

	out->type = data[5];
	out->subpage = data[6];
	out->part = data[7];
	out->part_count = data[8];
	out->payload_len = payload_len;
	out->seq = get_u32(data + 12);
	out->timestamp_us = (uint64_t)get_u32(data + 16) |
	                    ((uint64_t)get_u32(data + 20) << 32);
	out->payload = data + PROTO_HEADER_LEN;
	return true;
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
