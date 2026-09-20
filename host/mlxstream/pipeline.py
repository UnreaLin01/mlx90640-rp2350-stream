"""Blocks -> thermal images.

Every tool that shows or checks temperatures does the same three things:
keep the calculator that an EEPROM block defines, convert each SUBPAGE
block into an image, and skip the first one because only half of it is
filled. That logic lives here once, so viewer.py and check_temps.py differ
only in what they do with the result.

Which calculation to use is chosen here as well. "python" needs nothing
but numpy and is the default. "melexis" runs the official C code through a
DLL that has to be built first with scripts/build_host_lib.ps1; it is kept
as the reference the port is checked against. The two agree to within
0.04 mK, see docs/method_b_compare.md.
"""

import time

from .calc_melexis import MelexisCalc
from .calc_python import PythonCalc
from .protocol import TYPE_EEPROM, TYPE_STATUS, TYPE_SUBPAGE

CALC_CLASSES = {"python": PythonCalc, "melexis": MelexisCalc}
DEFAULT_CALC = "python"
DEFAULT_EMISSIVITY = 0.95


class ImageStream:
    """Feed it blocks, get back full images.

    Worth reading after each push():
        calc        the calculator, or None while no EEPROM has arrived
        ta          sensor temperature of the last subpage, degC
        status      counters from the last STATUS block
        convert_ms  how long the last conversion took
        new_eeprom  True on the push that built a new calculator
    """

    def __init__(self, calc=DEFAULT_CALC, emissivity=DEFAULT_EMISSIVITY):
        self._calc_class = CALC_CLASSES[calc]
        self._ee_words = None
        self._seen = set()
        self.calc = None
        self.emissivity = emissivity
        self.ta = float("nan")
        self.status = {}
        self.convert_ms = 0.0
        self.new_eeprom = False

    def reset(self):
        """Forget everything. Used when a replay file starts over."""
        self.calc = None
        self._ee_words = None
        self._seen = set()

    def push(self, block):
        """Handle one block. Returns a 24x32 image in degC once both
        subpages have been seen, otherwise None."""
        self.new_eeprom = False
        if block.type == TYPE_EEPROM:
            words = block.words()
            # Rebuild only when the calibration really changed, because
            # extracting the parameters is slow.
            if self.calc is None or words != self._ee_words:
                self._ee_words = words
                self.calc = self._calc_class(words, self.emissivity)
                self.new_eeprom = True
            return None
        if block.type == TYPE_STATUS:
            self.status = block.status()
            return None
        if block.type != TYPE_SUBPAGE or self.calc is None:
            return None

        self.calc.emissivity = self.emissivity
        t0 = time.perf_counter()
        image = self.calc.update(block.frame_data())
        self.convert_ms = (time.perf_counter() - t0) * 1e3
        self.ta = self.calc.ta
        self._seen.add(block.subpage)
        if len(self._seen) < 2:
            return None             # half the image is still empty
        return image
