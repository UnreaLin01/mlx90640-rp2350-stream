#ifndef MLX90640_H
#define MLX90640_H

/*
 * Project-wide MLX90640 settings.
 *
 * The sensor driver itself is the Melexis library (MLX90640_API.h);
 * its hardware access is in mlx90640_i2c.c.
 */

#include "MLX90640_API.h"

#define MLX90640_ADDR		0x33	/* default 7-bit I2C address */

/* EEPROM word 0x240F holds the I2C address in its low byte. */
#define MLX90640_EE_I2C_ADDR_INDEX	(0x240F - MLX90640_EEPROM_START_ADDRESS)

#endif
