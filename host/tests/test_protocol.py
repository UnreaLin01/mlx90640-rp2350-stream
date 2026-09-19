"""Tests for the stream parser and block assembler (no hardware needed).

Run:  host/.venv/Scripts/python host/tests/test_protocol.py -v
"""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mlxstream.blocks import BlockAssembler  # noqa: E402
from mlxstream.protocol import (PART_MAX, TYPE_EEPROM, TYPE_SUBPAGE,  # noqa: E402
                                StreamParser, build_packet)


def block_packets(type_, subpage, seq, data, ts=1234):
    """Split a block into packets, like firmware/src/stream.c does."""
    parts = (len(data) + PART_MAX - 1) // PART_MAX
    return [build_packet(type_, subpage, p, parts, seq, ts, data[p * PART_MAX:(p + 1) * PART_MAX])
            for p in range(parts)]


def subpage_bytes(seq):
    rnd = random.Random(seq)
    return bytes(rnd.randrange(256) for _ in range(1666))


def stream_of(n, start=0):
    out = []
    for s in range(start, start + n):
        out += block_packets(TYPE_SUBPAGE, s % 2, s, subpage_bytes(s))
    return out


def parse_all(chunks):
    parser, asm = StreamParser(), BlockAssembler()
    blocks = []
    for c in chunks:
        for pkt in parser.feed(c):
            b = asm.add(pkt)
            if b:
                blocks.append(b)
    return parser, asm, blocks


class ParserTests(unittest.TestCase):
    def test_clean_stream(self):
        parser, asm, blocks = parse_all([b"".join(stream_of(5))])
        self.assertEqual([b.seq for b in blocks], [0, 1, 2, 3, 4])
        self.assertEqual(blocks[3].data, subpage_bytes(3))
        self.assertEqual(parser.crc_errors + parser.skipped_bytes, 0)
        self.assertEqual(asm.seq_gaps, {})

    def test_byte_by_byte(self):
        data = b"".join(stream_of(3))
        _, _, blocks = parse_all([data[i:i + 1] for i in range(len(data))])
        self.assertEqual(len(blocks), 3)

    def test_garbage_before_and_between(self):
        pk = stream_of(3)
        data = b"\x00MLX\xffjunk" + pk[0] + pk[1] + b"MLXTgarbage" + pk[2] + pk[3] + pk[4] + pk[5]
        parser, asm, blocks = parse_all([data])
        self.assertEqual([b.seq for b in blocks], [0, 1, 2])
        self.assertGreater(parser.skipped_bytes, 0)

    def test_start_in_the_middle(self):
        data = b"".join(stream_of(4))
        parser, asm, blocks = parse_all([data[700:]])
        # Block 0 lost its first part; blocks 1..3 must come through.
        self.assertEqual([b.seq for b in blocks], [1, 2, 3])

    def test_corrupted_byte(self):
        pk = stream_of(4)
        bad = bytearray(pk[2])
        bad[300] ^= 0x40                      # flip one payload bit
        data = pk[0] + pk[1] + bytes(bad) + pk[3] + pk[4] + pk[5] + pk[6] + pk[7]
        parser, asm, blocks = parse_all([data])
        self.assertEqual(parser.crc_errors, 1)
        self.assertEqual([b.seq for b in blocks], [0, 2, 3])
        self.assertEqual(asm.incomplete.get(TYPE_SUBPAGE), 1)   # block 1 lost a part

    def test_seq_gap(self):
        pk = stream_of(2) + stream_of(2, start=5)
        _, asm, blocks = parse_all([b"".join(pk)])
        self.assertEqual([b.seq for b in blocks], [0, 1, 5, 6])
        self.assertEqual(asm.seq_gaps[TYPE_SUBPAGE], 3)

    def test_types_have_own_seq(self):
        ee = bytes(range(256)) * 6 + bytes(128)          # 1664 bytes
        pk = (block_packets(TYPE_SUBPAGE, 0, 0, subpage_bytes(0))
              + block_packets(TYPE_EEPROM, 0xFF, 0, ee)
              + block_packets(TYPE_SUBPAGE, 1, 1, subpage_bytes(1)))
        _, asm, blocks = parse_all([b"".join(pk)])
        self.assertEqual([(b.type, b.seq) for b in blocks],
                         [(TYPE_SUBPAGE, 0), (TYPE_EEPROM, 0), (TYPE_SUBPAGE, 1)])
        self.assertEqual(blocks[1].data, ee)
        self.assertEqual(asm.seq_gaps, {})

    def test_frame_data(self):
        _, _, blocks = parse_all([b"".join(stream_of(2))])
        fd = blocks[1].frame_data()
        self.assertEqual(len(fd), 834)
        self.assertEqual(fd[833], 1)


if __name__ == "__main__":
    unittest.main()
