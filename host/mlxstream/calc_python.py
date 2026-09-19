"""Temperature calculation in pure Python/numpy (method B).

A port of the Melexis library (third_party/mlx90640-library/functions/
MLX90640_API.c): ExtractParameters, GetVdd, GetTa, CalculateTo and
BadPixelsCorrection. Same interface as calc_melexis.MelexisCalc, so the
two can be swapped and compared (host/tools/compare_calc.py).

Notes on matching the C code:
  - Parameter extraction copies the C steps exactly, including where the
    C code stores values in 32-bit float and then rounds them into small
    integers (alpha, kta, kv). So the parameters come out bit-for-bit the
    same as the C version.
  - The per-subpage calculation uses 64-bit floats and works on all pixels
    of a subpage at once with numpy. The C code uses 32-bit floats, so the
    temperatures differ very slightly.
"""

import math

import numpy as np

ROWS, COLS, NPIX = 24, 32, 768
SCALEALPHA = 0.000001
TA_SHIFT = 8.0
DEFAULT_EMISSIVITY = 0.95

f32 = np.float32


# ---------------------------------------------------------------------------
# Bit helpers (same names as the Melexis macros)
# ---------------------------------------------------------------------------
def nib1(w):
    return w & 0x000F


def nib2(w):
    return (w & 0x00F0) >> 4


def nib3(w):
    return (w & 0x0F00) >> 8


def nib4(w):
    return (w & 0xF000) >> 12


def ms_byte(w):
    return (w & 0xFF00) >> 8


def ls_byte(w):
    return w & 0x00FF


def s8(v):
    """Reinterpret 0..255 as int8."""
    return v - 256 if v > 127 else v


def s16(v):
    """Reinterpret 0..65535 as int16."""
    return v - 65536 if v > 32767 else v


def signed(v, bits):
    """Two's complement of a `bits`-wide field (e.g. 'if > 31: -= 64')."""
    return v - (1 << bits) if v >= (1 << (bits - 1)) else v


def c_trunc(x):
    """C float -> int conversion (rounds toward zero)."""
    return int(math.trunc(x))


# ---------------------------------------------------------------------------
# Parameter extraction (MLX90640_ExtractParameters)
# ---------------------------------------------------------------------------
class Params:
    pass


def _extract_vdd(ee, p):
    kvdd = s8(ms_byte(ee[51]))
    vdd25 = ls_byte(ee[51])
    vdd25 = ((vdd25 - 256) << 5) - 8192
    p.kVdd = 32 * kvdd
    p.vdd25 = vdd25


def _extract_ptat(ee, p):
    kv = (ee[50] & 0xFC00) >> 10
    if kv > 31:
        kv -= 64
    p.KvPTAT = float(f32(f32(kv) / 4096))
    kt = ee[50] & 0x03FF
    if kt > 511:
        kt -= 1024
    p.KtPTAT = float(f32(f32(kt) / 8))
    p.vPTAT25 = ee[49]
    p.alphaPTAT = float(f32((ee[16] & 0xF000) / 2.0 ** 14 + 8.0))


def _extract_gain(ee, p):
    p.gainEE = s16(ee[48])


def _extract_tgc(ee, p):
    p.tgc = float(f32(s8(ls_byte(ee[60])) / f32(32.0)))


def _extract_resolution(ee, p):
    p.resolutionEE = (ee[56] & 0x3000) >> 12


def _extract_ksta(ee, p):
    p.KsTa = float(f32(s8(ms_byte(ee[60])) / f32(8192.0)))


def _extract_ksto(ee, p):
    step = ((ee[63] & 0x3000) >> 12) * 10
    ct = [-40, 0, nib2(ee[63]), nib3(ee[63]), 400]
    ct[2] = ct[2] * step
    ct[3] = ct[2] + ct[3] * step
    p.ct = ct
    scale = f32(1 << (nib1(ee[63]) + 8))
    p.ksTo = [float(f32(s8(ls_byte(ee[61])) / scale)),
              float(f32(s8(ms_byte(ee[61])) / scale)),
              float(f32(s8(ls_byte(ee[62])) / scale)),
              float(f32(s8(ms_byte(ee[62])) / scale)),
              float(f32(-0.0002))]


