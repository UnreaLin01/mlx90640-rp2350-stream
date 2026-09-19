#ifndef LOG_H
#define LOG_H

/*
 * Log output.
 *
 * All logs go to SEGGER RTT channel 0. The J-Link reads them from RAM in
 * the background, so printing does not wait on any wire and does not
 * disturb I2C timing. Read them on the PC with scripts/rtt.ps1.
 *
 * USB is kept for image data only. Never print logs to USB.
 */

#include "SEGGER_RTT.h"

static inline void log_init(void) {
	SEGGER_RTT_Init();
}

/* printf-style log line. Supports %d %u %x %s %c (no floating point). */
#define LOG(...)	SEGGER_RTT_printf(0, __VA_ARGS__)

#endif
