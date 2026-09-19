"""Small I2C decoder for raw Logic 2 CSV exports.

Logic 2 "raw data" CSV has one row per change: time, then one column per
channel. This module turns the SDA/SCL columns into I2C transfers.

It is used instead of the Logic 2 built-in I2C analyzer (which could not be
set up through the Logic 2 MCP server), and it also gives the edge times
we need for timing checks.
"""

import csv
from dataclasses import dataclass, field


@dataclass
class Transfer:
    """One I2C transfer: START (or repeated START), address, data bytes."""
    t_start: float
    addr: int = -1
    read: bool = False
    data: list = field(default_factory=list)
    acks: list = field(default_factory=list)   # True = ACK, one per byte incl. address
    t_end: float = 0.0


def read_rows(path, columns):
    """Read a raw CSV. `columns` maps a name to a CSV column index (1 = first channel).

    Returns a list of (time, {name: level}).
    """
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for rec in reader:
            rows.append((float(rec[0]), {k: int(rec[c]) for k, c in columns.items()}))
    return rows


def edges(rows, name):
    """Return (time, new_level) for every change of one signal."""
    out = []
    prev = rows[0][1][name]
    for t, lv in rows[1:]:
        if lv[name] != prev:
            out.append((t, lv[name]))
            prev = lv[name]
    return out


def decode(rows):
    """Decode I2C transfers from rows that have 'sda' and 'scl' levels."""
    transfers = []
    cur = None
    bits = []
    prev = rows[0][1]

    for t, lv in rows[1:]:
        sda, scl = lv["sda"], lv["scl"]
        psda, pscl = prev["sda"], prev["scl"]

        # START / repeated START: SDA falls while SCL stays high.
        if scl and pscl and psda and not sda:
            if cur is not None:
                cur.t_end = t
                transfers.append(cur)
            cur = Transfer(t_start=t)
            bits = []
        # STOP: SDA rises while SCL stays high.
        elif scl and pscl and not psda and sda:
            if cur is not None:
                cur.t_end = t
                transfers.append(cur)
            cur = None
            bits = []
        # Data bit: SDA is read on the rising edge of SCL.
        elif scl and not pscl and cur is not None:
            bits.append(sda)
            if len(bits) == 9:
                value = 0
                for b in bits[:8]:
                    value = (value << 1) | b
                ack = bits[8] == 0
                if cur.addr < 0:
                    cur.addr = value >> 1
                    cur.read = bool(value & 1)
                else:
                    cur.data.append(value)
                cur.acks.append(ack)
                bits = []
        prev = lv

    if cur is not None:
        transfers.append(cur)
    return transfers
