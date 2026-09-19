/*
 * I2C bus driver. See i2c_bus.h.
 */

#include "i2c_bus.h"

#include "pico/stdlib.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/i2c.h"

#include "board.h"

#define BUS			i2c0

/* Longest time we wait for one byte. One byte at 100 kHz takes 90 us. */
#define BYTE_TIMEOUT_US		1000

/* Reads of at least this many words use DMA; shorter ones use the SDK. */
#define DMA_MIN_WORDS		8
/* Biggest DMA read: one full MLX90640 EEPROM or frame block. */
#define DMA_MAX_WORDS		832

static uint current_baud;
static void (*idle_hook)(void);

/* DMA channels, claimed once at init (never fixed numbers, so other code
 * such as the Ethernet driver can claim its own channels freely). */
static int dma_cmd_ch = -1;
static int dma_rx_ch = -1;

/* Command words for one DMA read: 2 register address bytes + 1 read
 * command per data byte. */
static uint32_t dma_cmd_buf[2 + DMA_MAX_WORDS * 2];

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

	/* If the receive FIFO is full, pause the bus instead of losing data.
	 * (IC_CON can only be changed while the block is disabled.) */
	i2c_get_hw(BUS)->enable = 0;
	hw_set_bits(&i2c_get_hw(BUS)->con, I2C_IC_CON_RX_FIFO_FULL_HLD_CTRL_BITS);
	i2c_get_hw(BUS)->enable = 1;

	if (dma_cmd_ch < 0) {
		dma_cmd_ch = dma_claim_unused_channel(true);
		dma_rx_ch = dma_claim_unused_channel(true);
	}

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

