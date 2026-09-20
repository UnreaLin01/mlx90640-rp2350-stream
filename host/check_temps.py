"""Check that calculated temperatures are sensible (M5 automatic check).

Converts every subpage to temperatures and checks, for every full image
(after both subpages were seen):
  - no NaN / inf pixels
  - the image median is within the room range 15..40 degC
  - the sensor's own temperature Ta is within 15..60 degC
Also reports how long one conversion takes.

Usage:
    host/.venv/Scripts/python host/check_temps.py --file captures/m4_stream_65s.bin
    host/.venv/Scripts/python host/check_temps.py [--source usb] --duration 20
"""

import argparse
import sys
import time

import numpy as np

from mlxstream.pipeline import CALC_CLASSES, DEFAULT_CALC, ImageStream
from mlxstream.receiver import Receiver
from mlxstream.sources import FileSource, open_source

ROOM_RANGE = (15.0, 40.0)
TA_RANGE = (15.0, 60.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="saved stream (stream_stats.py --save)")
    ap.add_argument("--source", default="usb", help="usb, usb:COM9, udp, udp:<ip>")
    ap.add_argument("--duration", type=float, default=20.0, help="seconds, live mode only")
    ap.add_argument("--calc", choices=list(CALC_CLASSES), default=DEFAULT_CALC,
                    help="numpy port (default) or the official Melexis C code (needs the DLL)")
    args = ap.parse_args()

    src = FileSource(args.file) if args.file else open_source(args.source)
    rx = Receiver(src)
    images = ImageStream(args.calc)
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
                image = images.push(b)
                if images.new_eeprom:
                    print(f"EEPROM received, ExtractParameters -> "
                          f"{images.calc.extract_error}")
                if image is None:
                    continue
                calc_ms.append(images.convert_ms)
                if not np.all(np.isfinite(image)):
                    bad_images += 1
                    continue
                medians.append(float(np.median(image)))
                mins.append(float(image.min()))
                maxs.append(float(image.max()))
                tas.append(images.ta)
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
        ("no malformed blocks", sum(rx.assembler.bad_blocks.values()) == 0),
    ]
    ok = True
    for name, passed in checks:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