def _extract_cp(ee, p):
    alpha_scale = nib4(ee[32]) + 27
    off0 = ee[58] & 0x03FF
    if off0 > 511:
        off0 -= 1024
    off1 = (ee[58] & 0xFC00) >> 10
    if off1 > 31:
        off1 -= 64
    off1 += off0
    a0 = f32(ee[57] & 0x03FF)
    if a0 > 511:
        a0 = f32(a0 - 1024)
    a0 = f32(a0 / 2.0 ** alpha_scale)
    a1 = f32((ee[57] & 0xFC00) >> 10)
    if a1 > 31:
        a1 = f32(a1 - 64)
    a1 = f32((1 + a1 / f32(128)) * a0)
    kta_scale1 = nib2(ee[56]) + 8
    p.cpKta = float(f32(f32(s8(ls_byte(ee[59]))) / 2.0 ** kta_scale1))
    kv_scale = nib3(ee[56])
    p.cpKv = float(f32(f32(s8(ms_byte(ee[59]))) / 2.0 ** kv_scale))
    p.cpAlpha = [float(a0), float(a1)]
    p.cpOffset = [off0, off1]


def _nibble_table(ee, first_word, count_words, n):
    """accRow/accColumn style tables: 4 signed nibbles per word."""
    out = []
    for i in range(count_words):
        w = ee[first_word + i]
        out += [nib1(w), nib2(w), nib3(w), nib4(w)]
    return [v - 16 if v > 7 else v for v in out[:n]]


def _extract_alpha(ee, p):
    acc_rem_scale = nib1(ee[32])
    acc_col_scale = nib2(ee[32])
    acc_row_scale = nib3(ee[32])
    alpha_scale = nib4(ee[32]) + 30
    alpha_ref = ee[33]
    acc_row = _nibble_table(ee, 34, 6, ROWS)
    acc_col = _nibble_table(ee, 40, 8, COLS)
    cp_mean = f32(f32(p.tgc) * f32((f32(p.cpAlpha[0]) + f32(p.cpAlpha[1]))) / f32(2))

    temp = np.empty(NPIX, dtype=np.float32)
    for i in range(ROWS):
        for j in range(COLS):
            k = 32 * i + j
            a = f32((ee[64 + k] & 0x03F0) >> 4)
            if a > 31:
                a = f32(a - 64)
            a = f32(a * (1 << acc_rem_scale))
            a = f32(alpha_ref + (acc_row[i] << acc_row_scale) + (acc_col[j] << acc_col_scale) + a)
            a = f32(a / 2.0 ** alpha_scale)
            a = f32(a - cp_mean)
            # C: double / float -> double, then stored as float. (numpy would
            # do float32 / float32 here, which is not the same.)
            a = f32(SCALEALPHA / float(a))
            temp[k] = a
    t = f32(temp.max())
    scale = 0
    while t < 32767.4:
        t = f32(t * 2)
        scale += 1
    # C: temp (float) = alpha * 2^scale; alpha = (int)(temp + 0.5) in double.
    p.alpha = np.array([c_trunc(float(f32(float(temp[k]) * 2.0 ** scale)) + 0.5)
                        for k in range(NPIX)], dtype=np.uint16)
    p.alphaScale = scale


def _extract_offset(ee, p):
    rem_scale = nib1(ee[16])
    col_scale = nib2(ee[16])
    row_scale = nib3(ee[16])
    offset_ref = s16(ee[17])
    occ_row = _nibble_table(ee, 18, 6, ROWS)
    occ_col = _nibble_table(ee, 24, 8, COLS)
    off = np.empty(NPIX, dtype=np.int16)
    for i in range(ROWS):
        for j in range(COLS):
            k = 32 * i + j
            o = (ee[64 + k] & 0xFC00) >> 10
            if o > 31:
                o -= 64
            o = o * (1 << rem_scale)
            off[k] = offset_ref + (occ_row[i] << row_scale) + (occ_col[j] << col_scale) + o
    p.offset = off


