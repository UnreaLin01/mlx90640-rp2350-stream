/*
 * Log setup. See log.h.
 */

#include "log.h"

spin_lock_t *log_spin_lock;

void log_init(void) {
	/* One of the 32 hardware spin locks, so both cores can print. */
	log_spin_lock = spin_lock_instance((uint)spin_lock_claim_unused(true));
	SEGGER_RTT_Init();
}
