"""Put packet parts back together into blocks, and check sequence numbers."""

import struct
from dataclasses import dataclass

from .protocol import PART_MAX, TYPE_EEPROM, TYPE_STATUS, TYPE_SUBPAGE

STATUS_FIELDS = ("subpages", "read_errors", "order_errors", "wait_errors",
                 "tx_dropped", "read_us_max")
STATUS_LEN = 4 * len(STATUS_FIELDS)

# How long a complete block of each type must be.
SUBPAGE_LEN = 833 * 2       # 768 pixels + 64 aux words + control register
EEPROM_LEN = 832 * 2


def _length_ok(type_, n):
    """Is a finished block of this type the right size?

    A wrong size means the sender does not speak this version of the
    protocol. The block is then dropped and counted, because the tools
    downstream unpack these bytes into fixed-size arrays and would fail on
    anything else. STATUS is allowed to be longer than we know: a newer
    firmware may append fields, and the ones we read stay in place.
    """
    if type_ == TYPE_SUBPAGE:
        return n == SUBPAGE_LEN
    if type_ == TYPE_EEPROM:
        return n == EEPROM_LEN
    if type_ == TYPE_STATUS:
        return n >= STATUS_LEN
    return True                 # unknown type: pass it through untouched


@dataclass
class Block:
    type: int
    seq: int
    subpage: int
    timestamp_us: int
    data: bytes

    def words(self):
        """The data as a list of little-endian uint16."""
        n = len(self.data) // 2
        return list(struct.unpack(f"<{n}H", self.data[:n * 2]))

    def frame_data(self):
        """SUBPAGE only: the 834-word frameData the Melexis functions expect
        (833 words from the device + the subpage number). The length was
        checked by the assembler, so this always has the right size."""
        return self.words() + [self.subpage]

    def status(self):
        """STATUS only: dict of the device counters. Extra bytes from a
        newer firmware are ignored."""
        return dict(zip(STATUS_FIELDS,
                        struct.unpack("<6I", self.data[:STATUS_LEN])))


class BlockAssembler:
    """Collect parts by (type, seq). Emit a block when all parts are in.

    Counts, per type:
      seq_gaps    blocks that never arrived (jumps in seq)
      incomplete  blocks where some parts were missing
      bad_blocks  blocks that arrived complete but the wrong size
    """

    def __init__(self):
        self._pending = {}          # type -> (seq, {part: packet})
        self._last_seq = {}         # type -> seq of the last complete block
        self.seq_gaps = {}
        self.incomplete = {}
        self.bad_blocks = {}
        self.blocks = {}

    def _count(self, table, type_, n=1):
        table[type_] = table.get(type_, 0) + n

    def add(self, pkt):
        """Add one packet. Returns a Block when a complete and well-formed
        block is ready, else None."""
        pending = self._pending.get(pkt.type)
        if pending is not None and pending[0] != pkt.seq:
            # A new block started before the old one was complete.
            self._count(self.incomplete, pkt.type)
            pending = None
        if pending is None:
            pending = (pkt.seq, {})
            self._pending[pkt.type] = pending
        pending[1][pkt.part] = pkt
        if len(pending[1]) < pkt.part_count:
            return None

        del self._pending[pkt.type]
        parts = [pending[1][i] for i in range(pkt.part_count)]

        last = self._last_seq.get(pkt.type)
        if last is not None and pkt.seq != (last + 1) & 0xFFFFFFFF:
            self._count(self.seq_gaps, pkt.type, (pkt.seq - last - 1) & 0xFFFFFFFF)
        self._last_seq[pkt.type] = pkt.seq

        # Every part but the last must be full, and the block must have the
        # size its type always has. These bytes come off the wire, so a
        # mismatch is reported as a number, never as a crash.
        data = b"".join(p.payload for p in parts)
        if (any(len(p.payload) != PART_MAX for p in parts[:-1])
                or not _length_ok(pkt.type, len(data))):
            self._count(self.bad_blocks, pkt.type)
            return None

        self._count(self.blocks, pkt.type)
        first = parts[0]
        return Block(pkt.type, pkt.seq, first.subpage, first.timestamp_us, data)
