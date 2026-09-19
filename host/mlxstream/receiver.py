"""Receiver: source -> parser -> block assembler, in one object.

All PC tools (stream_stats, check_temps, viewer) get blocks through this,
so they work the same with any source (USB, saved file, later UDP).
"""

from .blocks import BlockAssembler
from .protocol import StreamParser


class Receiver:
    def __init__(self, source):
        self.source = source
        self.parser = StreamParser()
        self.assembler = BlockAssembler()

    def poll(self):
        """Read what is available and return the complete blocks (may be [])."""
        blocks = []
        for pkt in self.parser.feed(self.source.read()):
            b = self.assembler.add(pkt)
            if b:
                blocks.append(b)
        return blocks

    def close(self):
        self.source.close()
