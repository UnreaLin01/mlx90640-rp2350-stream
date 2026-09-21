"""Receive the stream and check it (M4 acceptance).

Prints one line per second, then a summary with PASS/FAIL:
  - no CRC errors
  - no missing SUBPAGE blocks (seq gaps) and no incomplete blocks
  - subpage numbers alternate 0/1
  - subpage rate matches the firmware's rate setting (--rate, default 32)
  - device counters (STATUS) show no new read/order/wait errors and no
    dropped packets during the run
  - EEPROM is received regularly and is always the same

Usage:
    host/.venv/Scripts/python host/stream_stats.py [--source usb|udp] [--duration 60]
        [--rate 32] [--save captures/stream.bin]

--rate must match SENSOR_RATE in firmware/src/main.c, otherwise the rate
check fails even though nothing is wrong. It is the only check that
depends on it.
"""

import argparse
import sys
import time

from mlxstream.blocks import BlockAssembler
from mlxstream.protocol import (TYPE_EEPROM, TYPE_STATUS, TYPE_SUBPAGE,
                                StreamParser)
from mlxstream.sources import open_source

# Subpage period measured in M3 at the 32 Hz setting (docs/m3_timing.md).
#
# The sensor's own oscillator runs about 2.3 % slow, so "32 Hz" is really
# 31.27 Hz. Every rate setting comes from that same oscillator, so the
# others are scaled from this one measurement. Checked against M3's 16 Hz
# measurement: 63.753 ms measured, 63.948 ms predicted, 0.3 % apart, well
# inside the tolerance below.
M3_PERIOD_US = 31974
M3_SETTING_HZ = 32
RATE_SETTINGS_HZ = (0.5, 1, 2, 4, 8, 16, 32, 64)   # what the sensor offers
RATE_TOLERANCE = 0.01


def expected_rate(setting_hz):
    """Subpage rate the board really produces at this rate setting."""
    return setting_hz * (1e6 / M3_PERIOD_US) / M3_SETTING_HZ


# A missed subpage right after connecting is expected with UDP: the board's
# first packet has to wait for an ARP reply (see docs/m7_udp.md), which can
# take tens of ms. Errors in this window are counted separately.
CONNECT_WINDOW_S = 2.0


class Checker:
    def __init__(self):
        self.subpages = 0
        self.alternation_errors = 0
        self.alternation_errors_at_connect = 0
        self._t_first = None
        self.last_subpage = None
        self.first_ts = self.last_ts = None
        self.eeprom_count = 0
        self.eeprom_first = None
        self.eeprom_mismatch = 0
        self.status_first = None
        self.status_last = None
        self.delays = []        # host arrival time minus device timestamp
        self.t_last = None      # arrival time of the last subpage

    def on_block(self, b, arrival):
        if b.type == TYPE_SUBPAGE:
            self.subpages += 1
            # The two clocks have different starting points, so only the
            # variation of this difference is meaningful: it is the
            # transport delay jitter.
            self.delays.append(arrival - b.timestamp_us / 1e6)
            if self._t_first is None:
                self._t_first = arrival
            self.t_last = arrival
            if self.last_subpage is not None and b.subpage == self.last_subpage:
                if arrival - self._t_first <= CONNECT_WINDOW_S:
                    self.alternation_errors_at_connect += 1
                else:
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

    def host_rate(self):
        """Receive rate measured between the first and the last subpage, so
        the time before the stream starts does not count."""
        if self.subpages < 2 or self.t_last is None:
            return 0.0
        return (self.subpages - 1) / (self.t_last - self._t_first)

    def device_rate(self):
        """Subpage rate from the device's own timestamps."""
        if self.subpages < 2:
            return 0.0
        return (self.subpages - 1) / ((self.last_ts - self.first_ts) / 1e6)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default="usb",
                    help="usb, usb:COM9, udp, udp:192.168.1.200 (default: usb)")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--rate", type=float, default=M3_SETTING_HZ, choices=RATE_SETTINGS_HZ,
                    metavar="HZ",
                    help="subpage rate the firmware is built for, SENSOR_RATE in "
                         "firmware/src/main.c (default 32; one of 0.5 1 2 4 8 16 32 64)")
    ap.add_argument("--save", help="also save the raw byte stream to this file")
    args = ap.parse_args()

    src = open_source(args.source)
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
                    chk.on_block(block, time.perf_counter())
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
    host_rate = chk.host_rate()
    dev_rate = chk.device_rate()
    want_rate = expected_rate(args.rate)
    s0, s1 = chk.status_first or {}, chk.status_last or {}
    dev_new = {k: s1.get(k, 0) - s0.get(k, 0)
               for k in ("read_errors", "order_errors", "wait_errors", "tx_dropped")}
    expected_eeprom = int(elapsed // 2)

    checks = [
        ("CRC errors = 0", parser.crc_errors == 0, parser.crc_errors),
        ("SUBPAGE seq gaps = 0", asm.seq_gaps.get(TYPE_SUBPAGE, 0) == 0,
         asm.seq_gaps.get(TYPE_SUBPAGE, 0)),
        ("incomplete blocks = 0", sum(asm.incomplete.values()) == 0, dict(asm.incomplete)),
        ("malformed blocks = 0 (wrong size for their type)",
         sum(asm.bad_blocks.values()) == 0, dict(asm.bad_blocks)),
        (f"subpage 0/1 alternation errors after the first {CONNECT_WINDOW_S:.0f} s = 0",
         chk.alternation_errors == 0,
         f"{chk.alternation_errors} (at connect: {chk.alternation_errors_at_connect})"),
        (f"device subpage rate within {RATE_TOLERANCE:.0%} of the {args.rate:g} Hz setting "
         f"({want_rate:.2f} Hz)",
         abs(dev_rate - want_rate) / want_rate <= RATE_TOLERANCE, f"{dev_rate:.3f} Hz"),
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
    if chk.delays:
        d = sorted(chk.delays)
        base = d[0]
        mid = d[len(d) // 2] - base
        p99 = d[int(len(d) * 0.99)] - base
        print(f"transport delay jitter (vs fastest packet): median {mid * 1e3:.2f} ms, "
              f"99% {p99 * 1e3:.2f} ms, max {(d[-1] - base) * 1e3:.2f} ms")
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
