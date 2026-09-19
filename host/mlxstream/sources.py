"""Data sources: where the byte stream comes from.

Every source has read() -> bytes (may be empty) and close(). The parser,
statistics and display code only use this, so switching from USB to
Ethernet (M7) only means picking another source.
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
