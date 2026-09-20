"""Live thermal image viewer (M5).

Shows the MLX90640 image in degC, converted on the PC with the Melexis
code (method A). Data comes from the board over USB, or from a saved
stream for work without the board.

Usage:
    host/.venv/Scripts/python host/viewer.py                 # live over USB
    host/.venv/Scripts/python host/viewer.py --source udp    # live over Ethernet
    host/.venv/Scripts/python host/viewer.py --replay captures/m4_stream_65s.bin
"""

import argparse
import sys
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from mlxstream.pipeline import CALC_CLASSES, DEFAULT_CALC
from mlxstream.worker import StreamWorker

ROWS, COLS = 24, 32
HISTORY_S = 30.0
COLORMAPS = ["inferno", "turbo", "magma", "viridis", "CET-L1"]
AVG_WEIGHT = 0.2        # time average: about 5 subpages (0.16 s at 32 Hz)

# --- Look ------------------------------------------------------------------
BG = "#15171c"
PANEL = "#1e2128"
CARD = "#262a33"
TEXT = "#e6e8ee"
MUTED = "#8b93a5"
ACCENT = "#ff8a3d"

STYLE = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-family: "Segoe UI", "Microsoft JhengHei";
           font-size: 10pt; }}
#panel {{ background: {PANEL}; border-left: 1px solid #2c313b; }}
#card {{ background: {CARD}; border-radius: 10px; }}
#cardTitle {{ color: {MUTED}; font-size: 9pt; background: transparent; }}
#cardValue {{ font-size: 20pt; font-weight: 600; background: transparent; }}
#section {{ color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 1px;
            padding-top: 8px; background: transparent; }}
#stat {{ color: {TEXT}; background: transparent; }}
#panel QLabel {{ background: transparent; }}
QComboBox, QDoubleSpinBox {{ background: {CARD}; border: 1px solid #353b47;
                            border-radius: 6px; padding: 4px 8px; }}
QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #4a5160;
                        border-radius: 4px; background: {CARD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QStatusBar {{ background: {PANEL}; color: {MUTED}; }}
"""


def upsample(img, factor):
    """Bilinear enlarge (for a smoother look). The data itself stays 32x24."""
    rows, cols = img.shape
    y = np.linspace(0, rows - 1, rows * factor)
    x = np.linspace(0, cols - 1, cols * factor)
    y0 = np.floor(y).astype(int)
    x0 = np.floor(x).astype(int)
    y1 = np.minimum(y0 + 1, rows - 1)
    x1 = np.minimum(x0 + 1, cols - 1)
    wy = (y - y0)[:, None]
    wx = (x - x0)[None, :]
    top = img[y0][:, x0] * (1 - wx) + img[y0][:, x1] * wx
    bot = img[y1][:, x0] * (1 - wx) + img[y1][:, x1] * wx
    return top * (1 - wy) + bot * wy


class Card(QtWidgets.QFrame):
    """A small box with a title and a big number."""

    def __init__(self, title, color=TEXT):
        super().__init__()
        self.setObjectName("card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)
        t = QtWidgets.QLabel(title)
        t.setObjectName("cardTitle")
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("cardValue")
        self.value.setStyleSheet(f"color: {color};")
        lay.addWidget(t)
        lay.addWidget(self.value)

    def set(self, text):
        self.value.setText(text)


class Viewer(QtWidgets.QMainWindow):
    def __init__(self, source, replay, calc=DEFAULT_CALC):
        super().__init__()
        self.setWindowTitle("MLX90640 Thermal Viewer"
                            + (f"  [{'replay' if replay else source}]")
                            + (f"  [calc: {calc}]" if calc != DEFAULT_CALC else ""))
        self.resize(1280, 800)

        self._last = None                   # last Frame
        self._levels = None                 # smoothed auto color range
        self._t0 = time.perf_counter()
        self._hist = {k: deque() for k in ("t", "max", "spot", "median")}
        self._hover = None                  # (row, col) under the mouse
        self._avg = None                    # time-averaged image

        self._build_ui()

        # --- Worker thread ---------------------------------------------------
        self._thread = QtCore.QThread(self)
        self._worker = StreamWorker(source=source, replay=replay, calc=calc)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.frame_ready.connect(self._on_frame)
        self._worker.message.connect(self.statusBar().showMessage)
        self._thread.start()

    # ------------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        h = QtWidgets.QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Left: image + color bar on top, temperature history below.
        pg.setConfigOptions(imageAxisOrder="row-major", antialias=True, background=BG,
                            foreground=MUTED)
        glw = pg.GraphicsLayoutWidget()
        self.plot = glw.addPlot(row=0, col=0)
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)             # row 0 at the top
        self.plot.hideAxis("left")
        self.plot.hideAxis("bottom")
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(False, False)
        self.image = pg.ImageItem()
        self.plot.addItem(self.image)
        self.hot_marker = pg.ScatterPlotItem(size=16, symbol="+", pen=pg.mkPen("w", width=2),
                                             brush=None)
        self.spot_marker = pg.ScatterPlotItem(size=14, symbol="o", pen=pg.mkPen(ACCENT, width=2),
                                              brush=None)
        self.plot.addItem(self.hot_marker)
        self.plot.addItem(self.spot_marker)
        self.colorbar = pg.ColorBarItem(values=(20, 35), colorMap=pg.colormap.get("inferno"),
                                        interactive=False, width=18)
        self.colorbar.setImageItem(self.image, insert_in=self.plot)

        self.hist_plot = glw.addPlot(row=1, col=0)
        self.hist_plot.setLabel("left", "°C")
        self.hist_plot.setLabel("bottom", "s")
        self.hist_plot.showGrid(x=True, y=True, alpha=0.15)
        # Legend in one row above the curves, so it does not cover them.
        self.hist_plot.addLegend(offset=(10, 1), colCount=3)
        self.hist_plot.getViewBox().setDefaultPadding(0.25)
        self.curves = {
            "max": self.hist_plot.plot(pen=pg.mkPen("#ff4d4d", width=2), name="最高"),
            "spot": self.hist_plot.plot(pen=pg.mkPen(ACCENT, width=2), name="中心點"),
            "median": self.hist_plot.plot(pen=pg.mkPen("#5fb3ff", width=2), name="中位數"),
        }
        glw.ci.layout.setRowStretchFactor(0, 3)
        glw.ci.layout.setRowStretchFactor(1, 1)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse)
        h.addWidget(glw, 1)

        # Right: numbers and controls.
        panel = QtWidgets.QWidget()
        panel.setObjectName("panel")
        panel.setFixedWidth(300)
        v = QtWidgets.QVBoxLayout(panel)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(8)
        self.card_max = Card("最高溫", "#ff6b6b")
        self.card_min = Card("最低溫", "#5fb3ff")
        self.card_spot = Card("中心點", ACCENT)
        self.card_hover = Card("游標處")
        grid.addWidget(self.card_max, 0, 0)
        grid.addWidget(self.card_min, 0, 1)
        grid.addWidget(self.card_spot, 1, 0)
        grid.addWidget(self.card_hover, 1, 1)
        v.addLayout(grid)

        v.addWidget(self._section("串流"))
        self.stat_labels = {}
        for key, name in (("rate", "subpage 速率"), ("ta", "感測器溫度 Ta"),
                          ("frames", "subpage 序號"), ("crc", "CRC 錯誤"),
                          ("gaps", "序號跳號 / 不完整"), ("dev", "裝置錯誤 / 丟包")):
            row = QtWidgets.QHBoxLayout()
            n = QtWidgets.QLabel(name)
            n.setObjectName("stat")
            n.setStyleSheet(f"color: {MUTED};")
            val = QtWidgets.QLabel("—")
            val.setObjectName("stat")
            val.setAlignment(QtCore.Qt.AlignRight)
            row.addWidget(n)
            row.addWidget(val)
            v.addLayout(row)
            self.stat_labels[key] = val

        v.addWidget(self._section("顯示"))
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.cmap_box = QtWidgets.QComboBox()
        self.cmap_box.addItems(COLORMAPS)
        self.cmap_box.currentTextChanged.connect(self._on_cmap)
        form.addRow("色彩", self.cmap_box)

        self.range_box = QtWidgets.QComboBox()
        self.range_box.addItems(["自動", "手動"])
        self.range_box.currentIndexChanged.connect(self._on_range_mode)
        form.addRow("溫度範圍", self.range_box)
        self.lo_spin = self._spin(20.0)
        self.hi_spin = self._spin(35.0)
        form.addRow("下限 °C", self.lo_spin)
        form.addRow("上限 °C", self.hi_spin)

        self.emis_spin = QtWidgets.QDoubleSpinBox()
        self.emis_spin.setRange(0.10, 1.00)
        self.emis_spin.setSingleStep(0.01)
        self.emis_spin.setValue(0.95)
        self.emis_spin.valueChanged.connect(lambda x: setattr(self._worker, "emissivity", x))
        form.addRow("放射率", self.emis_spin)
        v.addLayout(form)

        self.avg_chk = QtWidgets.QCheckBox("時間平均（降低雜訊，僅顯示）")
        self.smooth_chk = QtWidgets.QCheckBox("平滑顯示（雙線性放大）")
        self.flip_h_chk = QtWidgets.QCheckBox("左右翻轉")
        self.flip_v_chk = QtWidgets.QCheckBox("上下翻轉")
        for c in (self.avg_chk, self.smooth_chk, self.flip_h_chk, self.flip_v_chk):
            v.addWidget(c)
        v.addStretch(1)

        h.addWidget(panel)
        self._on_range_mode(0)

        self.setStyleSheet(STYLE)
        self.statusBar().showMessage("啟動中…")

    def _section(self, text):
        lab = QtWidgets.QLabel(text.upper())
        lab.setObjectName("section")
        return lab

    def _spin(self, value):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(-40.0, 300.0)
        s.setDecimals(1)
        s.setSingleStep(0.5)
        s.setValue(value)
        return s

    # ------------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------------
    def _on_cmap(self, name):
        try:
            self.colorbar.setColorMap(pg.colormap.get(name))
        except Exception:
            self.statusBar().showMessage(f"找不到色彩表 {name}")

    def _on_range_mode(self, index):
        manual = index == 1
        self.lo_spin.setEnabled(manual)
        self.hi_spin.setEnabled(manual)

    def _view(self, img):
        """Apply the flip options (display only)."""
        if self.flip_h_chk.isChecked():
            img = img[:, ::-1]
        if self.flip_v_chk.isChecked():
            img = img[::-1, :]
        return img

    def _on_mouse(self, pos):
        p = self.plot.vb.mapSceneToView(pos)
        col, row = int(np.floor(p.x())), int(np.floor(p.y()))
        self._hover = (row, col) if 0 <= row < ROWS and 0 <= col < COLS else None

    def _on_frame(self, f):
        self._last = f
        img = f.image
        # Time average (display only): exponential average over about
        # 1 / AVG_WEIGHT subpages. Noise goes down, reaction gets slower.
        if self.avg_chk.isChecked() and self._avg is not None:
            self._avg += AVG_WEIGHT * (img - self._avg)
        else:
            self._avg = img.astype(np.float64)
        if self.avg_chk.isChecked():
            img = self._avg
        img = self._view(img)

        # Color range: smoothed min/max in auto mode, so it does not flicker.
        lo, hi = float(np.min(img)), float(np.max(img))
        if self.range_box.currentIndex() == 0:
            if self._levels is None:
                self._levels = [lo, hi]
            self._levels[0] += 0.15 * (lo - self._levels[0])
            self._levels[1] += 0.15 * (hi - self._levels[1])
            levels = (self._levels[0], max(self._levels[1], self._levels[0] + 1.0))
            self.lo_spin.setValue(levels[0])
            self.hi_spin.setValue(levels[1])
        else:
            levels = (self.lo_spin.value(), max(self.hi_spin.value(), self.lo_spin.value() + 0.1))

        if self.smooth_chk.isChecked():
            factor = 8
            self.image.setImage(upsample(img, factor), levels=levels, autoLevels=False)
            self.image.setRect(QtCore.QRectF(0, 0, COLS, ROWS))
        else:
            self.image.setImage(img, levels=levels, autoLevels=False)
            self.image.setRect(QtCore.QRectF(0, 0, COLS, ROWS))
        self.colorbar.setLevels(levels)

        # Markers: hottest pixel and the center spot (2x2 average).
        r, c = np.unravel_index(np.argmax(img), img.shape)
        self.hot_marker.setData([c + 0.5], [r + 0.5])
        self.spot_marker.setData([COLS / 2], [ROWS / 2])
        spot = float(np.mean(img[ROWS // 2 - 1:ROWS // 2 + 1, COLS // 2 - 1:COLS // 2 + 1]))
        median = float(np.median(img))

        self.card_max.set(f"{hi:.1f}°")
        self.card_min.set(f"{lo:.1f}°")
        self.card_spot.set(f"{spot:.1f}°")
        if self._hover:
            self.card_hover.set(f"{img[self._hover]:.1f}°")
        else:
            self.card_hover.set("—")

        cnt = f.counters
        self.stat_labels["rate"].setText(f"{f.rate_hz:.2f} Hz")
        self.stat_labels["ta"].setText(f"{f.ta:.2f} °C")
        self.stat_labels["frames"].setText(f"{f.seq}")
        self.stat_labels["crc"].setText(f"{cnt['crc']}")
        self.stat_labels["gaps"].setText(f"{cnt['gaps']} / {cnt['incomplete']}")
        self.stat_labels["dev"].setText(f"{cnt['dev_errors']} / {cnt['dev_dropped']}")

        # History plot.
        t = time.perf_counter() - self._t0
        for key, val in (("t", t), ("max", hi), ("spot", spot), ("median", median)):
            self._hist[key].append(val)
        while self._hist["t"] and t - self._hist["t"][0] > HISTORY_S:
            for d in self._hist.values():
                d.popleft()
        ts = np.fromiter(self._hist["t"], float)
        for key, curve in self.curves.items():
            curve.setData(ts, np.fromiter(self._hist[key], float))
        # Time axis: always the last HISTORY_S seconds, no extra margin.
        self.hist_plot.setXRange(max(0.0, t - HISTORY_S), max(t, HISTORY_S), padding=0)

    def closeEvent(self, event):
        self._worker.stop()
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default="usb",
                    help="usb, usb:COM9, udp, udp:192.168.1.200 (default: usb)")
    ap.add_argument("--replay", help="play a saved stream instead of the board")
    ap.add_argument("--snapshot", help="save a PNG of the window after --after seconds, then quit")
    ap.add_argument("--after", type=float, default=5.0)
    ap.add_argument("--avg", action="store_true", help="start with time averaging on")
    ap.add_argument("--smooth", action="store_true", help="start with smooth display on")
    ap.add_argument("--calc", choices=list(CALC_CLASSES), default=DEFAULT_CALC,
                    help="temperature calculation: numpy port (default) or Melexis C code")
    args = ap.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(BG))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(TEXT))
    pal.setColor(QtGui.QPalette.Base, QtGui.QColor(CARD))
    pal.setColor(QtGui.QPalette.Text, QtGui.QColor(TEXT))
    pal.setColor(QtGui.QPalette.Button, QtGui.QColor(CARD))
    pal.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(TEXT))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(ACCENT))
    app.setPalette(pal)

    w = Viewer(args.source, args.replay, args.calc)
    w.avg_chk.setChecked(args.avg)
    w.smooth_chk.setChecked(args.smooth)
    w.show()
    if args.snapshot:
        def snap():
            w.grab().save(args.snapshot)
            w.close()
        QtCore.QTimer.singleShot(int(args.after * 1000), snap)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
