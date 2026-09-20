"""Background worker for the viewer: read -> parse -> temperatures.

Runs in its own thread so the GUI never waits on the COM port. Each full
update is sent to the GUI as a Frame through a Qt signal.

The blocks-to-image part is in pipeline.ImageStream, shared with
check_temps.py. What is left here is what only the GUI needs: the Qt
signals, the measured rate, the error counters and replaying a recording
at its original speed.
"""

import time
from dataclasses import dataclass, field

import numpy as np
from PySide6 import QtCore

from .pipeline import DEFAULT_CALC, DEFAULT_EMISSIVITY, ImageStream
from .protocol import TYPE_SUBPAGE
from .receiver import Receiver
from .sources import FileSource, open_source

# How many recent subpages the displayed rate is averaged over (about 1 s).
RATE_WINDOW = 33


@dataclass
class Frame:
    image: np.ndarray            # 24x32 degC
    ta: float                    # sensor temperature, degC
    subpage: int
    seq: int
    timestamp_us: int            # device time of this subpage
    rate_hz: float               # subpages per second (device timestamps)
    counters: dict = field(default_factory=dict)


class StreamWorker(QtCore.QObject):
    frame_ready = QtCore.Signal(object)
    message = QtCore.Signal(str)

    def __init__(self, source="usb", replay=None, emissivity=DEFAULT_EMISSIVITY,
                 calc=DEFAULT_CALC):
        super().__init__()
        self._source = source
        self._replay = replay
        self._calc = calc
        self._running = True
        self.emissivity = emissivity

    def stop(self):
        self._running = False

    def _open(self):
        if self._replay:
            return FileSource(self._replay)
        return open_source(self._source)

    def _counters(self, rx, images):
        """The numbers shown next to the image: what this PC missed, and
        what the board itself reported in its last STATUS block."""
        p, a = rx.parser, rx.assembler
        st = images.status
        return {
            "crc": p.crc_errors,
            "gaps": a.seq_gaps.get(TYPE_SUBPAGE, 0),
            "incomplete": sum(a.incomplete.values()) + sum(a.bad_blocks.values()),
            "dev_dropped": st.get("tx_dropped", 0),
            "dev_errors": sum(st.get(k, 0) for k in
                              ("read_errors", "order_errors", "wait_errors")),
        }

    @QtCore.Slot()
    def run(self):
        try:
            rx = Receiver(self._open())
        except Exception as e:           # no board / bad file: tell the GUI
            self.message.emit(f"無法開啟資料來源：{e}")
            return
        self.message.emit(f"資料來源：{rx.source.name}")

        images = ImageStream(self._calc, self.emissivity)
        rate_ts = []                     # recent device timestamps, for the rate
        replay_t0 = None                 # (wall clock, device time) at replay start

        while self._running:
            blocks = rx.poll()
            if self._replay and rx.source.eof:
                # Loop the recording.
                rx.close()
                rx = Receiver(self._open())
                images.reset()
                replay_t0, rate_ts = None, []
                continue

            for b in blocks:
                images.emissivity = self.emissivity
                image = images.push(b)
                if images.new_eeprom:
                    self.message.emit("已收到 EEPROM（ExtractParameters = "
                                      f"{images.calc.extract_error}）")
                if image is None:
                    continue

                if self._replay:
                    # Play back at the original speed.
                    now = time.perf_counter()
                    if replay_t0 is None:
                        replay_t0 = (now, b.timestamp_us)
                    due = replay_t0[0] + (b.timestamp_us - replay_t0[1]) / 1e6
                    if due > now:
                        time.sleep(due - now)

                rate_ts.append(b.timestamp_us)
                rate_ts = rate_ts[-RATE_WINDOW:]
                rate = ((len(rate_ts) - 1) / ((rate_ts[-1] - rate_ts[0]) / 1e6)
                        if len(rate_ts) > 1 else 0.0)
                self.frame_ready.emit(Frame(image, images.ta, b.subpage, b.seq,
                                            b.timestamp_us, rate,
                                            self._counters(rx, images)))
            if not blocks and self._replay is None:
                time.sleep(0.002)
        rx.close()
