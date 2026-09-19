#ifndef BOARD_H
#define BOARD_H

/*
 * Pin map for the W6300-EVB-Pico2.
 *
 * All pin numbers live here so the wiring is defined in one place.
 * GPIO15-22 are used by the W6300 Ethernet chip. Do not use them.
 *
 * Logic 8 channel for each measured pin:
 *   CH0 = SDA, CH1 = SCL, CH2 = mark A, CH3 = mark B
 * (For the Logic 2 I2C decoder: SDA = CH0, SCL = CH1.)
 */

#define PIN_I2C_SDA		4	/* I2C0 SDA to MLX90640 */
#define PIN_I2C_SCL		5	/* I2C0 SCL to MLX90640 */
#define PIN_MARK_A		6	/* timing mark for the logic analyzer */
#define PIN_MARK_B		7	/* timing mark for the logic analyzer */
#define PIN_LED			25	/* on-board LED */

#endif
