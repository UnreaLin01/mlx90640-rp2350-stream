/*
 * Main firmware.
 *
 * Current stage (M4): read subpages from the MLX90640 continuously and
 * stream the raw data to the PC over USB CDC (docs/protocol.md):
 *   - every subpage is sent as a SUBPAGE block
 *   - the EEPROM is sent when the PC opens the port, then every 2 s, so a
 *     receiver that starts late still gets the calibration data
 *   - a STATUS block with counters is sent once per second
 * Logs go to RTT only; USB carries packets only.
 *
 * Single core, no RTOS: the USB stack's background task runs whenever the
 * CPU would otherwise wait (while polling the sensor, and while the DMA
 * moves I2C data), through the i2c_bus idle hook.
 *
 * Timing marks for the logic analyzer:
 *   mark A (GP6, CH2): high while one subpage is being read
 *   mark B (GP7, CH3): toggles each time a new subpage is ready
 */

#include <stdint.h>

#include "pico/stdlib.h"
#include "hardware/clocks.h"

#include "board.h"
#include "i2c_bus.h"
#include "log.h"
#include "sensor.h"
#include "stream.h"
#include "transport.h"

#ifndef SENSOR_RATE
#define SENSOR_RATE	SENSOR_RATE_32HZ
#endif

/* How often to ask the sensor "is new data ready?" while waiting. */
#define POLL_US			200
/* Give up waiting after this long (slowest rate is 0.5 Hz). */
#define WAIT_TIMEOUT_US		3000000
/* Resend the EEPROM this often. */
#define EEPROM_PERIOD_US	2000000
#define REPORT_PERIOD_US	1000000

static uint16_t ee_data[MLX90640_EEPROM_DUMP_NUM];
static uint16_t frame[SENSOR_FRAME_WORDS];

/* Counters since boot (sent in STATUS packets). */
static struct proto_status totals;

/* Statistics for one reporting interval (RTT log). */
struct stats {
	uint32_t subpages;
	uint32_t read_min, read_max;	/* read time, us */
	uint32_t gap_min, gap_max;	/* time between new-data events, us */
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

/* Blink fast forever: the sensor did not start. */
static void fail_forever(void) {
	while (1) {
		gpio_xor_mask(1u << PIN_LED);
		for (int i = 0; i < 100; i++) {
			transport_poll();
			sleep_ms(1);
		}
	}
}

int main(void) {
	struct stats st;
	uint64_t last_ready = 0, last_report, last_eeprom = 0;
	bool was_connected = false;
	bool mark_b = false;
	int last_subpage = -1;
	int ret;

	log_init();
	pins_init();
	LOG("M4 boot, sys_clk=%u Hz, rate code %d\r\n",
	    (unsigned)clock_get_hz(clk_sys), SENSOR_RATE);

	/* USB first, so the PC sees the port while the sensor starts up. */
	transport_init();
	stream_init();
	i2c_bus_set_idle_hook(transport_poll);

	ret = sensor_init(SENSOR_RATE, ee_data);
	if (ret != SENSOR_OK) {
		fail_forever();
	}

	stats_reset(&st);
	last_report = time_us_64();

	while (1) {
		uint64_t t_ready, t_done, now;
		int subpage;
		bool connected;

		/* --- Wait for the next subpage --------------------------------- */
		ret = sensor_wait_data_ready(POLL_US, WAIT_TIMEOUT_US);
		t_ready = time_us_64();
		if (ret != SENSOR_OK) {
			totals.wait_errors++;
			LOG("wait error %d\r\n", ret);
			continue;
		}
		mark_b = !mark_b;
		gpio_put(PIN_MARK_B, mark_b);

		/* --- Read it ---------------------------------------------------- */
		gpio_put(PIN_MARK_A, 1);
		subpage = sensor_read_subpage(frame);
		gpio_put(PIN_MARK_A, 0);
		t_done = time_us_64();

		/* --- Send it and keep count ------------------------------------- */
		if (subpage < 0) {
			totals.read_errors++;
			LOG("read error %d\r\n", subpage);
		} else {
			uint32_t read_us = (uint32_t)(t_done - t_ready);

			stream_send_subpage(frame, subpage, t_ready);
			totals.subpages++;
			st.subpages++;
			st.read_min = read_us < st.read_min ? read_us : st.read_min;
			st.read_max = read_us > st.read_max ? read_us : st.read_max;
			if (last_ready) {
				uint32_t gap = (uint32_t)(t_ready - last_ready);

				st.gap_min = gap < st.gap_min ? gap : st.gap_min;
				st.gap_max = gap > st.gap_max ? gap : st.gap_max;
			}
			if (last_subpage >= 0 && subpage == last_subpage) {
				totals.order_errors++;
			}
			last_subpage = subpage;
		}
		last_ready = t_ready;

		/* --- EEPROM: right after the PC connects, then every 2 s -------- */
		now = time_us_64();
		connected = transport_connected();
		if (connected && (!was_connected || now - last_eeprom >= EEPROM_PERIOD_US)) {
			stream_send_eeprom(ee_data, now);
			last_eeprom = now;
		}
		was_connected = connected;

		/* --- Once per second: STATUS packet and RTT line ---------------- */
		if (now - last_report >= REPORT_PERIOD_US) {
			totals.tx_dropped = stream_dropped();
			totals.read_us_max = st.read_max;
			stream_send_status(&totals, now);
			LOG("%u subpages/s | read %u..%u us | gap %u..%u us | usb %s | "
			    "total %u, read_err %u order_err %u wait_err %u dropped %u\r\n",
			    (unsigned)st.subpages, (unsigned)st.read_min, (unsigned)st.read_max,
			    (unsigned)st.gap_min, (unsigned)st.gap_max,
			    connected ? "open" : "closed", (unsigned)totals.subpages,
			    (unsigned)totals.read_errors, (unsigned)totals.order_errors,
			    (unsigned)totals.wait_errors, (unsigned)totals.tx_dropped);
			gpio_xor_mask(1u << PIN_LED);
			stats_reset(&st);
			last_report = now;
		}
	}
}
