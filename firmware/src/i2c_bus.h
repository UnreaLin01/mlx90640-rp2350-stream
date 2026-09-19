#ifndef I2C_BUS_H
#define I2C_BUS_H

/*
 * I2C bus driver for the sensor bus (I2C0 on PIN_I2C_SDA / PIN_I2C_SCL).
 *
 * A thin layer over the Pico SDK that speaks the MLX90640 register format:
 * 16-bit register addresses and 16-bit data words, both sent high byte
 * first. Every call has a timeout, so a bad bus never hangs the firmware.
 */

#include <stdint.h>

#include "pico/types.h"

#define I2C_BUS_OK		0
#define I2C_BUS_ERR_NACK	-1	/* device did not answer (no ACK) */
#define I2C_BUS_ERR_TIMEOUT	-2	/* bus stuck or too slow */

/* Clock timing as programmed into the I2C block (for timing checks). */
struct i2c_bus_timing {
	uint baud_hz;		/* clock rate the SDK reports */
	uint clk_hz;		/* I2C block input clock */
	uint lcnt;		/* SCL low count, in clk cycles */
	uint hcnt;		/* SCL high count, in clk cycles */
	uint spklen;		/* spike filter length, in clk cycles */
	uint sda_hold;		/* SDA hold time after SCL falls, in clk cycles */
};

/* Set up the pins and the I2C block. Frees a stuck bus first. */
uint i2c_bus_init(uint freq_hz);

/* Change the clock rate. Returns the rate actually set. */
uint i2c_bus_set_freq(uint freq_hz);

void i2c_bus_get_timing(struct i2c_bus_timing *t);

/* Read `count` 16-bit words starting at register `reg`. */
int i2c_bus_read_words(uint8_t addr, uint16_t reg, uint16_t *dst, uint16_t count);

/* Write one 16-bit word to register `reg`. */
int i2c_bus_write_word(uint8_t addr, uint16_t reg, uint16_t value);

/* Send the I2C "general call reset" (address 0x00, data 0x06). */
int i2c_bus_general_reset(void);

#endif
