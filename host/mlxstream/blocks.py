"""Put packet parts back together into blocks, and check sequence numbers."""

import struct
from dataclasses import dataclass

from .protocol import PART_MAX, TYPE_STATUS, TYPE_SUBPAGE

STATUS_FIELDS = ("subpages", "read_errors", "order_errors", "wait_errors",
                 "tx_dropped", "read_us_max")


@dataclass
class Block:
    type: int
    seq: int
    subpage: int
    timestamp_us: int
    data: bytes

    def words(self):
        """The data as a list of little-endian uint16."""
        return list(struct.unpack(f"<{len(self.data) // 2}H", self.data))

    def frame_data(self):
        """SUBPAGE only: the 834-word frameData the Melexis functions expect
        (833 words from the device + the subpage number)."""
        assert self.type == TYPE_SUBPAGE
        return self.words() + [self.subpage]

    def status(self):
        """STATUS only: dict of the device counters."""
        assert self.type == TYPE_STATUS
        return dict(zip(STATUS_FIELDS, struct.unpack("<6I", self.data)))


class BlockAssembler:
    """Collect parts by (type, seq). Emit a block when all parts are in.

    Counts, per type:
      seq_gaps    blocks that never arrived (jumps in seq)
      incomplete  blocks where some parts were missing
    """

    def __init__(self):
        self._pending = {}          # type -> (seq, {part: packet})
        self._last_seq = {}         # type -> seq of the last complete block
        self.seq_gaps = {}
        self.incomplete = {}
        self.blocks = {}

    def _count(self, table, type_, n=1):
        table[type_] = table.get(type_, 0) + n

    def add(self, pkt):
        """Add one packet. Returns a Block when one is complete, else None."""
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
        data = b"".join(p.payload for p in parts)
        assert all(len(p.payload) == PART_MAX for p in parts[:-1])

        last = self._last_seq.get(pkt.type)
        if last is not None and pkt.seq != (last + 1) & 0xFFFFFFFF:
            self._count(self.seq_gaps, pkt.type, (pkt.seq - last - 1) & 0xFFFFFFFF)
        self._last_seq[pkt.type] = pkt.seq
        self._count(self.blocks, pkt.type)
        first = parts[0]
        return Block(pkt.type, pkt.seq, first.subpage, first.timestamp_us, data)
