"""Measure I2C rise time from Logic 8 analog captures of rise_test (M2).

Why this is not just "read the rise time off the analog trace"
--------------------------------------------------------------
The Logic 8 analog input has only about 1 MHz bandwidth at 10 MS/s. Its own
step response is a few hundred ns, about as slow as the I2C lines we want
to measure. So we do two things:

1. Equivalent-time sampling. rise_test repeats the same edge every period P.
   We fit P very precisely from the edge times, then "fold" all samples
   into one period by their phase (t mod P). Tens of thousands of edges
   land at different phases, which rebuilds the edge with ~2 ns steps
   instead of the 100 ns sample step.

2. Remove the analyzer's own response. The marker pin (GP6) is a push-pull
   output with an edge of a few ns, so its folded trace is the analyzer's
   step response m(t). A pull-up line rises like an RC curve
   x(t) = 1 - exp(-t / tau). Through the analyzer it would look like
   m(t) convolved with dx/dt. We search for the tau (and time shift) whose
   result best matches the folded SDA/SCL trace.

The 30%-70% rise time of an RC curve is tau * ln(7/3) = 0.847 * tau.

Needs numpy (run with: py -3.13 analyze_rise_analog.py ...).

Usage:
    py -3.13 analyze_rise_analog.py <marker analog.csv> <line analog.csv> [<line2 analog.csv> ...]
"""

import csv
import math
import sys

import numpy as np

BIN_S = 2e-9
LIMIT_FMP_NS = 120
LIMIT_FM_NS = 300


def load(path):
    with open(path, newline="") as f:
        reader = csv.reader(f)
        next(reader)
        data = np.array([[float(a), float(b)] for a, b in reader])
    return data[:, 0], data[:, 1]


def crossings(t, v, level, rising):
    """Interpolated times where v crosses `level` in one direction."""
    if rising:
        idx = np.nonzero((v[:-1] < level) & (v[1:] >= level))[0]
    else:
        idx = np.nonzero((v[:-1] > level) & (v[1:] <= level))[0]
    frac = (level - v[idx]) / (v[idx + 1] - v[idx])
    return t[idx] + frac * (t[idx + 1] - t[idx])


def fit_period(times):
    """Fit times[i] = t0 + n_i * P with integer n_i. Returns (t0, P, rms jitter)."""
    d = np.diff(times)
    p0 = np.median(d)
    # Count periods edge by edge. Dividing the total time by p0 instead
    # would add up p0's small error over tens of thousands of periods.
    n = np.concatenate([[0], np.cumsum(np.round(d / p0))])
    a = np.vstack([np.ones_like(n), n]).T
    (t0, p), *_ = np.linalg.lstsq(a, times, rcond=None)
    resid = times - (t0 + n * p)
    return t0, p, float(np.sqrt(np.mean(resid ** 2)))


def fold(t, v, t0, period):
    """Average samples by phase within one period. Returns (phase grid, mean value)."""
    phase = np.mod(t - t0, period)
    nbins = int(period / BIN_S)
    b = np.minimum((phase / BIN_S).astype(int), nbins - 1)
    s = np.bincount(b, weights=v, minlength=nbins)
    c = np.bincount(b, minlength=nbins)
    with np.errstate(invalid="ignore"):
        mean = s / c
    # Fill any empty bins from neighbours (rare).
    good = c > 0
    mean[~good] = np.interp(np.nonzero(~good)[0], np.nonzero(good)[0], mean[good])
    return np.arange(nbins) * BIN_S, mean, int(c.min())