void i2c_bus_set_scl_counts(uint lcnt, uint hcnt) {
	i2c_hw_t *hw = i2c_get_hw(BUS);

	/* Timing registers can only be changed while the block is disabled. */
	hw->enable = 0;
	hw->fs_scl_lcnt = lcnt;
	hw->fs_scl_hcnt = hcnt;
	hw->enable = 1;
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

/* The sensor sends the high byte first, but the MCU stores the low byte
 * first. Reads go straight into the caller's buffer (to save RAM), then
 * this swaps the two bytes of each word in place. */
static void swap_bytes(uint16_t *dst, uint16_t count) {
	const uint8_t *bytes = (const uint8_t *)dst;

	for (uint16_t i = 0; i < count; i++) {
		dst[i] = (uint16_t)((bytes[2 * i] << 8) | bytes[2 * i + 1]);
	}
}

/* Short reads: the SDK's blocking functions. */
static int read_blocking(uint8_t addr, uint16_t reg, uint16_t *dst, uint16_t count) {
	uint8_t reg_bytes[2] = { reg >> 8, reg & 0xff };
	size_t len = (size_t)count * 2;
	int ret;

	/* Send the register address, then a repeated START (no STOP) and read. */
	ret = i2c_write_timeout_per_char_us(BUS, addr, reg_bytes, 2, true, BYTE_TIMEOUT_US);
	ret = map_result(ret, 2);
	if (ret != I2C_BUS_OK) {
		return ret;
	}
	ret = i2c_read_timeout_per_char_us(BUS, addr, (uint8_t *)dst, len, false, BYTE_TIMEOUT_US);
	return map_result(ret, len);
}

/* ------------------------------------------------------------------------
 * DMA reads
 *
 * The SDK read function handles one byte at a time: it waits for each
 * byte before asking for the next one, which leaves a gap on the bus after
 * every byte (about 0.8 us at 1 MHz). For long reads we let two DMA
 * channels keep the I2C FIFOs busy instead, so the bytes follow each other
 * without gaps and the CPU is free:
 *
 *   cmd channel: copies command words from dma_cmd_buf into IC_DATA_CMD.
 *                Each word is "send this byte" or "read one byte", plus
 *                RESTART / STOP flags.
 *   rx channel:  copies each received byte from IC_DATA_CMD into the
 *                caller's buffer.
 *
 * One transfer on the wire:
 *   START, addr+W, reg high, reg low, RESTART, addr+R, data ... data, STOP
 * ------------------------------------------------------------------------ */

/* Stop both channels and bring the I2C block back to idle after an error. */
static void dma_read_abort(i2c_hw_t *hw) {
	dma_channel_abort(dma_cmd_ch);
	dma_channel_abort(dma_rx_ch);
	(void)hw->clr_tx_abrt;
	/* Wait (briefly) for the STOP the block sends after an abort. */
	absolute_time_t until = make_timeout_time_us(1000);
	while ((hw->status & I2C_IC_STATUS_ACTIVITY_BITS) && !time_reached(until)) {
		tight_loop_contents();
	}
	/* Throw away any bytes still in the receive FIFO. */
	while (hw->rxflr) {
		(void)hw->data_cmd;
	}
}

static int read_dma(uint8_t addr, uint16_t reg, uint16_t *dst, uint16_t count) {
	i2c_hw_t *hw = i2c_get_hw(BUS);
	uint nbytes = (uint)count * 2;
	uint n = 0;
	dma_channel_config c;
	absolute_time_t until;

	/* Build the command list. */
	dma_cmd_buf[n++] = reg >> 8;
	dma_cmd_buf[n++] = reg & 0xff;
	for (uint i = 0; i < nbytes; i++) {
		uint32_t cmd = I2C_IC_DATA_CMD_CMD_BITS;	/* read one byte */

		if (i == 0) {
			cmd |= I2C_IC_DATA_CMD_RESTART_BITS;
		}
		if (i == nbytes - 1) {
			cmd |= I2C_IC_DATA_CMD_STOP_BITS;
		}
		dma_cmd_buf[n++] = cmd;
	}

	/* The target address can only be changed while the block is disabled. */
	hw->enable = 0;
	hw->tar = addr;
	hw->enable = 1;
	(void)hw->clr_tx_abrt;
	(void)hw->clr_stop_det;

	/* Start the receive side first, so no byte is missed. */
	c = dma_channel_get_default_config(dma_rx_ch);
	channel_config_set_transfer_data_size(&c, DMA_SIZE_8);
	channel_config_set_read_increment(&c, false);
	channel_config_set_write_increment(&c, true);
	channel_config_set_dreq(&c, i2c_get_dreq(BUS, false));
	dma_channel_configure(dma_rx_ch, &c, dst, &hw->data_cmd, nbytes, true);

	c = dma_channel_get_default_config(dma_cmd_ch);
	channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
	channel_config_set_read_increment(&c, true);
	channel_config_set_write_increment(&c, false);
	channel_config_set_dreq(&c, i2c_get_dreq(BUS, true));
	dma_channel_configure(dma_cmd_ch, &c, &hw->data_cmd, dma_cmd_buf, n, true);

	/* Wait for the last byte. A NACK makes the block abort the transfer. */
	until = make_timeout_time_us(nbytes * 20u + 1000u);
	while (dma_channel_is_busy(dma_rx_ch)) {
		i2c_bus_idle();
		if (hw->raw_intr_stat & I2C_IC_RAW_INTR_STAT_TX_ABRT_BITS) {
			dma_read_abort(hw);
			return I2C_BUS_ERR_NACK;
		}
		if (time_reached(until)) {
			dma_read_abort(hw);
			return I2C_BUS_ERR_TIMEOUT;
		}
	}

	/* Wait for the STOP, so the bus is idle before the next transfer. */
	until = make_timeout_time_us(1000);
	while (!(hw->raw_intr_stat & I2C_IC_RAW_INTR_STAT_STOP_DET_BITS)) {
		if (time_reached(until)) {
			return I2C_BUS_ERR_TIMEOUT;
		}
	}
	(void)hw->clr_stop_det;
	return I2C_BUS_OK;
}

int i2c_bus_read_words(uint8_t addr, uint16_t reg, uint16_t *dst, uint16_t count) {
	int ret;

	if (count >= DMA_MIN_WORDS && count <= DMA_MAX_WORDS) {
		ret = read_dma(addr, reg, dst, count);
	} else {
		ret = read_blocking(addr, reg, dst, count);
	}
	if (ret == I2C_BUS_OK) {
		swap_bytes(dst, count);
	}
	return ret;
}

int i2c_bus_write_word(uint8_t addr, uint16_t reg, uint16_t value) {
	uint8_t buf[4] = { reg >> 8, reg & 0xff, value >> 8, value & 0xff };
	int ret;

	ret = i2c_write_timeout_per_char_us(BUS, addr, buf, sizeof(buf), false, BYTE_TIMEOUT_US);
	return map_result(ret, sizeof(buf));
}

void i2c_bus_set_idle_hook(void (*hook)(void)) {
	idle_hook = hook;
}

void i2c_bus_idle(void) {
	if (idle_hook) {
		idle_hook();
	}
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
