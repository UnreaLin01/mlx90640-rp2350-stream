"""Stream protocol v1: packet format and a parser that can resync.

Must match firmware/src/protocol.c and docs/protocol.md.
"""

import struct
import zlib
from dataclasses import dataclass

MAGIC = b"MLXT"
VERSION = 1
HEADER_LEN = 24
CRC_LEN = 4
PART_MAX = 1024

TYPE_SUBPAGE = 1
TYPE_EEPROM = 2
TYPE_STATUS = 3
TYPE_REQUEST = 4        # PC -> board, UDP only (docs/protocol.md)
TYPE_NAMES = {TYPE_SUBPAGE: "SUBPAGE", TYPE_EEPROM: "EEPROM", TYPE_STATUS: "STATUS",
              TYPE_REQUEST: "REQUEST"}

SUBPAGE_NONE = 0xFF

# magic, version, type, subpage, part, part_count, reserved, payload_len, seq, timestamp_us
_HEADER = struct.Struct("<4sBBBBBBHIQ")
assert _HEADER.size == HEADER_LEN


@dataclass
class Packet:
    type: int
    subpage: int
    part: int
    part_count: int
    seq: int
    timestamp_us: int
    payload: bytes


def build_packet(type_, subpage, part, part_count, seq, timestamp_us, payload):
    """Build one packet (same bytes as the firmware makes). Used by tests."""
    head = _HEADER.pack(MAGIC, VERSION, type_, subpage, part, part_count, 0,
                        len(payload), seq, timestamp_us)
    body = head + bytes(payload)
    return body + struct.pack("<I", zlib.crc32(body))


class StreamParser:
    """Turn a byte stream (with possible garbage or errors) into packets.

    Feed it bytes in any chunk sizes; it returns every complete, valid
    packet. Rules (docs/protocol.md, "重新同步規則"):
      1. find "MLXT"
      2. check the header (version, length, part numbers)
      3. check the CRC
    If a check fails, skip one byte past that magic and search again.
    """

    def __init__(self):
        self._buf = bytearray()
        self.packets = 0
        self.crc_errors = 0
        self.header_errors = 0
        self.skipped_bytes = 0      # bytes thrown away while searching

    def feed(self, data):
        self._buf += data
        out = []
        buf = self._buf
        while True:
            i = buf.find(MAGIC)
            if i < 0:
                # Keep the last 3 bytes: they may be the start of a magic.
                keep = min(len(buf), len(MAGIC) - 1)
                self.skipped_bytes += len(buf) - keep
                del buf[:len(buf) - keep]
                break
            if i > 0:
                self.skipped_bytes += i
                del buf[:i]
            if len(buf) < HEADER_LEN:
                break

            (_, version, type_, subpage, part, part_count, _, plen, seq,
             ts) = _HEADER.unpack_from(buf)
            if version != VERSION or plen > PART_MAX or part_count == 0 or part >= part_count:
                self.header_errors += 1
                self.skipped_bytes += 1
                del buf[:1]
                continue

            total = HEADER_LEN + plen + CRC_LEN
            if len(buf) < total:
                break
            (crc,) = struct.unpack_from("<I", buf, HEADER_LEN + plen)
            if zlib.crc32(buf[:HEADER_LEN + plen]) != crc:
                self.crc_errors += 1
                self.skipped_bytes += 1
                del buf[:1]
                continue

            out.append(Packet(type_, subpage, part, part_count, seq, ts,
                              bytes(buf[HEADER_LEN:HEADER_LEN + plen])))
            self.packets += 1
            del buf[:total]
        return out
