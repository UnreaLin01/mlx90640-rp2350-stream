"""Check subpage read timing from a Logic 8 capture of the main firmware (M3).

Capture CH0 = SDA, CH1 = SCL, CH2 = mark A, CH3 = mark B.
  mark A: high while one subpage is read
  mark B: toggles when a new subpage is ready (edge-to-edge = subpage period)

Reports:
  - read time (mark A high) and subpage period (mark B edges)
  - read time as a share of the period (M3 target: below 50%)
  - SCL low/high time and SDA setup margin while reading, at the Logic 8
    threshold, plus the same values converted to the I2C measuring points
    (30% / 70% of VDD) using the RC time constant from docs/m2_i2c.md

Usage:
    python check_m3_timing.py <digital.csv> [tau_ns]
"""

import math
import statistics
import sys

from i2c_decode import edges, read_rows

VDD = 3.24                      # measured high level (docs/m2_i2c.md)
DEFAULT_TAU_NS = 260            # measured RC time constant (docs/m2_i2c.md)
T_L8_NS = 95                    # measured time to Logic 8 threshold


def pulses(edge_list):
    """(start, length) of every high pulse."""
    out = []
    for (t0, v0), (t1, _) in zip(edge_list, edge_list[1:]):
        if v0:
            out.append((t0, t1 - t0))
    return out


def us(x):
    return x * 1e6


def ns(x):
    return x * 1e9


def summary(values, scale, unit):
    return (f"median {scale(statistics.median(values)):.3f} {unit}, "
            f"min {scale(min(values)):.3f}, max {scale(max(values)):.3f} (n={len(values)})")


def main(path, tau_ns=DEFAULT_TAU_NS):
    rows = read_rows(path, {"sda": 1, "scl": 2, "a": 3, "b": 4})
    a_pulses = pulses(edges(rows, "a"))
    b_times = [t for t, _ in edges(rows, "b")]
    periods = [b - a for a, b in zip(b_times, b_times[1:])]
    if not a_pulses or len(periods) < 2:
        print("FAIL: not enough mark A / mark B edges")
        return 1

    reads = [length for _, length in a_pulses]
    print(f"read time (mark A):       {summary(reads, us, 'us')}")
    print(f"subpage period (mark B):  {summary(periods, us, 'us')}")
    ratio = max(reads) / min(periods)
    print(f"worst read / shortest period = {ratio * 100:.1f}%  (M3 target < 50%)")

    # SCL timing inside the read windows only.
    scl = edges(rows, "scl")
    lows, highs = [], []
    j = 0
    for start, length in a_pulses:
        end = start + length
        while j < len(scl) and scl[j][0] < start:
            j += 1
        k = j
        while k + 1 < len(scl) and scl[k + 1][0] <= end:
            (highs if scl[k][1] else lows).append(scl[k + 1][0] - scl[k][0])
            k += 1
    # Drop the long idle / between-transfer parts.
    low_limit = 2 * statistics.median(lows)
    high_limit = 2 * statistics.median(highs)
    lows = [x for x in lows if x < low_limit]
    highs = [x for x in highs if x < high_limit]
    period = statistics.median(lows) + statistics.median(highs)
    print(f"SCL at Logic 8 threshold: low {ns(statistics.median(lows)):.0f} ns "
          f"(min {ns(min(lows)):.0f}), high {ns(statistics.median(highs)):.0f} ns "
          f"(min {ns(min(highs)):.0f}), bit period {ns(period):.0f} ns "
          f"= {1 / period / 1e3:.0f} kHz")

    # Convert to the I2C spec measuring points with the RC model.
    tau = tau_ns * 1e-9
    t30 = -tau * math.log(1 - 0.3)
    t70 = -tau * math.log(1 - 0.7)
    t_l8 = T_L8_NS * 1e-9
    t_low_30 = min(lows) - t_l8 + t30          # falling edge is fast
    t_high_70 = min(highs) - (t70 - t_l8)
    print(f"  -> tLOW (30%..30%)  ~ {ns(t_low_30):.0f} ns (I2C 1 MHz min 500 ns, project rule >= 600 ns)")
    print(f"  -> tHIGH (70%..70%) ~ {ns(t_high_70):.0f} ns (I2C 1 MHz min 260 ns)")

    # SDA setup: time from the last SDA rise to the next SCL rise, for bits
    # where SDA changed during that SCL low time.
    sda = edges(rows, "sda")
    scl_rises = [t for t, v in scl if v]
    scl_falls = [t for t, v in scl if not v]
    setups = []
    i = f = 0
    for t in scl_rises:
        while i + 1 < len(sda) and sda[i + 1][0] < t:
            i += 1
        while f + 1 < len(scl_falls) and scl_falls[f + 1] < t:
            f += 1
        if sda[i][1] == 1 and sda[i][0] < t and scl_falls and sda[i][0] > scl_falls[f]:
            setups.append(t - sda[i][0])
    if setups:
        su = min(setups)
        # SDA reaches 70% later than the Logic 8 threshold; SCL reaches 30%
        # about when it crosses the Logic 8 threshold.
        su_spec = su - (t70 - t_l8) + (t30 - t_l8)
        print(f"SDA rise -> SCL rise at Logic 8 threshold: min {ns(su):.0f} ns (n={len(setups)})")
        print(f"  -> setup (SDA 70% .. SCL 30%) ~ {ns(su_spec):.0f} ns (I2C 1 MHz min 50 ns)")

    ok = ratio < 0.5
    print("RESULT:", "PASS" if ok else "FAIL (read time not below half the period)")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], *(float(x) for x in sys.argv[2:])))
