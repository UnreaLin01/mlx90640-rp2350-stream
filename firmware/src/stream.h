#ifndef STREAM_H
#define STREAM_H

/*
 * Stream: turns sensor data into protocol packets and hands them to the
 * transport. Big blocks (subpage, EEPROM) are split into parts of at most
 * PROTO_PART_MAX bytes. See docs/protocol.md.
 */

#include <stdbool.h>
#include <stdint.h>

#include "protocol.h"

void stream_init(void);

/* One subpage: frame[0..832] from MLX90640_GetFrameData. */
void stream_send_subpage(const uint16_t *frame, int subpage, uint64_t t_us);

/* The whole EEPROM (832 words). */
void stream_send_eeprom(const uint16_t *ee, uint64_t t_us);

void stream_send_status(const struct proto_status *st, uint64_t t_us);

/* Packets dropped because the transport could not take them. */
uint32_t stream_dropped(void);

/* The PC asked for the EEPROM (REQUEST packet). Set by the transport,
 * cleared when the main loop has sent it. */
void stream_request_eeprom(void);
bool stream_take_eeprom_request(void);

#endif
