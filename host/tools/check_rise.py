"""Estimate I2C rise time from a capture of firmware/tests/rise_test.c (M2).

Capture CH0 = SDA, CH1 = SCL, CH2 = mark A at 100 MS/s.

How it works
------------
The firmware releases SDA/SCL and raises mark A in the same clock cycle
(and pulls them low together). For each marker edge we measure how long
the line takes to cross the Logic 8 threshold:

    fall delay = fixed channel offset            (lines are driven low: fast)
    rise delay = fixed channel offset + t_th     (pull-up only: slow)

So t_th = mean(rise delay) - mean(fall delay). Averaging thousands of edges
gives much better than the 10 ns sample step, because the firmware edge
timing drifts against the sample clock.

From t_th to rise time
----------------------
A line pulled up by a resistor rises like an RC curve:
    V(t) = VDD * (1 - exp(-t / tau))
The Logic 8 threshold is only known to be between 0.6 V and 1.2 V (fixed
threshold, undefined in between). So t_th gives a RANGE for tau:
    tau = t_th / -ln(1 - Vth / VDD),   Vth in [0.6, 1.2] V
The I2C rise time is from 30% to 70% of VDD:
    t_r = tau * ln(0.7 / 0.3) = 0.847 * tau
The limit is 120 ns for Fast-mode Plus (1 MHz) and 300 ns for Fast-mode
(400 kHz).

Usage:
    python check_rise.py <digital.csv>
"""

import math
import statistics
import sys

from i2c_decode import edges, read_rows

VDD = 3.3
VTH_RANGE = (0.6, 1.2)
MAX_DELAY_S = 1e-6
LIMIT_FMP_NS = 120
LIMIT_FM_NS = 300


def delays(marker_edges, line_edges, level):
    """Delay from each marker edge (to `level`) to the next line edge (to `level`)."""
    out = []
    j = 0
    for t, v in marker_edges:
        if v != level:
            continue
        while j < len(line_edges) and line_edges[j][0] < t:
            j += 1
        k = j
        while k < len(line_edges) and line_edges[k][1] != level:
            k += 1
        if k < len(line_edges) and line_edges[k][0] - t < MAX_DELAY_S:
            out.append(line_edges[k][0] - t)
    return out


def ns(x):
    return x * 1e9


def main(path):
    rows = read_rows(path, {"sda": 1, "scl": 2, "mark": 3})
    mark = edges(rows, "mark")
    ok = True
    print(f"marker edges: {len(mark)}")

    for name in ("sda", "scl"):
        line = edges(rows, name)
        rise = delays(mark, line, 1)
        fall = delays(mark, line, 0)
        if len(rise) < 100 or len(fall) < 100:
            print(f"{name.upper()}: not enough edges (rise {len(rise)}, fall {len(fall)})")
            ok = False
            continue

        t_th = statistics.mean(rise) - statistics.mean(fall)
        k_lo = -math.log(1 - VTH_RANGE[0] / VDD)
        k_hi = -math.log(1 - VTH_RANGE[1] / VDD)
        tau_min, tau_max = t_th / k_hi, t_th / k_lo
        k_r = math.log(0.7 / 0.3)
        tr_min, tr_max = ns(tau_min * k_r), ns(tau_max * k_r)

        print(f"{name.upper()}: {len(rise)} rises, {len(fall)} falls")
        print(f"  rise delay: mean {ns(statistics.mean(rise)):6.1f} ns  "
              f"(min {ns(min(rise)):.0f}, max {ns(max(rise)):.0f})")
        print(f"  fall delay: mean {ns(statistics.mean(fall)):6.1f} ns  "
              f"(min {ns(min(fall)):.0f}, max {ns(max(fall)):.0f})")
        print(f"  time to Logic 8 threshold t_th = {ns(t_th):.1f} ns")
        print(f"  RC time constant tau: {ns(tau_min):.0f} .. {ns(tau_max):.0f} ns")
        print(f"  rise time 30-70%:     {tr_min:.0f} .. {tr_max:.0f} ns "
              f"(limit {LIMIT_FMP_NS} ns @1 MHz, {LIMIT_FM_NS} ns @400 kHz)")
        if tr_max <= LIMIT_FMP_NS:
            verdict = "PASS (whole range under the 1 MHz limit)"
        elif tr_min > LIMIT_FMP_NS:
            verdict = "FAIL (whole range over the 1 MHz limit)"
            ok = False
        else:
            verdict = "UNSURE (range crosses the 1 MHz limit)"
            ok = False
        print(f"  1 MHz: {verdict}")

    print("RESULT:", "PASS" if ok else "NOT PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
