/*
 * Main firmware.
 *
 * Current stage (M1): blink the LED and print a counter to RTT once per
 * second, to prove that flashing and logging work.
 */

#include <stdint.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"

#include "board.h"
#include "log.h"

int main(void) {
	uint32_t count = 0;
	absolute_time_t next;

	log_init();
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);
	LOG("M1 boot, sys_clk=%u Hz\r\n", (unsigned)clock_get_hz(clk_sys));

	/* Wait until fixed points in time, so the 1 s period does not drift. */
	next = get_absolute_time();
	while (1) {
		LOG("count=%u t_us=%u\r\n", (unsigned)count, (unsigned)time_us_32());
		count++;

		gpio_put(PIN_LED, 1);
		next = delayed_by_ms(next, 500);
		sleep_until(next);
		gpio_put(PIN_LED, 0);
		next = delayed_by_ms(next, 500);
		sleep_until(next);
	}
}
