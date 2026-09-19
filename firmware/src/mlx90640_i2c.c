/*
 * I2C functions required by the Melexis MLX90640 library.
 *
 * The Melexis library (third_party/mlx90640-library) does not talk to any
 * hardware itself. It calls the functions declared in MLX90640_I2C_Driver.h,
 * and each platform must provide them. This file provides them on top of
 * i2c_bus. The behavior follows the Melexis reference driver:
 *   - return 0 on success, -1 (NACK) if the device does not answer
 *   - I2CWrite reads the register back and returns -2 if it differs
 */

#include <stdint.h>

#include "MLX90640_I2C_Driver.h"

#include "i2c_bus.h"

#define DEFAULT_FREQ_HZ		400000

void MLX90640_I2CInit(void) {
	i2c_bus_init(DEFAULT_FREQ_HZ);
}

/* The Melexis API gives the frequency in kHz. */
void MLX90640_I2CFreqSet(int freq) {
	i2c_bus_set_freq((uint)freq * 1000u);
}

int MLX90640_I2CGeneralReset(void) {
	if (i2c_bus_general_reset() != I2C_BUS_OK) {
		return -MLX90640_I2C_NACK_ERROR;
	}
	return 0;
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t nMemAddressRead, uint16_t *data) {
	if (i2c_bus_read_words(slaveAddr, startAddress, data, nMemAddressRead) != I2C_BUS_OK) {
		return -MLX90640_I2C_NACK_ERROR;
	}
	return 0;
}

int MLX90640_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data) {
	uint16_t check;

	if (i2c_bus_write_word(slaveAddr, writeAddress, data) != I2C_BUS_OK) {
		return -MLX90640_I2C_NACK_ERROR;
	}
	/* Read back to make sure the value was stored. Some registers (like
	 * the status register) change by themselves, so callers may ignore
	 * this error, as the Melexis library does. */
	if (i2c_bus_read_words(slaveAddr, writeAddress, &check, 1) != I2C_BUS_OK) {
		return -MLX90640_I2C_NACK_ERROR;
	}
	if (check != data) {
		return -MLX90640_I2C_WRITE_ERROR;
	}
	return 0;
}