def rising_edge(t, v):
    """Fold the trace and return a normalized rising edge window (time from 0, 0..1)."""
    lo, hi = np.percentile(v, 2), np.percentile(v, 98)
    mid = (lo + hi) / 2
    t0, period, jitter = fit_period(crossings(t, v, mid, True))
    ph, wave, min_count = fold(t, v, t0, period)

    # The crossing is at phase 0. Look from -40% to +40% of the period.
    wave = np.roll(wave, int(0.4 * len(wave)))
    ph = ph - 0.4 * period
    n_edge = int(0.4 * len(wave))
    low = np.median(wave[: n_edge // 2])                 # well before the edge
    high = np.median(wave[n_edge + n_edge // 2 : n_edge * 2])  # well after it
    norm = (wave[: 2 * n_edge] - low) / (high - low)
    return ph[: 2 * n_edge], norm, dict(period=period, jitter=jitter,
                                        low=low, high=high, min_count=min_count)


def t_between(ph, y, a, b):
    """Time from first crossing of level a to first crossing of level b."""
    def first(level):
        i = np.nonzero(y >= level)[0][0]
        return ph[i - 1] + (level - y[i - 1]) / (y[i] - y[i - 1]) * (ph[i] - ph[i - 1])
    return first(b) - first(a)


def mid_index(y):
    """Index where y first reaches 0.5."""
    return int(np.nonzero(y >= 0.5)[0][0])


def fit_tau(ph, marker, line):
    """Find tau so that (marker step response) * (RC input) matches `line`.

    The two traces come from different captures, so their time offset is
    unknown. For each tau we line up the 50% points of model and line, then
    try small extra shifts around that.
    """
    n = len(ph)
    h = np.diff(marker, prepend=marker[0])       # analyzer impulse response
    tt = np.arange(n) * BIN_S
    size = 1 << (2 * n - 1).bit_length()
    h_f = np.fft.rfft(h, size)
    line_mid = mid_index(line)
    lo, hi = 300, n - 300                         # ignore roll wrap-around
    best = None
    for tau_ns in np.arange(10, 1000, 2):
        x = 1 - np.exp(-tt / (tau_ns * 1e-9))
        model = np.fft.irfft(h_f * np.fft.rfft(x, size), size)[:n] + marker[0]
        base = line_mid - mid_index(model)
        for extra in range(-25, 26):
            m = np.roll(model, base + extra)
            err = float(np.mean((m[lo:hi] - line[lo:hi]) ** 2))
            if best is None or err < best[0]:
                best = (err, tau_ns, base + extra)
    return best


def main(marker_path, line_paths):
    tm, vm = load(marker_path)
    ph_m, m, info_m = rising_edge(tm, vm)
    print(f"marker: period {info_m['period'] * 1e6:.4f} us, edge jitter {info_m['jitter'] * 1e9:.1f} ns rms, "
          f"levels {info_m['low']:.2f}..{info_m['high']:.2f} V, min samples/bin {info_m['min_count']}")
    tr_m = t_between(ph_m, m, 0.3, 0.7)
    print(f"  analyzer's own 30-70% rise (from the fast marker edge): {tr_m * 1e9:.0f} ns")

    ok = True
    for path in line_paths:
        t, v = load(path)
        ph, y, info = rising_edge(t, v)
        # Put both on the same length.
        n = min(len(y), len(m))
        err, tau_ns, shift = fit_tau(ph[:n], m[:n], y[:n])
        tr_ns = tau_ns * math.log(7 / 3)
        rms_pct = math.sqrt(err) * 100
        raw = t_between(ph, y, 0.3, 0.7) * 1e9
        print(f"{path}:")
        print(f"  levels {info['low']:.2f}..{info['high']:.2f} V, period {info['period'] * 1e6:.4f} us, "
              f"edge jitter {info['jitter'] * 1e9:.1f} ns rms")
        print(f"  raw 30-70% on the analog trace (includes analyzer): {raw:.0f} ns")
        print(f"  fitted RC: tau = {tau_ns:.0f} ns -> line 30-70% rise = {tr_ns:.0f} ns "
              f"(fit error {rms_pct:.1f}% rms)")
        print(f"  limit: {LIMIT_FMP_NS} ns @1 MHz -> {'PASS' if tr_ns <= LIMIT_FMP_NS else 'FAIL'}, "
              f"{LIMIT_FM_NS} ns @400 kHz -> {'PASS' if tr_ns <= LIMIT_FM_NS else 'FAIL'}")
        ok = ok and tr_ns <= LIMIT_FMP_NS
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2:]))
