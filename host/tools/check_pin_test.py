"""Check a Logic 8 capture of firmware/tests/pin_test.c.

The pin test drives CH0..CH3 as the bits of a counter that goes up every
100 us. This script reads the raw CSV exported by Logic 2 and checks:

  1. CH0..CH3 read as a counter that always goes up by exactly 1.
     A swapped wire breaks the order; a broken wire shows no edges.
  2. The frequency of each channel matches the expected value.
  3. How long each edge lags behind the first edge of the same tick.
     SCL/SDA go high through a pull-up, so their rising edges come late;
     this gives a first rough look at the pull-up strength.

Usage:
    python check_pin_test.py captures/m1_pin_test/digital.csv
"""

import csv
import sys

TICK_S = 100e-6
NUM_CH = 4
# Edges closer together than this belong to the same counter tick.
GROUP_WINDOW_S = 20e-6


def read_changes(path):
    """Return a list of (time, [ch0..ch3]) rows. Each row is a state change."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for rec in reader:
            rows.append((float(rec[0]), [int(v) for v in rec[1:1 + NUM_CH]]))
    return rows


def to_value(bits):
    return sum(b << i for i, b in enumerate(bits))


def main(path):
    rows = read_changes(path)
    if len(rows) < 2:
        print("FAIL: capture has no edges")
        return 1

    t_start, t_end = rows[0][0], rows[-1][0]
    duration = t_end - t_start

    # --- Per-channel edge counts and edge lag inside each tick -------------
    rising = [0] * NUM_CH
    lag_rise = [[] for _ in range(NUM_CH)]
    lag_fall = [[] for _ in range(NUM_CH)]

    # --- Group edges into ticks and check the counter ----------------------
    errors = 0
    ticks = 0
    prev_bits = rows[0][1]
    prev_value = None
    group_t0 = None

    def close_group(bits):
        nonlocal prev_value, errors, ticks
        value = to_value(bits)
        if prev_value is not None and value != (prev_value + 1) % 16:
            errors += 1
            if errors <= 10:
                print(f"  counter jump at t={group_t0:.6f}s: {prev_value} -> {value}")
        prev_value = value
        ticks += 1

    for t, bits in rows[1:]:
        # Logic 2 adds a last row at the end of the capture even when
        # nothing changed. Skip rows like that.
        if bits == prev_bits:
            continue
        if group_t0 is None or t - group_t0 > GROUP_WINDOW_S:
            if group_t0 is not None:
                close_group(prev_bits)
            group_t0 = t
        for ch in range(NUM_CH):
            if bits[ch] != prev_bits[ch]:
                lag = t - group_t0
                if bits[ch]:
                    rising[ch] += 1
                    lag_rise[ch].append(lag)
                else:
                    lag_fall[ch].append(lag)
        prev_bits = bits
    close_group(prev_bits)

    # --- Report ------------------------------------------------------------
    names = ["GP4 SDA", "GP5 SCL", "GP6 mark A", "GP7 mark B"]
    print(f"capture: {duration * 1e3:.1f} ms, {ticks} ticks "
          f"(expected about {duration / TICK_S:.0f})")
    ok = errors == 0
    for ch in range(NUM_CH):
        expected = 1 / (TICK_S * 2 * (1 << ch))
        measured = rising[ch] / duration if duration > 0 else 0
        freq_ok = abs(measured - expected) / expected < 0.01
        ok = ok and freq_ok
        r_max = max(lag_rise[ch], default=0) * 1e9
        f_max = max(lag_fall[ch], default=0) * 1e9
        print(f"CH{ch} {names[ch]:<11} {measured:8.1f} Hz (expect {expected:6.1f}) "
              f"{'OK ' if freq_ok else 'BAD'}  "
              f"max lag: rise {r_max:6.0f} ns, fall {f_max:6.0f} ns")
    print(f"counter errors: {errors}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
