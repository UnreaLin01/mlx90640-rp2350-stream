/*
 * I2C bus driver. See i2c_bus.h.
 */

#include "i2c_bus.h"

#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/i2c.h"

#include "board.h"

#define BUS			i2c0

/* Longest time we wait for one byte. One byte at 100 kHz takes 90 us. */
#define BYTE_TIMEOUT_US		1000

static uint current_baud;

/* ------------------------------------------------------------------------
 * Bus recovery
 * ------------------------------------------------------------------------ */

/* Open-drain helpers: pull the line low, or let the pull-up take it high. */
static void line_low(uint pin) {
	gpio_put(pin, 0);
	gpio_set_dir(pin, GPIO_OUT);
}

static void line_release(uint pin) {
	gpio_set_dir(pin, GPIO_IN);
}

/*
 * Free a stuck bus.
 *
 * If the MCU was reset in the middle of a read, the sensor may still be
 * sending a byte and hold SDA low, waiting for more clock pulses. Up to 9
 * clock pulses let it finish that byte and let go of SDA. A STOP condition
 * (SDA going high while SCL is high) then puts the bus back to idle.
 */
static void bus_recover(void) {
	gpio_init(PIN_I2C_SDA);
	gpio_init(PIN_I2C_SCL);
	gpio_pull_up(PIN_I2C_SDA);
	gpio_pull_up(PIN_I2C_SCL);
	line_release(PIN_I2C_SDA);
	line_release(PIN_I2C_SCL);
	sleep_us(10);

	for (int i = 0; i < 9 && !gpio_get(PIN_I2C_SDA); i++) {
		line_low(PIN_I2C_SCL);
		sleep_us(5);
		line_release(PIN_I2C_SCL);
		sleep_us(5);
	}

	/* STOP: SDA low -> SCL high -> SDA high. */
	line_low(PIN_I2C_SCL);
	sleep_us(5);
	line_low(PIN_I2C_SDA);
	sleep_us(5);
	line_release(PIN_I2C_SCL);
	sleep_us(5);
	line_release(PIN_I2C_SDA);
	sleep_us(5);
}

/* ------------------------------------------------------------------------
 * Setup
 * ------------------------------------------------------------------------ */

uint i2c_bus_init(uint freq_hz) {
	bus_recover();

	current_baud = i2c_init(BUS, freq_hz);
	gpio_set_function(PIN_I2C_SDA, GPIO_FUNC_I2C);
	gpio_set_function(PIN_I2C_SCL, GPIO_FUNC_I2C);
	/* The sensor board has its own pull-ups. The weak internal ones
	 * (about 50 kOhm) stay on only as a backup. */
	gpio_pull_up(PIN_I2C_SDA);
	gpio_pull_up(PIN_I2C_SCL);
	return current_baud;
}

uint i2c_bus_set_freq(uint freq_hz) {
	current_baud = i2c_set_baudrate(BUS, freq_hz);
	return current_baud;
}

void i2c_bus_get_timing(struct i2c_bus_timing *t) {
	i2c_hw_t *hw = i2c_get_hw(BUS);

	t->baud_hz = current_baud;
	t->clk_hz = clock_get_hz(clk_sys);
	t->lcnt = hw->fs_scl_lcnt;
	t->hcnt = hw->fs_scl_hcnt;
	t->spklen = hw->fs_spklen;
	t->sda_hold = hw->sda_hold & I2C_IC_SDA_HOLD_IC_SDA_TX_HOLD_BITS;
}

/* ------------------------------------------------------------------------
 * Transfers
 * ------------------------------------------------------------------------ */

/* Turn an SDK result (byte count or negative error) into our error code. */
static int map_result(int ret, size_t expected) {
	if (ret == (int)expected) {
		return I2C_BUS_OK;
	}
	if (ret == PICO_ERROR_TIMEOUT) {
		return I2C_BUS_ERR_TIMEOUT;
	}
	return I2C_BUS_ERR_NACK;
}

int i2c_bus_read_words(uint8_t addr, uint16_t reg, uint16_t *dst, uint16_t count) {
	uint8_t reg_bytes[2] = { reg >> 8, reg & 0xff };
	uint8_t *bytes = (uint8_t *)dst;
	size_t len = (size_t)count * 2;
	int ret;

	/* Send the register address, then a repeated START (no STOP) and read. */
	ret = i2c_write_timeout_per_char_us(BUS, addr, reg_bytes, 2, true, BYTE_TIMEOUT_US);
	ret = map_result(ret, 2);
	if (ret != I2C_BUS_OK) {
		return ret;
	}

	/* Read straight into the caller's buffer to save RAM ... */
	ret = i2c_read_timeout_per_char_us(BUS, addr, bytes, len, false, BYTE_TIMEOUT_US);
	ret = map_result(ret, len);
	if (ret != I2C_BUS_OK) {
		return ret;
	}

	/* ... then swap the bytes of each word. The sensor sends the high byte
	 * first, but the MCU stores the low byte first. */
	for (uint16_t i = 0; i < count; i++) {
		dst[i] = (uint16_t)((bytes[2 * i] << 8) | bytes[2 * i + 1]);
	}
	return I2C_BUS_OK;
}

int i2c_bus_write_word(uint8_t addr, uint16_t reg, uint16_t value) {
	uint8_t buf[4] = { reg >> 8, reg & 0xff, value >> 8, value & 0xff };
	int ret;

	ret = i2c_write_timeout_per_char_us(BUS, addr, buf, sizeof(buf), false, BYTE_TIMEOUT_US);
	return map_result(ret, sizeof(buf));
}

int i2c_bus_general_reset(void) {
	uint8_t cmd = 0x06;
	int ret;

	/* Address 0x00 is the "general call" address. The SDK marks it as
	 * reserved, but only checks that when parameter checks are turned on
	 * (they are off by default), so the call goes through. */
	ret = i2c_write_timeout_per_char_us(BUS, 0x00, &cmd, 1, false, BYTE_TIMEOUT_US);
	return map_result(ret, 1);
}
