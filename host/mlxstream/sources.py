"""Data sources: where the byte stream comes from.

Every source has read() -> bytes (may be empty) and close(). The parser,
statistics and display code only use this, so switching from USB to
Ethernet (M7) only means picking another source.

Tools take a source as text (open_source):
    usb            the board's COM port, found by VID/PID
    usb:COM9       a specific COM port
    udp            the board over Ethernet (default address)
    udp:1.2.3.4    the board at that address
    file:path      a stream saved earlier (stream_stats.py --save)
"""

import serial
import serial.tools.list_ports

USB_VID = 0x2E8A
USB_PID = 0x0009
USB_PRODUCT = "MLX90640 Thermal Stream"


def find_serial_port():
    """Find the board's COM port by VID/PID (and product name if Windows
    reports it). Returns the port name, or None."""
    candidates = [p for p in serial.tools.list_ports.comports()
                  if p.vid == USB_VID and p.pid == USB_PID]
    named = [p for p in candidates if p.product and USB_PRODUCT in p.product]
    chosen = named or candidates
    return chosen[0].device if chosen else None


class FileSource:
    """A byte stream saved earlier (stream_stats.py --save). read() returns
    b"" at the end. Used to work on the PC side without the board."""

    def __init__(self, path, chunk=16384):
        self.name = path
        self._f = open(path, "rb")
        self._chunk = chunk
        self.eof = False

    def read(self):
        data = self._f.read(self._chunk)
        if not data:
            self.eof = True
        return data

    def close(self):
        self._f.close()


class SerialSource:
    """USB CDC virtual COM port. The baud rate setting does not matter for
    USB CDC; opening the port (DTR on) tells the board to start sending."""

    def __init__(self, port=None, chunk=16384, timeout=0.05):
        port = port or find_serial_port()
        if port is None:
            raise RuntimeError("board COM port not found (VID 2E8A / PID 0009)")
        self.name = port
        self._chunk = chunk
        self._ser = serial.Serial(port, timeout=timeout)
        self._ser.dtr = True

    def read(self):
        n = max(1, self._ser.in_waiting)
        return self._ser.read(min(n, self._chunk))

    def close(self):
        self._ser.close()


def open_source(spec):
    """Open a source from text like 'usb', 'udp:192.168.1.200', 'file:x.bin'."""
    kind, _, arg = spec.partition(":")
    if kind == "usb":
        return SerialSource(arg or None)
    if kind == "udp":
        from .udp_source import UdpSource    # imported late: needs no pyserial
        return UdpSource(arg) if arg else UdpSource()
    if kind == "file":
        return FileSource(arg)
    raise ValueError(f"unknown source '{spec}' (use usb, udp or file:path)")
