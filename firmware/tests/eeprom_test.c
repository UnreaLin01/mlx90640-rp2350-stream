/*
 * EEPROM read test (M2).
 *
 * Reads the whole MLX90640 EEPROM (832 words) once per second at
 * I2C_TEST_HZ, using the Melexis library (MLX90640_DumpEE).
 *
 *   - The first good read is printed to RTT as a hex dump, so it can be
 *     compared with the Logic 8 I2C decoder.
 *   - Every later read is compared with the first one. Any difference
 *     means the bus is not reliable at this clock rate.
 *   - Mark A (GP6) is high while a read runs, so the read time can be
 *     measured on the logic analyzer.
 *
 * Build settings (set per target in CMakeLists.txt):
 *   I2C_TEST_HZ       I2C clock rate
 *   READ_INTERVAL_MS  pause between reads (0 = read back to back, for the
 *                     long-run test)
 *   REPORT_EVERY      print a status line every N reads. Errors and
 *                     differences are always printed.
 */

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "pico/stdlib.h"

#include "board.h"
#include "i2c_bus.h"
#include "log.h"
#include "mlx90640.h"

#ifndef I2C_TEST_HZ
#error "I2C_TEST_HZ must be set by the build"
#endif

#ifndef READ_INTERVAL_MS
#define READ_INTERVAL_MS	1000
#endif

#ifndef REPORT_EVERY
#define REPORT_EVERY		1
#endif

#define WORDS_PER_LINE	16

static uint16_t ee_first[MLX90640_EEPROM_DUMP_NUM];
static uint16_t ee_now[MLX90640_EEPROM_DUMP_NUM];

static void dump_eeprom(const uint16_t *ee) {
	for (uint i = 0; i < MLX90640_EEPROM_DUMP_NUM; i += WORDS_PER_LINE) {
		/* RTT printf has a small line buffer, so print word by word. */
		LOG("EE %04X:", MLX90640_EEPROM_START_ADDRESS + i);
		for (uint j = 0; j < WORDS_PER_LINE; j++) {
			LOG(" %04X", ee[i + j]);
		}
		LOG("\r\n");
	}
}

static void log_timing(void) {
	struct i2c_bus_timing t;

	i2c_bus_get_timing(&t);
	LOG("I2C baud=%u clk=%u lcnt=%u hcnt=%u spklen=%u sda_hold=%u\r\n",
	    t.baud_hz, t.clk_hz, t.lcnt, t.hcnt, t.spklen, t.sda_hold);
}

int main(void) {
	uint32_t reads = 0, bad_reads = 0, errors = 0, bad_words = 0;
	uint32_t t_min = UINT32_MAX, t_max = 0;
	uint32_t t_start;
	bool have_first = false;

	log_init();
	gpio_init(PIN_MARK_A);
	gpio_set_dir(PIN_MARK_A, GPIO_OUT);
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);

	i2c_bus_init(I2C_TEST_HZ);
	LOG("eeprom test, target %u Hz, interval %u ms, report every %u\r\n",
	    I2C_TEST_HZ, READ_INTERVAL_MS, REPORT_EVERY);
	log_timing();
	t_start = time_us_32();

	while (1) {
		uint32_t t0, t1, dt;
		uint diff = 0;
		int ret;

		gpio_put(PIN_MARK_A, 1);
		t0 = time_us_32();
		ret = MLX90640_DumpEE(MLX90640_ADDR, ee_now);
		t1 = time_us_32();
		gpio_put(PIN_MARK_A, 0);
		reads++;
		dt = t1 - t0;

		if (ret != 0) {
			/* Bus error: always report. */
			errors++;
			LOG("read %u: I2C error %d (no ACK or timeout)\r\n", (unsigned)reads, ret);
		} else if (!have_first) {
			/* First good read becomes the reference. */
			memcpy(ee_first, ee_now, sizeof(ee_first));
			have_first = true;
			LOG("read %u: OK, %u us, I2C addr word 0x240F=%04X\r\n", (unsigned)reads,
			    (unsigned)dt, ee_now[MLX90640_EE_I2C_ADDR_INDEX]);
			dump_eeprom(ee_first);
		} else {
			/* Compare with the reference. Report every bad word. */
			for (uint i = 0; i < MLX90640_EEPROM_DUMP_NUM; i++) {
				if (ee_now[i] != ee_first[i]) {
					diff++;
					LOG("read %u: word %04X is %04X, expected %04X\r\n", (unsigned)reads,
					    MLX90640_EEPROM_START_ADDRESS + i, ee_now[i], ee_first[i]);
				}
			}
			if (diff) {
				bad_reads++;
				bad_words += diff;
			}
		}

		if (ret == 0) {
			t_min = dt < t_min ? dt : t_min;
			t_max = dt > t_max ? dt : t_max;
		}

		if (reads % REPORT_EVERY == 0 || diff) {
			LOG("read %u: %u s, last %u us (min %u, max %u), bad_reads=%u, "
			    "bad_words=%u, errors=%u\r\n",
			    (unsigned)reads, (unsigned)((t1 - t_start) / 1000000u), (unsigned)dt,
			    (unsigned)t_min, (unsigned)t_max, (unsigned)bad_reads,
			    (unsigned)bad_words, (unsigned)errors);
			gpio_put(PIN_LED, (reads / REPORT_EVERY) & 1u);
		}

		if (READ_INTERVAL_MS) {
			sleep_ms(READ_INTERVAL_MS);
		}
	}
}
