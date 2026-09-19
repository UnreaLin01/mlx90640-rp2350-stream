"""Temperature calculation with the official Melexis C code (method A).

Loads host/native/build/mlx90640.dll (built by scripts/build_host_lib.ps1
from the unmodified Melexis library) through ctypes.

Usage follows the Melexis example code:
  - unpack the EEPROM once (ExtractParameters)
  - for each subpage: Ta, then CalculateTo, which updates only the pixels
    of that subpage; the other half keeps the values of the previous
    subpage, so one image array is kept between calls
  - fix the pixels the EEPROM marks as broken / outliers
"""

import ctypes
import os

import numpy as np

DLL_PATH = os.path.join(os.path.dirname(__file__), "..", "native", "build", "mlx90640.dll")

# Reflected temperature = Ta - TA_SHIFT. Melexis uses 8 degC for a sensor
# in open air (the sensor body is warmer than the surroundings).
TA_SHIFT = 8.0
DEFAULT_EMISSIVITY = 0.95

ROWS, COLS = 24, 32


class MelexisCalc:
    def __init__(self, ee_words, emissivity=DEFAULT_EMISSIVITY, dll_path=DLL_PATH):
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"{dll_path} not found: run scripts/build_host_lib.ps1")
        lib = ctypes.CDLL(os.path.abspath(dll_path))
        lib.mlxw_params_size.restype = ctypes.c_int
        lib.mlxw_extract.restype = ctypes.c_int
        lib.mlxw_get_ta.restype = ctypes.c_float
        lib.mlxw_get_vdd.restype = ctypes.c_float
        lib.mlxw_calculate_to.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_float, ctypes.c_float, ctypes.c_void_p]
        lib.mlxw_bad_pixels_correction.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        self._lib = lib

        self.emissivity = emissivity
        self._params = ctypes.create_string_buffer(lib.mlxw_params_size())
        ee = (ctypes.c_uint16 * 832)(*ee_words)
        self.extract_error = lib.mlxw_extract(ee, self._params)
        if self.extract_error != 0:
            # Melexis returns a negative code for a bad EEPROM or too many
            # bad pixels; the parameters may still be usable, so only warn.
            print(f"warning: MLX90640_ExtractParameters returned {self.extract_error}")

        self._frame = (ctypes.c_uint16 * 834)()
        self._result = (ctypes.c_float * 768)(*([float("nan")] * 768))
        self.ta = float("nan")
        self.vdd = float("nan")

    def update(self, frame_data):
        """Process one subpage (834 words). Returns the full 24x32 image in
        degC (pixels of the not-yet-seen subpage are NaN at the start)."""
        ctypes.memmove(self._frame, (ctypes.c_uint16 * 834)(*frame_data), 834 * 2)
        self.vdd = self._lib.mlxw_get_vdd(self._frame, self._params)
        self.ta = self._lib.mlxw_get_ta(self._frame, self._params)
        tr = self.ta - TA_SHIFT
        self._lib.mlxw_calculate_to(self._frame, self._params, self.emissivity, tr, self._result)
        chess = (frame_data[832] >> 12) & 1       # control register bit 12
        self._lib.mlxw_bad_pixels_correction(self._params, self._result, chess)
        return np.frombuffer(self._result, dtype=np.float32).reshape(ROWS, COLS).copy()
