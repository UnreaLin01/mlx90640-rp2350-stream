/*
 * Main firmware.
 *
 * Current stage (M3): read subpages from the MLX90640 continuously and
 * report timing. Nothing is sent to the PC yet (that is M4).
 *
 * Timing marks for the logic analyzer:
 *   mark A (GP6, CH2): high while one subpage is being read
 *   mark B (GP7, CH3): toggles each time a new subpage is ready, so the
 *                      time between B edges is the subpage period
 *
 * Once per second a status line goes to RTT.
 */

#include <stdint.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"

#include "board.h"
#include "log.h"
#include "sensor.h"

#ifndef SENSOR_RATE
#define SENSOR_RATE	SENSOR_RATE_32HZ
#endif

/* How often to ask the sensor "is new data ready?" while waiting. */
#define POLL_US		200
/* Give up waiting after this long (slowest rate is 0.5 Hz). */
#define WAIT_TIMEOUT_US	3000000

static uint16_t ee_data[MLX90640_EEPROM_DUMP_NUM];
static uint16_t frame[SENSOR_FRAME_WORDS];

/* Statistics for one reporting interval. */
struct stats {
	uint32_t subpages;
	uint32_t read_min, read_max;	/* read time, us */
	uint32_t gap_min, gap_max;	/* time between new-data events, us */
	uint32_t order_errors;		/* subpage number did not alternate */
	uint32_t read_errors;		/* Melexis read / check errors */
	uint32_t wait_errors;		/* timeouts or I2C errors while waiting */
};

static void stats_reset(struct stats *s) {
	*s = (struct stats){ .read_min = UINT32_MAX, .gap_min = UINT32_MAX };
}

static void pins_init(void) {
	const uint pins[] = { PIN_LED, PIN_MARK_A, PIN_MARK_B };

	for (uint i = 0; i < sizeof(pins) / sizeof(pins[0]); i++) {
		gpio_init(pins[i]);
		gpio_set_dir(pins[i], GPIO_OUT);
		gpio_put(pins[i], 0);
	}
}

int main(void) {
	struct stats st;
	uint32_t total = 0, total_errors = 0;
	uint32_t last_ready = 0, last_report;
	int last_subpage = -1;
	bool mark_b = false;
	int ret;

	log_init();
	pins_init();
	LOG("M3 boot, sys_clk=%u Hz, rate code %d\r\n",
	    (unsigned)clock_get_hz(clk_sys), SENSOR_RATE);

	ret = sensor_init(SENSOR_RATE, ee_data);
	if (ret != SENSOR_OK) {
		/* Nothing useful to do without the sensor: blink fast. */
		while (1) {
			gpio_xor_mask(1u << PIN_LED);
			sleep_ms(100);
		}
	}

	stats_reset(&st);
	last_report = time_us_32();

	while (1) {
		uint32_t t_ready, t_done;
		int subpage;

		/* --- Wait for the next subpage --------------------------------- */
		ret = sensor_wait_data_ready(POLL_US, WAIT_TIMEOUT_US);
		t_ready = time_us_32();
		if (ret != SENSOR_OK) {
			st.wait_errors++;
			LOG("wait error %d\r\n", ret);
			continue;
		}
		mark_b = !mark_b;
		gpio_put(PIN_MARK_B, mark_b);

		/* --- Read it ---------------------------------------------------- */
		gpio_put(PIN_MARK_A, 1);
		subpage = sensor_read_subpage(frame);
		gpio_put(PIN_MARK_A, 0);
		t_done = time_us_32();

		/* --- Bookkeeping ------------------------------------------------ */
		if (subpage < 0) {
			st.read_errors++;
			LOG("read error %d\r\n", subpage);
		} else {
			uint32_t read_us = t_done - t_ready;

			st.subpages++;
			total++;
			st.read_min = read_us < st.read_min ? read_us : st.read_min;
			st.read_max = read_us > st.read_max ? read_us : st.read_max;
			if (last_ready) {
				uint32_t gap = t_ready - last_ready;

				st.gap_min = gap < st.gap_min ? gap : st.gap_min;
				st.gap_max = gap > st.gap_max ? gap : st.gap_max;
			}
			if (last_subpage >= 0 && subpage == last_subpage) {
				st.order_errors++;
			}
			last_subpage = subpage;
		}
		last_ready = t_ready;

		/* --- Report once per second ------------------------------------- */
		if (t_done - last_report >= 1000000u) {
			total_errors += st.read_errors + st.wait_errors + st.order_errors;
			LOG("%u subpages/s | read %u..%u us | gap %u..%u us | "
			    "order_err %u read_err %u wait_err %u | total %u, errors %u\r\n",
			    (unsigned)st.subpages, (unsigned)st.read_min, (unsigned)st.read_max,
			    (unsigned)st.gap_min, (unsigned)st.gap_max,
			    (unsigned)st.order_errors, (unsigned)st.read_errors,
			    (unsigned)st.wait_errors, (unsigned)total, (unsigned)total_errors);
			gpio_xor_mask(1u << PIN_LED);
			stats_reset(&st);
			last_report = t_done;
		}
	}
}
