"""UDP data source (M7): same byte stream, over Ethernet instead of USB.

The PC starts the conversation: it sends a REQUEST packet to the board
about once per second. The board then sends its packets back to this
socket. That way the board does not need to know the PC's address in
advance, and the Windows firewall lets the answers in (they belong to a
connection the PC started). See docs/protocol.md.
"""

import socket
import struct
import time

from .protocol import SUBPAGE_NONE, TYPE_REQUEST, build_packet

BOARD_IP = "192.168.1.200"
BOARD_PORT = 5005
REQUEST_PERIOD_S = 1.0
REQ_SEND_EEPROM = 1 << 0


class UdpSource:
    def __init__(self, ip=BOARD_IP, port=BOARD_PORT, timeout=0.05):
        self.name = f"udp {ip}:{port}"
        self._addr = (ip, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", 0))
        self._sock.settimeout(timeout)
        # A bigger receive buffer: the board sends in bursts of 2 packets
        # every 32 ms, and the PC may be busy drawing.
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self._seq = 0
        self._next_request = 0.0
        self._first = True

    def _send_request(self, flags):
        payload = struct.pack("<I", flags)
        pkt = build_packet(TYPE_REQUEST, SUBPAGE_NONE, 0, 1, self._seq, 0, payload)
        self._seq += 1
        try:
            self._sock.sendto(pkt, self._addr)
        except OSError:
            pass

    def read(self):
        now = time.perf_counter()
        if now >= self._next_request:
            # Ask for the EEPROM in the first request, so a receiver that
            # starts late does not wait for the next periodic copy.
            self._send_request(REQ_SEND_EEPROM if self._first else 0)
            self._first = False
            self._next_request = now + REQUEST_PERIOD_S
        chunks = []
        try:
            while True:
                chunks.append(self._sock.recv(2048))
                self._sock.settimeout(0)        # take everything queued
        except (socket.timeout, BlockingIOError, OSError):
            pass
        finally:
            self._sock.settimeout(0.05)
        return b"".join(chunks)

    def close(self):
        self._sock.close()
