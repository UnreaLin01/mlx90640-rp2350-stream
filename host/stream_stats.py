"""Receive the stream and check it (M4 acceptance).

Prints one line per second, then a summary with PASS/FAIL:
  - no CRC errors
  - no missing SUBPAGE blocks (seq gaps) and no incomplete blocks
  - subpage numbers alternate 0/1
  - subpage rate matches the M3 setting (period from docs/m3_timing.md)
  - device counters (STATUS) show no new read/order/wait errors and no
    dropped packets during the run
  - EEPROM is received regularly and is always the same

Usage:
    host/.venv/Scripts/python host/stream_stats.py [--port COM9] [--duration 60]
        [--save captures/stream.bin]
"""

import argparse
import sys
import time

from mlxstream.blocks import BlockAssembler
from mlxstream.protocol import (TYPE_EEPROM, TYPE_STATUS, TYPE_SUBPAGE,
                                StreamParser)
from mlxstream.sources import SerialSource

# Subpage period measured in M3 at the 32 Hz setting (docs/m3_timing.md).
M3_PERIOD_US = 31974
RATE_TOLERANCE = 0.01


class Checker:
    def __init__(self):
        self.subpages = 0
        self.alternation_errors = 0
        self.last_subpage = None
        self.first_ts = self.last_ts = None
        self.eeprom_count = 0
        self.eeprom_first = None
        self.eeprom_mismatch = 0
        self.status_first = None
        self.status_last = None

    def on_block(self, b):
        if b.type == TYPE_SUBPAGE:
            self.subpages += 1
            if self.last_subpage is not None and b.subpage == self.last_subpage:
                self.alternation_errors += 1
            self.last_subpage = b.subpage
            if self.first_ts is None:
                self.first_ts = b.timestamp_us
            self.last_ts = b.timestamp_us
        elif b.type == TYPE_EEPROM:
            self.eeprom_count += 1
            if self.eeprom_first is None:
                self.eeprom_first = b.data
            elif b.data != self.eeprom_first:
                self.eeprom_mismatch += 1
        elif b.type == TYPE_STATUS:
            s = b.status()
            if self.status_first is None:
                self.status_first = s
            self.status_last = s

    def device_rate(self):
        """Subpage rate from the device's own timestamps."""
        if self.subpages < 2:
            return 0.0
        return (self.subpages - 1) / ((self.last_ts - self.first_ts) / 1e6)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="COM port (default: find by VID/PID)")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--save", help="also save the raw byte stream to this file")
    args = ap.parse_args()

    src = SerialSource(args.port)
    save = open(args.save, "wb") if args.save else None
    parser, asm, chk = StreamParser(), BlockAssembler(), Checker()
    print(f"reading {src.name} for {args.duration:.0f} s")

    t0 = time.perf_counter()
    next_report = t0 + 1.0
    last_sub = 0
    first_packet_skip = None
    try:
        while True:
            now = time.perf_counter()
            if now - t0 >= args.duration:
                break
            data = src.read()
            if save and data:
                save.write(data)
            for pkt in parser.feed(data):
                if first_packet_skip is None:
                    first_packet_skip = parser.skipped_bytes
                block = asm.add(pkt)
                if block:
                    chk.on_block(block)
            if now >= next_report:
                st = chk.status_last or {}
                print(f"{now - t0:5.1f} s | {chk.subpages - last_sub:3d} subpages/s | "
                      f"crc_err {parser.crc_errors} | gaps {asm.seq_gaps.get(TYPE_SUBPAGE, 0)} | "
                      f"incomplete {asm.incomplete.get(TYPE_SUBPAGE, 0)} | "
                      f"alt_err {chk.alternation_errors} | eeprom {chk.eeprom_count} | "
                      f"dev dropped {st.get('tx_dropped', '-')} read_max {st.get('read_us_max', '-')} us")
                last_sub = chk.subpages
                next_report += 1.0
    finally:
        src.close()
        if save:
            save.close()
    elapsed = time.perf_counter() - t0

    # --- Summary -----------------------------------------------------------
    host_rate = chk.subpages / elapsed
    dev_rate = chk.device_rate()
    m3_rate = 1e6 / M3_PERIOD_US
    s0, s1 = chk.status_first or {}, chk.status_last or {}
    dev_new = {k: s1.get(k, 0) - s0.get(k, 0)
               for k in ("read_errors", "order_errors", "wait_errors", "tx_dropped")}
    expected_eeprom = int(elapsed // 2)

    checks = [
        ("CRC errors = 0", parser.crc_errors == 0, parser.crc_errors),
        ("SUBPAGE seq gaps = 0", asm.seq_gaps.get(TYPE_SUBPAGE, 0) == 0,
         asm.seq_gaps.get(TYPE_SUBPAGE, 0)),
        ("incomplete blocks = 0", sum(asm.incomplete.values()) == 0, dict(asm.incomplete)),
        ("subpage 0/1 alternation errors = 0", chk.alternation_errors == 0,
         chk.alternation_errors),
        (f"device subpage rate within {RATE_TOLERANCE:.0%} of M3 ({m3_rate:.2f} Hz)",
         abs(dev_rate - m3_rate) / m3_rate <= RATE_TOLERANCE, f"{dev_rate:.3f} Hz"),
        ("PC receive rate matches device rate (nothing lost)",
         abs(host_rate - dev_rate) / dev_rate <= RATE_TOLERANCE if dev_rate else False,
         f"{host_rate:.3f} Hz"),
        ("no new device errors / drops (STATUS)", chk.status_last is not None
         and not any(dev_new.values()), dev_new),
        (f"EEPROM received >= {expected_eeprom - 1} times, all identical",
         chk.eeprom_count >= expected_eeprom - 1 and chk.eeprom_mismatch == 0,
         f"{chk.eeprom_count} received, {chk.eeprom_mismatch} different"),
    ]

    print()
    print(f"elapsed {elapsed:.1f} s, packets {parser.packets}, subpages {chk.subpages}, "
          f"blocks {dict(asm.blocks)}")
    print(f"bytes skipped: {parser.skipped_bytes} (before first packet: {first_packet_skip}), "
          f"header errors {parser.header_errors}")
    if chk.status_last:
        print(f"device STATUS at end: {chk.status_last}")
    ok = True
    for name, passed, value in checks:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {value}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
