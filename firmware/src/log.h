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
 *
 * Both cores may log. RTT's own lock only blocks interrupts on the core
 * that is printing, which is not enough when two cores print at the same
 * time, so a hardware spin lock is taken around each line. Taking it also
 * disables interrupts on that core, so an interrupt on the same core
 * cannot deadlock by trying to log while the lock is held.
 */

#include "hardware/sync.h"
#include "pico/stdlib.h"

#include "SEGGER_RTT.h"

extern spin_lock_t *log_spin_lock;

void log_init(void);

/* printf-style log line. Supports %d %u %x %s %c (no floating point). */
#define LOG(...)							\
	do {								\
		uint32_t log_irq_state = spin_lock_blocking(log_spin_lock); \
		SEGGER_RTT_printf(0, __VA_ARGS__);			\
		spin_unlock(log_spin_lock, log_irq_state);		\
	} while (0)

#endif
