"""Compare the Logic 2 I2C analyzer table with the RTT EEPROM dump (M2).

Input is the I2C data table exported from Logic 2 with hex values
(columns: name, type, start_time, duration, ack, address, read, data).
Optionally also the raw CSV, to compare with our own decoder too.

Usage:
    python check_logic2_i2c_table.py <i2c_table.csv> <rtt.log> [digital.csv]
"""

import csv
import sys

from check_eeprom_capture import EE_START, EE_WORDS, SENSOR_ADDR, find_eeprom_read, read_rtt_dump
from i2c_decode import Transfer, decode, read_rows


def parse_value(text):
    """Parse a hex value like '0x3F'. Returns None if the table is not in hex."""
    text = text.strip()
    if not text.lower().startswith("0x"):
        return None
    return int(text, 16)


def read_table(path):
    """Turn the Logic 2 table into Transfer objects (same shape as our decoder)."""
    transfers = []
    cur = None
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind = row["type"]
            t = float(row["start_time"])
            if kind == "start":
                if cur is not None:
                    transfers.append(cur)
                cur = Transfer(t_start=t)
            elif kind == "stop":
                if cur is not None:
                    cur.t_end = t
                    transfers.append(cur)
                cur = None
            elif kind == "address" and cur is not None:
                addr = parse_value(row["address"])
                if addr is None:
                    raise SystemExit("table is not in hex: set the analyzer radix to Hexadecimal")
                cur.addr = addr
                cur.read = row["read"] == "true"
                cur.acks.append(row["ack"] == "true")
            elif kind == "data" and cur is not None:
                value = parse_value(row["data"])
                if value is None:
                    raise SystemExit("table is not in hex: set the analyzer radix to Hexadecimal")
                cur.data.append(value)
                cur.acks.append(row["ack"] == "true")
    if cur is not None:
        transfers.append(cur)
    return transfers


def words_of(transfer):
    d = transfer.data
    return [(d[2 * i] << 8) | d[2 * i + 1] for i in range(len(d) // 2)]


def compare(name_a, a, name_b, b):
    diffs = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    same = len(a) == len(b) and not diffs
    print(f"{name_a} vs {name_b}: {len(a)} / {len(b)} words, {len(diffs)} differences"
          f" -> {'MATCH' if same else 'MISMATCH'}")
    for i in diffs[:10]:
        print(f"  0x{EE_START + i:04X}: {a[i]:04X} vs {b[i]:04X}")
    return same


def main(table_path, rtt_path, raw_path=None):
    rtt_words, _ = read_rtt_dump(rtt_path)
    w, r = find_eeprom_read(read_table(table_path))
    if r is None:
        print("FAIL: no EEPROM read in the Logic 2 table")
        return 1

    ok = w.acks[0] and all(w.acks) and r.acks[0]
    print(f"Logic 2 analyzer: address 0x{r.addr:02X}, write ACKs {all(w.acks)}, "
          f"read address ACK {r.acks[0]}, data bytes {len(r.data)}")
    table_words = words_of(r)
    ok = compare("Logic 2 analyzer", table_words, "RTT dump", rtt_words) and ok
    ok = ok and len(table_words) == EE_WORDS and r.addr == SENSOR_ADDR

    if raw_path:
        _, r2 = find_eeprom_read(decode(read_rows(raw_path, {"sda": 1, "scl": 2})))
        if r2 is None:
            print("our decoder: no EEPROM read found")
            ok = False
        else:
            ok = compare("Logic 2 analyzer", table_words, "our decoder", words_of(r2)) and ok

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(__doc__)
        sys.exit(2)
    sys.exit(main(*sys.argv[1:]))