def _split(k):
    """0..3: which of the 4 row/column parity groups pixel k is in."""
    return 2 * (k // 32 - (k // 64) * 2) + k % 2


def _quantize_signed(values, limit):
    """Scale up to use the int8 range, like the C code (temp < 63.4 loop)."""
    t = f32(np.abs(values).max())
    scale = 0
    while t < limit:
        t = f32(t * 2)
        scale += 1
    q = []
    for v in values:
        # C: temp (float) = v * 2^scale; then (int)(temp -/+ 0.5) in double.
        x = float(f32(float(v) * 2.0 ** scale))
        q.append(c_trunc(x - 0.5) if x < 0 else c_trunc(x + 0.5))
    return np.array(q, dtype=np.int8), scale


def _extract_kta(ee, p):
    kta_rc = [s8(ms_byte(ee[54])), s8(ms_byte(ee[55])), s8(ls_byte(ee[54])), s8(ls_byte(ee[55]))]
    scale1 = nib2(ee[56]) + 8
    scale2 = nib1(ee[56])
    temp = np.empty(NPIX, dtype=np.float32)
    for k in range(NPIX):
        t = f32((ee[64 + k] & 0x000E) >> 1)
        if t > 3:
            t = f32(t - 8)
        t = f32(t * (1 << scale2))
        t = f32(kta_rc[_split(k)] + t)
        t = f32(t / 2.0 ** scale1)
        temp[k] = t
    p.kta, p.ktaScale = _quantize_signed(temp, 63.4)


def _extract_kv(ee, p):
    def sn(v):
        return v - 16 if v > 7 else v
    kvt = [sn(nib4(ee[52])), sn(nib2(ee[52])), sn(nib3(ee[52])), sn(nib1(ee[52]))]
    scale = nib3(ee[56])
    temp = np.array([f32(f32(kvt[_split(k)]) / 2.0 ** scale) for k in range(NPIX)], dtype=np.float32)
    p.kv, p.kvScale = _quantize_signed(temp, 63.4)


def _extract_cilc(ee, p):
    mode = (ee[10] & 0x0800) >> 4
    p.calibrationModeEE = mode ^ 0x80
    c0 = ee[53] & 0x003F
    c0 = (c0 - 64 if c0 > 31 else c0) / 16.0
    c1 = (ee[53] & 0x07C0) >> 6
    c1 = (c1 - 32 if c1 > 15 else c1) / 2.0
    c2 = (ee[53] & 0xF800) >> 11
    c2 = (c2 - 32 if c2 > 15 else c2) / 8.0
    p.ilChessC = [float(f32(c0)), float(f32(c1)), float(f32(c2))]


def _adjacent(p1, p2):
    return abs((p1 >> 5) - (p2 >> 5)) < 2 and abs((p1 & 31) - (p2 & 31)) < 2


def _extract_deviating(ee, p):
    broken, outlier = [], []
    k = 0
    while k < NPIX and len(broken) < 5 and len(outlier) < 5:
        if ee[k + 64] == 0:
            broken.append(k)
        elif ee[k + 64] & 0x0001:
            outlier.append(k)
        k += 1
    p.brokenPixels = broken
    p.outlierPixels = outlier
    if len(broken) > 4:
        return -3
    if len(outlier) > 4:
        return -4
    if len(broken) + len(outlier) > 4:
        return -5
    pairs = ([(a, b) for i, a in enumerate(broken) for b in broken[i + 1:]]
             + [(a, b) for i, a in enumerate(outlier) for b in outlier[i + 1:]]
             + [(a, b) for a in broken for b in outlier])
    for a, b in pairs:
        if _adjacent(a, b):
            return -6
    return 0


def extract_parameters(ee):
    """MLX90640_ExtractParameters. Returns (Params, error code)."""
    ee = [int(w) for w in ee]
    p = Params()
    # Same order as the C code: CP before alpha (alpha uses cpAlpha and tgc).
    _extract_vdd(ee, p)
    _extract_ptat(ee, p)
    _extract_gain(ee, p)
    _extract_tgc(ee, p)
    _extract_resolution(ee, p)
    _extract_ksta(ee, p)
    _extract_ksto(ee, p)
    _extract_cp(ee, p)
    _extract_alpha(ee, p)
    _extract_offset(ee, p)
    _extract_kta(ee, p)
    _extract_kv(ee, p)
    _extract_cilc(ee, p)
    err = _extract_deviating(ee, p)
    return p, err


# ---------------------------------------------------------------------------
# Per-subpage calculation
# ---------------------------------------------------------------------------
_N = np.arange(NPIX)
IL_PATTERN = (_N // 32) % 2                              # row parity
CHESS_PATTERN = IL_PATTERN ^ (_N % 2)
CONVERSION_PATTERN = (((_N + 2) // 4 - (_N + 3) // 4 + (_N + 1) // 4 - _N // 4)
                      * (1 - 2 * IL_PATTERN))


def get_vdd(frame, p):
    res_ram = (frame[832] & 0x0C00) >> 10
    corr = 2.0 ** p.resolutionEE / 2.0 ** res_ram
    return (corr * s16(frame[810]) - p.vdd25) / p.kVdd + 3.3


def get_ta(frame, p):
    vdd = get_vdd(frame, p)
    ptat = s16(frame[800])
    ptat_art = (ptat / (ptat * p.alphaPTAT + s16(frame[768]))) * 2.0 ** 18
    ta = ptat_art / (1 + p.KvPTAT * (vdd - 3.3)) - p.vPTAT25
    return ta / p.KtPTAT + 25


def calculate_to(frame, p, emissivity, tr, result):
    """MLX90640_CalculateTo, all pixels of one subpage at once.
    frame: int array of 834 words. result: float64[768], updated in place."""
    sub = int(frame[833])
    vdd = get_vdd(frame, p)
    ta = get_ta(frame, p)
    ta4 = (ta + 273.15) ** 4
    tr4 = (tr + 273.15) ** 4
    ta_tr = tr4 - (tr4 - ta4) / emissivity

    kta_scale = 2.0 ** p.ktaScale
    kv_scale = 2.0 ** p.kvScale
    alpha_scale = 2.0 ** p.alphaScale
    ks, ct = p.ksTo, p.ct
    alpha_corr = [1 / (1 + ks[0] * 40), 1.0, 1 + ks[1] * ct[2]]
    alpha_corr.append(alpha_corr[2] * (1 + ks[2] * (ct[3] - ct[2])))

    gain = p.gainEE / s16(frame[778])
    # Note: "mode" is 0 or 128 here (bit 12 shifted right by 5), and so is
    # calibrationModeEE. Keep it that way to compare like the C code.
    mode = (frame[832] & 0x1000) >> 5

    cp_scale = (1 + p.cpKta * (ta - 25)) * (1 + p.cpKv * (vdd - 3.3))
    ir_cp = [s16(frame[776]) * gain - p.cpOffset[0] * cp_scale,
             s16(frame[808]) * gain]
    if mode == p.calibrationModeEE:
        ir_cp[1] -= p.cpOffset[1] * cp_scale
    else:
        ir_cp[1] -= (p.cpOffset[1] + p.ilChessC[0]) * cp_scale

    pattern = IL_PATTERN if mode == 0 else CHESS_PATTERN
    idx = np.nonzero(pattern == sub)[0]

    raw = np.asarray(frame[:NPIX], dtype=np.int64)[idx]
    raw = np.where(raw > 32767, raw - 65536, raw)          # int16
    ir = raw * gain
    kta = p.kta[idx] / kta_scale
    kv = p.kv[idx] / kv_scale
    ir = ir - p.offset[idx] * (1 + kta * (ta - 25)) * (1 + kv * (vdd - 3.3))
    if mode != p.calibrationModeEE:
        ir = (ir + p.ilChessC[2] * (2 * IL_PATTERN[idx] - 1)
              - p.ilChessC[1] * CONVERSION_PATTERN[idx])
    ir = ir - p.tgc * ir_cp[sub]
    ir = ir / emissivity

    a = SCALEALPHA * alpha_scale / p.alpha[idx].astype(np.float64)
    a = a * (1 + p.KsTa * (ta - 25))
    sx = a ** 3 * (ir + a * ta_tr)
    sx = np.sqrt(np.sqrt(sx)) * ks[1]
    to = np.sqrt(np.sqrt(ir / (a * (1 - ks[1] * 273.15) + sx) + ta_tr)) - 273.15

    rng = np.select([to < ct[1], to < ct[2], to < ct[3]], [0, 1, 2], 3)
    ks_r = np.array(ks)[rng]
    ct_r = np.array(ct, dtype=np.float64)[rng]
    corr_r = np.array(alpha_corr)[rng]
    to = np.sqrt(np.sqrt(ir / (a * corr_r * (1 + ks_r * (to - ct_r))) + ta_tr)) - 273.15
    result[idx] = to


def bad_pixels_correction(pixels, to, mode, p):
    """MLX90640_BadPixelsCorrection. mode: 1 = chess, 0 = interleaved."""
    bad = set(p.brokenPixels) | set(p.outlierPixels)
    for px in pixels:
        line, col = px >> 5, px & 31
        if mode == 1:
            if line == 0:
                if col == 0:
                    to[px] = to[33]
                elif col == 31:
                    to[px] = to[62]
                else:
                    to[px] = (to[px + 31] + to[px + 33]) / 2
            elif line == 23:
                if col == 0:
                    to[px] = to[705]
                elif col == 31:
                    to[px] = to[734]
                else:
                    to[px] = (to[px - 33] + to[px - 31]) / 2
            elif col == 0:
                to[px] = (to[px - 31] + to[px + 33]) / 2
            elif col == 31:
                to[px] = (to[px - 33] + to[px + 31]) / 2
            else:
                to[px] = float(np.median([to[px - 33], to[px - 31], to[px + 31], to[px + 33]]))
        else:
            if col == 0:
                to[px] = to[px + 1]
            elif col in (1, 30):
                to[px] = (to[px - 1] + to[px + 1]) / 2
            elif col == 31:
                to[px] = to[px - 1]
            elif px - 2 not in bad and px + 2 not in bad:
                a0 = to[px + 1] - to[px + 2]
                a1 = to[px - 1] - to[px - 2]
                to[px] = to[px - 1] + a1 if abs(a0) > abs(a1) else to[px + 1] + a0
            else:
                to[px] = (to[px - 1] + to[px + 1]) / 2


class PythonCalc:
    """Same interface as calc_melexis.MelexisCalc."""

    def __init__(self, ee_words, emissivity=DEFAULT_EMISSIVITY):
        self.params, self.extract_error = extract_parameters(ee_words)
        if self.extract_error != 0:
            print(f"warning: extract_parameters returned {self.extract_error}")
        self.emissivity = emissivity
        self._result = np.full(NPIX, np.nan)
        self.ta = float("nan")
        self.vdd = float("nan")

    def update(self, frame_data):
        frame = np.asarray(frame_data, dtype=np.int64)
        p = self.params
        self.vdd = get_vdd(frame, p)
        self.ta = get_ta(frame, p)
        calculate_to(frame, p, self.emissivity, self.ta - TA_SHIFT, self._result)
        chess = (int(frame[832]) >> 12) & 1
        bad_pixels_correction(p.brokenPixels, self._result, chess, p)
        bad_pixels_correction(p.outlierPixels, self._result, chess, p)
        return self._result.reshape(ROWS, COLS).copy()
