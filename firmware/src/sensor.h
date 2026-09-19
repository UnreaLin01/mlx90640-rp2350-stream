#ifndef SENSOR_H
#define SENSOR_H

/*
 * MLX90640 sensor control: setup, waiting for new data, and reading one
 * subpage. Reading follows the Melexis library (MLX90640_GetFrameData).
 *
 * The sensor measures the image in two halves ("subpages" 0 and 1, in a
 * chess board pattern) and sets a "new data" flag in its status register
 * each time a subpage is ready.
 */

#include <stdbool.h>
#include <stdint.h>

#include "mlx90640.h"

/* Refresh rate codes for the control register (bits 7..9). */
enum sensor_rate {
	SENSOR_RATE_0HZ5 = 0,
	SENSOR_RATE_1HZ,
	SENSOR_RATE_2HZ,
	SENSOR_RATE_4HZ,
	SENSOR_RATE_8HZ,
	SENSOR_RATE_16HZ,
	SENSOR_RATE_32HZ,
	SENSOR_RATE_64HZ,
};

/* Raw data of one subpage, as filled in by MLX90640_GetFrameData:
 * [0..767] pixels, [768..831] aux data, [832] control reg, [833] subpage. */
#define SENSOR_FRAME_WORDS	834

#define SENSOR_OK		0
#define SENSOR_ERR_TIMEOUT	-100	/* no new data in time */

/*
 * Set up the I2C bus and the sensor, and read the EEPROM into `ee`
 * (832 words). Returns SENSOR_OK or a negative Melexis error code.
 */
int sensor_init(enum sensor_rate rate, uint16_t *ee);

/*
 * Wait until the sensor has a new subpage ready. Polls the status
 * register every `poll_us`. Returns SENSOR_OK, SENSOR_ERR_TIMEOUT, or a
 * negative I2C error.
 */
int sensor_wait_data_ready(uint32_t poll_us, uint32_t timeout_us);

/*
 * Read the new subpage (call after sensor_wait_data_ready). Returns the
 * subpage number (0 or 1) or a negative Melexis error code.
 */
int sensor_read_subpage(uint16_t *frame);

/* Read back the refresh rate code from the control register. */
int sensor_get_rate(void);

#endif
