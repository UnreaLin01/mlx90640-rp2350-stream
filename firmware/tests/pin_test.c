/*
 * Pin test: checks the four Logic 8 wires (M1).
 *
 * A counter goes up by one every TICK_US. Each measured pin shows one bit
 * of that counter, in Logic 8 channel order:
 *
 *   CH0 = GP4 (SDA)     bit 0   5000 Hz
 *   CH1 = GP5 (SCL)     bit 1   2500 Hz
 *   CH2 = GP6 (mark A)  bit 2   1250 Hz
 *   CH3 = GP7 (mark B)  bit 3    625 Hz
 *
 * If every wire is right, CH0..CH3 read as a clean 4-bit counter
 * (0, 1, 2, ... 15, 0, ...). A swapped wire shows the wrong speed on that
 * channel, and a broken wire shows a flat line.
 *
 * SCL and SDA are driven the I2C way ("open-drain"): the pin either pulls
 * the line low, or lets go and a pull-up resistor brings it high. The pin
 * never drives high by itself, so nothing is damaged if the sensor pulls
 * the same line low at the same time. The internal pull-up is turned on
 * as a backup in case the sensor module has no pull-ups.
 */

#include <stdbool.h>
#include <stdint.h>

#include "pico/stdlib.h"

#include "board.h"
#include "log.h"

#define TICK_US		100

struct test_pin {
	uint pin;
	bool open_drain;
	const char *name;
};

/* Index in this table = Logic 8 channel = counter bit. */
static const struct test_pin test_pins[] = {
	{ PIN_I2C_SDA, true,  "GP4 SDA" },
	{ PIN_I2C_SCL, true,  "GP5 SCL" },
	{ PIN_MARK_A,  false, "GP6 mark A" },
	{ PIN_MARK_B,  false, "GP7 mark B" },
};

#define NUM_TEST_PINS	(sizeof(test_pins) / sizeof(test_pins[0]))

static volatile uint32_t tick_count;

/* Set one pin high or low. Open-drain pins release the line for "high". */
static void test_pin_write(const struct test_pin *tp, bool high) {
	if (tp->open_drain) {
		gpio_set_dir(tp->pin, high ? GPIO_IN : GPIO_OUT);
	} else {
		gpio_put(tp->pin, high);
	}
}

static void test_pins_init(void) {
	for (uint i = 0; i < NUM_TEST_PINS; i++) {
		const struct test_pin *tp = &test_pins[i];

		gpio_init(tp->pin);
		gpio_put(tp->pin, 0);
		if (tp->open_drain) {
			/* Output value stays 0; only the direction changes. */
			gpio_pull_up(tp->pin);
			gpio_set_dir(tp->pin, GPIO_IN);
		} else {
			gpio_set_dir(tp->pin, GPIO_OUT);
		}
	}
}

/* Runs in the timer interrupt every TICK_US. */
static bool on_tick(repeating_timer_t *rt) {
	(void)rt;
	uint32_t n = ++tick_count;

	for (uint i = 0; i < NUM_TEST_PINS; i++) {
		test_pin_write(&test_pins[i], (n >> i) & 1u);
	}
	return true;
}

int main(void) {
	repeating_timer_t timer;
	uint32_t seconds = 0;

	log_init();
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);
	test_pins_init();

	LOG("pin test start, tick=%u us\r\n", TICK_US);
	for (uint i = 0; i < NUM_TEST_PINS; i++) {
		LOG("  CH%u = %s, %u Hz\r\n", i, test_pins[i].name,
		    1000000u / (TICK_US * 2u << i));
	}

	/* A negative delay means "start to start", so ticks do not drift. */
	add_repeating_timer_us(-TICK_US, on_tick, NULL, &timer);

	while (1) {
		gpio_put(PIN_LED, seconds & 1u);
		LOG("alive %u s, ticks=%u\r\n", (unsigned)seconds, (unsigned)tick_count);
		seconds++;
		sleep_ms(1000);
	}
}
