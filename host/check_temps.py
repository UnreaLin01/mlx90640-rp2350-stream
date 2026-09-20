"""Check that calculated temperatures are sensible (M5 automatic check).

Converts every subpage to temperatures with the Melexis code (method A)
and checks, for every full image (after both subpages were seen):
  - no NaN / inf pixels
  - the image median is within the room range 15..40 degC
  - the sensor's own temperature Ta is within 15..60 degC
Also reports how long one conversion takes.

Usage:
    host/.venv/Scripts/python host/check_temps.py --file captures/m4_stream_65s.bin
    host/.venv/Scripts/python host/check_temps.py [--port COM9] --duration 20
"""

import argparse
import sys
import time

import numpy as np

from mlxstream.protocol import TYPE_EEPROM, TYPE_SUBPAGE
from mlxstream.worker import CALC_CLASSES
from mlxstream.receiver import Receiver
from mlxstream.sources import FileSource, open_source

ROOM_RANGE = (15.0, 40.0)
TA_RANGE = (15.0, 60.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="saved stream (stream_stats.py --save)")
    ap.add_argument("--source", default="usb", help="usb, usb:COM9, udp, udp:<ip>")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds, live mode only")
    ap.add_argument("--calc", choices=list(CALC_CLASSES), default="melexis",
                    help="Melexis C code (A) or numpy port (B)")
    args = ap.parse_args()

    src = FileSource(args.file) if args.file else open_source(args.source)
    rx = Receiver(src)
    calc = None
    seen = set()
    medians, mins, maxs, tas, bad_images, calc_ms = [], [], [], [], 0, []
    t0 = time.perf_counter()
    try:
        while True:
            if not args.file and time.perf_counter() - t0 > args.duration:
                break
            blocks = rx.poll()
            if args.file and src.eof:
                break
            for b in blocks:
                if b.type == TYPE_EEPROM and calc is None:
                    calc = CALC_CLASSES[args.calc](b.words())
                    print(f"EEPROM received, ExtractParameters -> {calc.extract_error}")
                elif b.type == TYPE_SUBPAGE and calc is not None:
                    t = time.perf_counter()
                    img = calc.update(b.frame_data())
                    calc_ms.append((time.perf_counter() - t) * 1e3)
                    seen.add(b.subpage)
                    if len(seen) < 2:
                        continue            # half the image is still empty
                    if not np.all(np.isfinite(img)):
                        bad_images += 1
                        continue
                    medians.append(float(np.median(img)))
                    mins.append(float(img.min()))
                    maxs.append(float(img.max()))
                    tas.append(calc.ta)
    finally:
        rx.close()

    if not medians:
        print("FAIL: no complete image (no EEPROM or no subpages)")
        return 1
    med = np.array(medians)
    ta = np.array(tas)
    print(f"images checked: {len(med)}  (NaN/inf images: {bad_images})")
    print(f"image median: {med.min():.2f} .. {med.max():.2f} degC (mean {med.mean():.2f})")
    print(f"image min / max pixel: {min(mins):.2f} / {max(maxs):.2f} degC")
    print(f"sensor Ta: {ta.min():.2f} .. {ta.max():.2f} degC")
    print(f"conversion time: median {np.median(calc_ms):.2f} ms, max {max(calc_ms):.2f} ms per subpage")

    checks = [
        ("no NaN/inf in full images", bad_images == 0),
        (f"all image medians in {ROOM_RANGE[0]:.0f}..{ROOM_RANGE[1]:.0f} degC",
         ROOM_RANGE[0] <= med.min() and med.max() <= ROOM_RANGE[1]),
        (f"Ta in {TA_RANGE[0]:.0f}..{TA_RANGE[1]:.0f} degC",
         TA_RANGE[0] <= ta.min() and ta.max() <= TA_RANGE[1]),
    ]
    ok = True
    for name, passed in checks:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
