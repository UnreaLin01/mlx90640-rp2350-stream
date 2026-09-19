/*
 * Rise time test for the I2C lines (M2).
 *
 * Runs the PIO program in rise_test.pio: SDA and SCL are pulled low and
 * released over and over, and mark A (GP6) changes at the exact same
 * moment. Capture CH0 (SDA), CH1 (SCL) and CH2 (mark A) at 100 MS/s and
 * run host/tools/check_rise.py.
 *
 * The pads are set up like the real I2C setup in i2c_bus.c (internal
 * pull-ups on), so the result matches what the I2C block sees.
 */

#include "pico/stdlib.h"
#include "hardware/pio.h"

#include "board.h"
#include "log.h"
#include "rise_test.pio.h"

/* SDA must be the pin just below SCL, because PIO drives them as a pair. */
#if PIN_I2C_SCL != PIN_I2C_SDA + 1
#error "rise test needs SCL = SDA + 1"
#endif

/* 1 + 3/256: see rise_test_program_init() for why it is not exactly 1. */
#define PIO_CLKDIV	(1.0f + 3.0f / 256.0f)

int main(void) {
	PIO pio = pio0;
	uint sm = 0;
	uint offset;
	uint32_t seconds = 0;

	log_init();
	gpio_init(PIN_LED);
	gpio_set_dir(PIN_LED, GPIO_OUT);

	offset = pio_add_program(pio, &rise_test_program);
	rise_test_program_init(pio, sm, offset, PIN_I2C_SDA, PIN_MARK_A, PIO_CLKDIV);
	/* Same pull-ups as the real I2C setup. pio_gpio_init() keeps pulls. */
	gpio_pull_up(PIN_I2C_SDA);
	gpio_pull_up(PIN_I2C_SCL);

	LOG("rise test running, PIO clkdiv=1+3/256\r\n");
	while (1) {
		gpio_put(PIN_LED, seconds & 1u);
		LOG("alive %u s\r\n", (unsigned)seconds);
		seconds++;
		sleep_ms(1000);
	}
}
