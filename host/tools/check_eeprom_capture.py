"""Check a Logic 8 capture of firmware/tests/eeprom_test.c (M2).

Inputs:
  - raw CSV from Logic 2 with CH0 = SDA, CH1 = SCL, CH2 = mark A
  - the RTT log of the same firmware run (holds the EEPROM hex dump)

Checks:
  1. The sensor ACKs every byte of the EEPROM read.
  2. The 832 words decoded from the wire equal the RTT hex dump.
  3. Timing: SCL rate, SCL low/high time, gaps between bytes, and the
     read time from mark A.

Usage:
    python check_eeprom_capture.py <digital.csv> <rtt.log>
"""

import re
import statistics
import sys

from i2c_decode import decode, edges, read_rows

SENSOR_ADDR = 0x33
EE_START = 0x2400
EE_WORDS = 832


def read_rtt_dump(path):
    """Return (eeprom words from the hex dump, I2C timing line fields)."""
    words = {}
    timing = {}
    with open(path, encoding="ascii", errors="replace") as f:
        for line in f:
            m = re.match(r"EE ([0-9A-F]{4}):((?: [0-9A-F]{4})+)", line)
            if m:
                base = int(m.group(1), 16)
                # Only keep the first dump in the log.
                if base in words:
                    continue
                words[base] = [int(w, 16) for w in m.group(2).split()]
            m = re.match(r"I2C (.*)", line)
            if m and not timing:
                timing = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", m.group(1))}
    flat = []
    for base in sorted(words):
        flat.extend(words[base])
    return flat, timing


def find_eeprom_read(transfers):
    """Find 'write 0x2400' followed by a read of the full EEPROM."""
    for i in range(len(transfers) - 1):
        w, r = transfers[i], transfers[i + 1]
        if (w.addr == SENSOR_ADDR and not w.read and w.data[:2] == [EE_START >> 8, EE_START & 0xFF]
                and r.addr == SENSOR_ADDR and r.read):
            return w, r
    return None, None


def us(x):
    return x * 1e6


def main(csv_path, rtt_path):
    ok = True
    rows = read_rows(csv_path, {"sda": 1, "scl": 2, "mark": 3})
    transfers = decode(rows)
    rtt_words, timing = read_rtt_dump(rtt_path)
    print(f"decoded {len(transfers)} transfers; RTT dump has {len(rtt_words)} words")

    w, r = find_eeprom_read(transfers)
    if r is None:
        print("FAIL: no EEPROM read found in capture")
        return 1

    # --- 1. ACKs ----------------------------------------------------------
    # In a read, the controller ACKs every byte except the last (NACK = end).
    addr_ack = w.acks[0] and r.acks[0]
    reg_ack = all(w.acks)
    print(f"address ACK: {addr_ack}, register bytes ACK: {reg_ack}")
    ok = ok and addr_ack and reg_ack

    # --- 2. Data ------------------------------------------------------------
    wire = [(r.data[2 * i] << 8) | r.data[2 * i + 1] for i in range(len(r.data) // 2)]
    diffs = [i for i in range(min(len(wire), len(rtt_words))) if wire[i] != rtt_words[i]]
    print(f"wire words: {len(wire)}, differences vs RTT dump: {len(diffs)}")
    for i in diffs[:10]:
        print(f"  0x{EE_START + i:04X}: wire {wire[i]:04X}  rtt {rtt_words[i]:04X}")
    data_ok = len(wire) == EE_WORDS and len(rtt_words) == EE_WORDS and not diffs
    ok = ok and data_ok

    # --- 3. Timing ----------------------------------------------------------
    scl = [(t, v) for t, v in edges(rows, "scl") if w.t_start <= t <= r.t_end]
    rises = [t for t, v in scl if v]
    periods = [b - a for a, b in zip(rises, rises[1:])]
    lows, highs = [], []
    for (t0, v0), (t1, _) in zip(scl, scl[1:]):
        (highs if v0 else lows).append(t1 - t0)

    # Clock periods inside a byte are short; the ones between bytes are longer
    # because the MCU loads the next byte. Split them at 1.5x the median.
    med = statistics.median(periods)
    in_byte = [p for p in periods if p < 1.5 * med]
    gaps = [p for p in periods if p >= 1.5 * med]
    low_in = [x for x in lows if x < 1.5 * statistics.median(lows)]

    print(f"SCL in-byte rate: {1 / statistics.mean(in_byte) / 1e3:.1f} kHz "
          f"(period {us(statistics.mean(in_byte)):.3f} us)")
    print(f"SCL low:  median {us(statistics.median(low_in)):.3f} us, "
          f"min {us(min(low_in)):.3f} us")
    print(f"SCL high: median {us(statistics.median(highs)):.3f} us, "
          f"min {us(min(highs)):.3f} us")
    if gaps:
        print(f"between-byte clock periods: {len(gaps)}, median {us(statistics.median(gaps)):.3f} us")
    eff_bits = len(r.data) * 9 + len(w.data) * 9 + 18
    dur = r.t_end - w.t_start
    print(f"EEPROM transfer on wire: {dur * 1e3:.3f} ms "
          f"(effective {eff_bits / dur / 1e3:.1f} kbit/s)")

    mark = edges(rows, "mark")
    for (t0, v0), (t1, _) in zip(mark, mark[1:]):
        if v0:
            print(f"mark A high (whole DumpEE call): {(t1 - t0) * 1e3:.3f} ms")
            break

    if timing:
        clk = timing["clk"]
        print(f"programmed: lcnt={timing['lcnt']} ({timing['lcnt'] / clk * 1e6:.3f} us), "
              f"hcnt={timing['hcnt']} ({timing['hcnt'] / clk * 1e6:.3f} us), "
              f"spklen={timing['spklen']}")

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
