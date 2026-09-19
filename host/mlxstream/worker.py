"""Background worker for the viewer: read -> parse -> temperatures.

Runs in its own thread so the GUI never waits on the COM port. Each full
update is sent to the GUI as a Frame through a Qt signal.
"""

import time
from dataclasses import dataclass, field

import numpy as np
from PySide6 import QtCore

from .calc_melexis import MelexisCalc
from .calc_python import PythonCalc
from .protocol import TYPE_EEPROM, TYPE_STATUS, TYPE_SUBPAGE

# Temperature calculation: "melexis" = official C code (method A),
# "python" = numpy port (method B). Both give the same result.
CALC_CLASSES = {"melexis": MelexisCalc, "python": PythonCalc}
from .receiver import Receiver
from .sources import FileSource, SerialSource


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

    def __init__(self, port=None, replay=None, emissivity=0.95, calc="melexis"):
        super().__init__()
        self._port = port
        self._replay = replay
        self._calc_class = CALC_CLASSES[calc]
        self._running = True
        self.emissivity = emissivity

    def stop(self):
        self._running = False

    def _open(self):
        if self._replay:
            return FileSource(self._replay)
        return SerialSource(self._port)

    @QtCore.Slot()
    def run(self):
        try:
            rx = Receiver(self._open())
        except Exception as e:           # no board / bad file: tell the GUI
            self.message.emit(f"無法開啟資料來源：{e}")
            return
        self.message.emit(f"資料來源：{rx.source.name}")

        calc = None
        ee_words = None
        seen = set()
        device_status = {}
        rate_ts = []                     # recent device timestamps, for the rate
        replay_t0 = None                 # (wall clock, device time) at replay start

        while self._running:
            blocks = rx.poll()
            if self._replay and rx.source.eof:
                # Loop the recording.
                rx.close()
                rx = Receiver(self._open())
                calc, seen, replay_t0, rate_ts = None, set(), None, []
                continue

            for b in blocks:
                if b.type == TYPE_EEPROM:
                    words = b.words()
                    if calc is None or words != ee_words:
                        ee_words = words
                        calc = self._calc_class(words, self.emissivity)
                        self.message.emit(f"已收到 EEPROM（ExtractParameters = {calc.extract_error}）")
                elif b.type == TYPE_STATUS:
                    device_status = b.status()
                elif b.type == TYPE_SUBPAGE and calc is not None:
                    calc.emissivity = self.emissivity
                    image = calc.update(b.frame_data())
                    seen.add(b.subpage)
                    if len(seen) < 2:
                        continue         # wait until both halves are filled

                    if self._replay:
                        # Play back at the original speed.
                        now = time.perf_counter()
                        if replay_t0 is None:
                            replay_t0 = (now, b.timestamp_us)
                        due = replay_t0[0] + (b.timestamp_us - replay_t0[1]) / 1e6
                        if due > now:
                            time.sleep(due - now)

                    rate_ts.append(b.timestamp_us)
                    rate_ts = rate_ts[-33:]
                    rate = ((len(rate_ts) - 1) / ((rate_ts[-1] - rate_ts[0]) / 1e6)
                            if len(rate_ts) > 1 else 0.0)
                    p, a = rx.parser, rx.assembler
                    counters = {
                        "crc": p.crc_errors,
                        "gaps": a.seq_gaps.get(TYPE_SUBPAGE, 0),
                        "incomplete": sum(a.incomplete.values()),
                        "dev_dropped": device_status.get("tx_dropped", 0),
                        "dev_errors": sum(device_status.get(k, 0) for k in
                                          ("read_errors", "order_errors", "wait_errors")),
                    }
                    self.frame_ready.emit(Frame(image, calc.ta, b.subpage, b.seq,
                                                b.timestamp_us, rate, counters))
            if not blocks and self._replay is None:
                time.sleep(0.002)
        rx.close()
