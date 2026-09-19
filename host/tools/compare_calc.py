"""Compare method A (Melexis C code, DLL) with method B (Python/numpy port).

1. Calibration parameters: every field of B's result against A's C struct
   (read straight from the DLL's memory with ctypes). Expected: identical.
2. Temperatures: per-pixel difference over a whole recording.
3. Speed: time per subpage for each method.

Usage:
    host/.venv/Scripts/python host/tools/compare_calc.py captures/m4_stream_65s.bin
"""

import ctypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mlxstream.calc_melexis import MelexisCalc  # noqa: E402
from mlxstream.calc_python import PythonCalc  # noqa: E402
from mlxstream.protocol import TYPE_EEPROM, TYPE_SUBPAGE  # noqa: E402
from mlxstream.receiver import Receiver  # noqa: E402
from mlxstream.sources import FileSource  # noqa: E402

c = ctypes


class ParamsC(c.Structure):
    """Same layout as paramsMLX90640 in MLX90640_API.h."""
    _fields_ = [
        ("kVdd", c.c_int16), ("vdd25", c.c_int16),
        ("KvPTAT", c.c_float), ("KtPTAT", c.c_float),
        ("vPTAT25", c.c_uint16), ("alphaPTAT", c.c_float),
        ("gainEE", c.c_int16), ("tgc", c.c_float),
        ("cpKv", c.c_float), ("cpKta", c.c_float),
        ("resolutionEE", c.c_uint8), ("calibrationModeEE", c.c_uint8),
        ("KsTa", c.c_float), ("ksTo", c.c_float * 5), ("ct", c.c_int16 * 5),
        ("alpha", c.c_uint16 * 768), ("alphaScale", c.c_uint8),
        ("offset", c.c_int16 * 768),
        ("kta", c.c_int8 * 768), ("ktaScale", c.c_uint8),
        ("kv", c.c_int8 * 768), ("kvScale", c.c_uint8),
        ("cpAlpha", c.c_float * 2), ("cpOffset", c.c_int16 * 2),
        ("ilChessC", c.c_float * 3),
        ("brokenPixels", c.c_uint16 * 5), ("outlierPixels", c.c_uint16 * 5),
    ]


def as_list(v):
    return list(v) if hasattr(v, "__len__") and not isinstance(v, (str, bytes)) else [v]


def compare_params(a_calc, b_calc):
    lib = a_calc._lib
    assert c.sizeof(ParamsC) == lib.mlxw_params_size(), "struct layout does not match the DLL"
    pa = ParamsC.from_buffer(a_calc._params)
    pb = b_calc.params
    bad = []
    for name, _ in ParamsC._fields_:
        va = as_list(getattr(pa, name))
        vb = as_list(getattr(pb, name))
        if name in ("brokenPixels", "outlierPixels"):
            vb = list(vb) + [0xFFFF] * (5 - len(vb))
        # Compare as float32 for float fields (that is what C stores).
        va = np.array(va, dtype=np.float64)
        vb = np.array(vb, dtype=np.float64)
        if va.shape != vb.shape or not np.array_equal(va.astype(np.float32), vb.astype(np.float32)):
            n = int(np.sum(va.astype(np.float32) != vb.astype(np.float32))) if va.shape == vb.shape else -1
            bad.append((name, n))
    return bad


def run(path, ee_mod=None, frame_mod=None, limit=None):
    """Run A and B side by side over a recording and print the comparison.
    ee_mod / frame_mod: optional functions that change the input first
    (to reach code paths the real sensor does not use)."""
    rx = Receiver(FileSource(path))
    a = b = None
    seen = set()
    ta_a, ta_b, t_a, t_b = [], [], [], []
    diffs = []                 # per full image: max |A-B|
    all_diff = []
    count = 0
    while limit is None or count < limit:
        blocks = rx.poll()
        if rx.source.eof and not blocks:
            break
        for blk in blocks:
            if blk.type == TYPE_EEPROM and a is None:
                ee = blk.words()
                if ee_mod:
                    ee = ee_mod(ee)
                a = MelexisCalc(ee)
                t0 = time.perf_counter()
                b = PythonCalc(ee)
                t_extract = time.perf_counter() - t0
                bad = compare_params(a, b)
                print(f"ExtractParameters: A error {a.extract_error}, B error {b.extract_error}, "
                      f"B took {t_extract * 1e3:.0f} ms")
                print(f"  broken {b.params.brokenPixels}, outlier {b.params.outlierPixels}")
                if bad:
                    print(f"  parameter fields that differ: {bad}")
                else:
                    print("  all 27 parameter fields identical (bit for bit)")
            elif blk.type == TYPE_SUBPAGE and a is not None:
                count += 1
                fd = blk.frame_data()
                if frame_mod:
                    fd = frame_mod(fd)
                t0 = time.perf_counter()
                img_a = a.update(fd)
                t1 = time.perf_counter()
                img_b = b.update(fd)
                t2 = time.perf_counter()
                t_a.append(t1 - t0)
                t_b.append(t2 - t1)
                ta_a.append(a.ta)
                ta_b.append(b.ta)
                seen.add(blk.subpage)
                if len(seen) == 2:
                    d = np.abs(img_a.astype(np.float64) - img_b)
                    diffs.append(d.max())
                    all_diff.append(d.ravel())
    rx.close()

    all_diff = np.concatenate(all_diff)
    dta = np.abs(np.array(ta_a) - np.array(ta_b))
    print(f"images compared: {len(diffs)} ({all_diff.size} pixel values)")
    print(f"|A - B| per pixel: max {all_diff.max() * 1e3:.3f} mK, mean {all_diff.mean() * 1e3:.4f} mK, "
          f"99.9% below {np.percentile(all_diff, 99.9) * 1e3:.3f} mK")
    print(f"|Ta_A - Ta_B|: max {dta.max() * 1e3:.4f} mK")
    print(f"time per subpage: A {np.median(t_a) * 1e3:.3f} ms (max {max(t_a) * 1e3:.2f}), "
          f"B {np.median(t_b) * 1e3:.3f} ms (max {max(t_b) * 1e3:.2f})")


# --- Variants: reach the code paths this sensor does not use -----------------
# Pixel k = 32 * line + column. Chosen to hit every branch of the bad pixel
# repair: corners, first/last line, first/second/last columns, interior.
# Not next to each other (Melexis refuses adjacent bad pixels).
BROKEN = [0, 334]          # line 0 col 0 (corner); line 10 col 14 (interior)
OUTLIER = [62, 737]        # line 1 col 30; line 23 col 1


def inject_bad_pixels(ee):
    ee = list(ee)
    for k in BROKEN:
        ee[64 + k] = 0                      # "broken": pixel word is 0
    for k in OUTLIER:
        ee[64 + k] |= 0x0001                # "outlier": lowest bit set
    return ee


def to_interleaved(fd):
    fd = list(fd)
    fd[832] &= ~0x1000                      # control register bit 12 = 0
    return fd


VARIANTS = [
    ("injected bad pixels, chess mode", inject_bad_pixels, None),
    ("interleaved mode (mode != calibration mode)", None, to_interleaved),
    ("injected bad pixels + interleaved mode", inject_bad_pixels, to_interleaved),
]


if __name__ == "__main__":
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    print("=== real data ===")
    run(args[0])
    if "--variants" in sys.argv:
        for name, ee_mod, frame_mod in VARIANTS:
            print(f"\n=== variant: {name} (first 400 subpages) ===")
            run(args[0], ee_mod, frame_mod, limit=400)
