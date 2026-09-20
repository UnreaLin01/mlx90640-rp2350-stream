#ifndef PROTOCOL_H
#define PROTOCOL_H

/*
 * Stream protocol v1: packet layout shared by USB and Ethernet.
 * The full description is in docs/protocol.md; keep the two in sync.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PROTO_MAGIC		"MLXT"
#define PROTO_VERSION		1

#define PROTO_HEADER_LEN	24
#define PROTO_CRC_LEN		4
#define PROTO_PART_MAX		1024	/* max payload bytes in one packet */
#define PROTO_PACKET_MAX	(PROTO_HEADER_LEN + PROTO_PART_MAX + PROTO_CRC_LEN)

#define PROTO_SUBPAGE_NONE	0xFF	/* subpage field for non-subpage types */

enum proto_type {
	PROTO_TYPE_SUBPAGE = 1,
	PROTO_TYPE_EEPROM = 2,
	PROTO_TYPE_STATUS = 3,
	PROTO_TYPE_REQUEST = 4,		/* PC -> board (UDP only) */
};

/* REQUEST payload flags */
#define PROTO_REQ_SEND_EEPROM	(1u << 0)

/* Fields of a received packet, filled in by proto_parse(). */
struct proto_packet {
	uint8_t type;
	uint8_t subpage;
	uint8_t part;
	uint8_t part_count;
	uint16_t payload_len;
	uint32_t seq;
	uint64_t timestamp_us;
	const uint8_t *payload;
};

/*
 * Check one received packet (magic, version, lengths, CRC) and fill in
 * `out`. Returns false if it is not a valid packet.
 */
bool proto_parse(const uint8_t *data, size_t len, struct proto_packet *out);

/* Payload of a STATUS packet (all little-endian uint32). */
struct proto_status {
	uint32_t subpages;
	uint32_t read_errors;
	uint32_t order_errors;
	uint32_t wait_errors;
	uint32_t tx_dropped;
	uint32_t read_us_max;
};

void proto_init(void);

/* CRC-32, same as zlib.crc32 on the PC. */
uint32_t proto_crc32(const uint8_t *data, size_t len);

/*
 * Build one packet into `out` (at least PROTO_PACKET_MAX bytes).
 * `payload` is this part's data (len <= PROTO_PART_MAX).
 * Returns the packet length.
 */
size_t proto_build(uint8_t *out, enum proto_type type, uint8_t subpage,
                   uint8_t part, uint8_t part_count, uint32_t seq,
                   uint64_t timestamp_us, const void *payload, size_t len);

#endif
