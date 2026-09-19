/*
 * PC-side wrapper around the Melexis MLX90640 library (third_party,
 * unmodified), built as a Windows DLL and used from Python with ctypes
 * (host/mlxstream/calc_melexis.py).
 *
 * Only the calculation functions are used on the PC. The library also has
 * functions that talk to the sensor over I2C; they are never called here,
 * but the linker needs the I2C functions to exist, so they are stubs that
 * always fail.
 *
 * Build: scripts/build_host_lib.ps1
 */

#include <stdint.h>

#include "MLX90640_API.h"
#include "MLX90640_I2C_Driver.h"

#define EXPORT	__declspec(dllexport)

/* ------------------------------------------------------------------------
 * Calculation API for Python
 * ------------------------------------------------------------------------ */

/* Size of the parameter struct, so Python can allocate it. */
EXPORT int mlxw_params_size(void) {
	return (int)sizeof(paramsMLX90640);
}

/* Unpack the calibration parameters from the 832 EEPROM words.
 * Returns 0, or a negative Melexis error (bad EEPROM / too many bad pixels). */
EXPORT int mlxw_extract(uint16_t *ee, paramsMLX90640 *params) {
	return MLX90640_ExtractParameters(ee, params);
}

/* frame: 834 words (833 from the device + subpage number at [833]). */
EXPORT float mlxw_get_ta(uint16_t *frame, const paramsMLX90640 *params) {
	return MLX90640_GetTa(frame, params);
}

EXPORT float mlxw_get_vdd(uint16_t *frame, const paramsMLX90640 *params) {
	return MLX90640_GetVdd(frame, params);
}

/* Object temperatures in degC. Only the pixels of this frame's subpage
 * are written into result[768]; the others keep their old values. */
EXPORT void mlxw_calculate_to(uint16_t *frame, const paramsMLX90640 *params,
                              float emissivity, float tr, float *result) {
	MLX90640_CalculateTo(frame, params, emissivity, tr, result);
}

/* Replace the broken and outlier pixels listed in the EEPROM with a value
 * from their neighbours. mode: 1 = chess pattern, 0 = interleaved. */
EXPORT void mlxw_bad_pixels_correction(paramsMLX90640 *params, float *result, int mode) {
	MLX90640_BadPixelsCorrection(params->brokenPixels, result, mode, params);
	MLX90640_BadPixelsCorrection(params->outlierPixels, result, mode, params);
}

/* ------------------------------------------------------------------------
 * I2C stubs (never used on the PC)
 * ------------------------------------------------------------------------ */

void MLX90640_I2CInit(void) {
}

int MLX90640_I2CGeneralReset(void) {
	return -MLX90640_I2C_NACK_ERROR;
}

int MLX90640_I2CRead(uint8_t slaveAddr, uint16_t startAddress,
                     uint16_t nMemAddressRead, uint16_t *data) {
	(void)slaveAddr;
	(void)startAddress;
	(void)nMemAddressRead;
	(void)data;
	return -MLX90640_I2C_NACK_ERROR;
}

int MLX90640_I2CWrite(uint8_t slaveAddr, uint16_t writeAddress, uint16_t data) {
	(void)slaveAddr;
	(void)writeAddress;
	(void)data;
	return -MLX90640_I2C_NACK_ERROR;
}

void MLX90640_I2CFreqSet(int freq) {
	(void)freq;
}
