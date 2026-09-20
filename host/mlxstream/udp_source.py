"""UDP data source (M7): same byte stream, over Ethernet instead of USB.

The PC starts the conversation: it sends a REQUEST packet to the board
about once per second. The board then sends its packets back to this
socket. That way the board does not need to know the PC's address in
advance, and the Windows firewall lets the answers in (they belong to a
connection the PC started). See docs/protocol.md.

Finding the board
-----------------
The board's address can change (it uses DHCP with a fixed address as
fallback), so it is searched for:

  1. the address given on the command line, or the one remembered from
     last time (host/.board_address), is tried first, as a normal packet
  2. if there is no answer, REQUESTs go to the broadcast address as well,
     several times per second, until the board answers
  3. the answer comes from the board's real address; from then on every
     REQUEST goes only to that address, and it is remembered for next time

Broadcast is only used for the search, because Wi-Fi does not acknowledge
or resend broadcast frames, so they are lost more easily. Normal packets
are acknowledged by Wi-Fi, so the stream itself never depends on
broadcast.
"""

import os
import socket
import struct
import time

from .protocol import SUBPAGE_NONE, TYPE_REQUEST, build_packet

BOARD_PORT = 5005
BROADCAST_IP = "255.255.255.255"
SEARCH_PERIOD_S = 0.25          # while searching
KEEPALIVE_PERIOD_S = 1.0        # once the board is found
REQ_SEND_EEPROM = 1 << 0

ADDRESS_FILE = os.path.join(os.path.dirname(__file__), "..", ".board_address")


def _remembered_address():
    try:
        with open(ADDRESS_FILE) as f:
            return f.read().strip() or None
    except OSError:
        return None


def _remember_address(ip):
    try:
        with open(ADDRESS_FILE, "w") as f:
            f.write(ip)
    except OSError:
        pass                    # only a convenience; ignore failures


class UdpSource:
    def __init__(self, ip=None, port=BOARD_PORT, timeout=0.05):
        self._port = port
        self._timeout = timeout
        self._known_ip = ip or _remembered_address()
        self._found = False
        self.name = f"udp {self._known_ip or 'searching'}:{port}"
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
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
        targets = []
        if self._known_ip:
            targets.append(self._known_ip)
        if not self._found:
            targets.append(BROADCAST_IP)
        for ip in targets:
            try:
                self._sock.sendto(pkt, (ip, self._port))
            except OSError:
                pass

    def read(self):
        now = time.perf_counter()
        if now >= self._next_request:
            # Ask for the EEPROM in the first request, so a receiver that
            # starts late does not wait for the next periodic copy.
            self._send_request(REQ_SEND_EEPROM if self._first else 0)
            self._first = False
            self._next_request = now + (KEEPALIVE_PERIOD_S if self._found
                                        else SEARCH_PERIOD_S)
        chunks = []
        try:
            while True:
                data, addr = self._sock.recvfrom(2048)
                if not self._found:
                    # The first answer tells us where the board really is.
                    self._found = True
                    self._known_ip = addr[0]
                    self.name = f"udp {addr[0]}:{self._port}"
                    _remember_address(addr[0])
                chunks.append(data)
                self._sock.settimeout(0)        # take everything queued
        except (socket.timeout, BlockingIOError, OSError):
            pass
        finally:
            # Back to the blocking timeout, so the next read waits again.
            self._sock.settimeout(self._timeout)
        return b"".join(chunks)

    def close(self):
        self._sock.close()
