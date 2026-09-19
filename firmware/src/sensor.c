/*
 * MLX90640 sensor control. See sensor.h.
 */

#include "sensor.h"

#include "pico/stdlib.h"

#include "MLX90640_I2C_Driver.h"

#include "i2c_bus.h"
#include "log.h"

#define I2C_FREQ_HZ	1000000

/*
 * SCL timing at 1 MHz, in clk_sys cycles (150 MHz, 6.67 ns).
 *
 * The SDK picks lcnt=90 / hcnt=60, which gives only about 806 kHz on this
 * board: the I2C block adds some cycles, and it waits for SCL to really be
 * high before it counts the high time, which takes long here because the
 * lines rise slowly (about 220 ns, see docs/m2_i2c.md).
 *
 * These values were worked out from the measured rise time:
 *   - high time at 70% of VDD stays about 280 ns (I2C limit: 260 ns)
 *   - low time at 30% of VDD stays about 630 ns (I2C limit: 500 ns;
 *     project rule: at least 600 ns)
 *   - SDA setup before SCL rises stays about 150 ns (I2C limit: 50 ns)
 * See docs/m3_timing.md for the measured result.
 */
#define SCL_LCNT	77
#define SCL_HCNT	57

int sensor_init(enum sensor_rate rate, uint16_t *ee) {
	struct i2c_bus_timing t;
	int ret;

	i2c_bus_init(I2C_FREQ_HZ);
	i2c_bus_set_scl_counts(SCL_LCNT, SCL_HCNT);
	i2c_bus_get_timing(&t);
	LOG("I2C baud=%u lcnt=%u hcnt=%u spklen=%u sda_hold=%u\r\n",
	    t.baud_hz, t.lcnt, t.hcnt, t.spklen, t.sda_hold);

	ret = MLX90640_DumpEE(MLX90640_ADDR, ee);
	if (ret != 0) {
		LOG("sensor: EEPROM read failed (%d)\r\n", ret);
		return ret;
	}

	ret = MLX90640_SetRefreshRate(MLX90640_ADDR, (uint8_t)rate);
	if (ret != 0) {
		LOG("sensor: set refresh rate failed (%d)\r\n", ret);
		return ret;
	}
	LOG("sensor: refresh code %d (read back %d)\r\n", (int)rate, sensor_get_rate());
	return SENSOR_OK;
}

int sensor_wait_data_ready(uint32_t poll_us, uint32_t timeout_us) {
	uint32_t start = time_us_32();
	uint16_t status;

	while (1) {
		if (MLX90640_I2CRead(MLX90640_ADDR, MLX90640_STATUS_REG, 1, &status) != 0) {
			return -MLX90640_I2C_NACK_ERROR;
		}
		if (MLX90640_GET_DATA_READY(status)) {
			return SENSOR_OK;
		}
		if (time_us_32() - start > timeout_us) {
			return SENSOR_ERR_TIMEOUT;
		}
		/* Wait before the next poll, running the idle hook meanwhile. */
		uint32_t t0 = time_us_32();
		while (time_us_32() - t0 < poll_us) {
			i2c_bus_idle();
		}
	}
}

int sensor_read_subpage(uint16_t *frame) {
	/* The Melexis function checks the flag again (it is already set, so it
	 * goes on at once), clears it, reads pixels + aux data + control
	 * register, and checks the data. */
	return MLX90640_GetFrameData(MLX90640_ADDR, frame);
}

int sensor_get_rate(void) {
	return MLX90640_GetRefreshRate(MLX90640_ADDR);
}
