#ifndef TRANSPORT_H
#define TRANSPORT_H

/*
 * Transport layer: "send one packet to the PC".
 *
 * Every transport (USB now, W6300 Ethernet later) implements these
 * functions. The rest of the firmware only uses this interface, so
 * changing the transport does not change anything else.
 *
 * Rules for every implementation:
 *   - transport_send() never blocks. If the packet cannot be queued
 *     right now, it is dropped as a whole (never half a packet).
 *   - transport_poll() must be called often (it runs the stack's
 *     background work). It must be quick.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

void transport_init(void);

/* Background work of the transport stack. Call often. */
void transport_poll(void);

/* True when a receiver is there to take data. */
bool transport_connected(void);

/* Queue one whole packet. Returns false if it was dropped. */
bool transport_send(const uint8_t *packet, size_t len);

#endif
