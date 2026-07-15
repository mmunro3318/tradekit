"""tests/unit/mae_indicators/test_volatility.py — SPRINT P1B story 1:
true_range, atr, bollinger, keltner (tradekit.mae._indicators.volatility).

TEST-PATH EXCEPTION (tests/ASSUMPTIONS.md, extends entry 23/29): this
module imports `tradekit.mae._indicators.volatility` directly — no public
verb wires `_indicators` in yet (P1C+).

Golden vectors (tests/golden/indicators/*.json) are NOT computed by running
these stubs (they raise NotImplementedError) and NOT from a third-party TA
library. They come from an independent, from-spec reference implementation
written directly against the formulas pinned in
docs/handoff/SPRINT-P1B-indicators.md (main body + addendum) — see
scratchpad script `gen_golden.py` referenced in each JSON's "source" field,
and this file's own dev-log entry. SERIES_A is a seeded random walk
(random.Random(20260715), 45 bars, values rounded to 2 decimals so the
hand-arithmetic comments below are exact, not binary-float mush).

Hand cross-checks below use SERIES_A rows directly (H/L/C printed in the
JSON's "input"); every number a reviewer needs to redo the arithmetic is
either quoted inline or trivially readable from the golden file.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from tradekit.mae._indicators.volatility import atr, bollinger, keltner, true_range

GOLDEN_DIR = Path(__file__).resolve().parent.parent.parent / "golden" / "indicators"


def _load(name: str) -> dict:
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text())


def _assert_aligned(actual: list, expected: list) -> None:
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        if e is None:
            assert a is None, f"index {i}: expected None, got {a}"
        else:
            assert a == pytest.approx(e, rel=1e-9, abs=1e-12), f"index {i}: {a} != {e}"


def _random_walk(n: int = 120, seed: int = 42):
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] + rng.uniform(-2.5, 2.5)))
    highs = [c + rng.uniform(0.05, 1.6) for c in closes]
    lows = [c - rng.uniform(0.05, 1.6) for c in closes]
    return highs, lows, closes


# ---------------------------------------------------------------------------
# true_range
# ---------------------------------------------------------------------------


def test_true_range_golden_vector() -> None:
    g = _load("true_range")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    _assert_aligned(out, g["expected"]["true_range"])

    # Hand check 1 (never-None boundary): TR[0] = high[0]-low[0], no
    # previous close to gap against. H0=100.88, L0=99.13 -> 100.88-99.13=1.75.
    assert out[0] == pytest.approx(1.75, abs=1e-9)

    # Hand check 2 (|low-prev_close| branch dominates): H8=95.67, L8=93.98,
    # prev close C7=97.69. high-low=95.67-93.98=1.69;
    # |high-prevclose|=|95.67-97.69|=2.02; |low-prevclose|=|93.98-97.69|=3.71.
    # max(1.69, 2.02, 3.71) = 3.71.
    assert out[8] == pytest.approx(3.71, abs=1e-9)

    # Hand check 3 (feeds directly into the ATR seed at index 13):
    # H13=96.02, L13=95.43, prev close C12=94.17. high-low=0.59;
    # |high-prevclose|=|96.02-94.17|=1.85; |low-prevclose|=|95.43-94.17|=1.26.
    # max(0.59, 1.85, 1.26) = 1.85.
    assert out[13] == pytest.approx(1.85, abs=1e-9)


def test_true_range_never_none() -> None:
    """Contract: TR[0] is NEVER None, unlike every other indicator's lookback
    prefix (addendum lookback table: true_range first non-None index = 0)."""
    g = _load("true_range")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    assert out[0] is not None


def test_true_range_gap_bar() -> None:
    """Edge vector: a gap-down bar (bar1 high=108.00 < prev close 110.00)
    exercises the |low-prev_close| branch beating both high-low and
    |high-prev_close|.

    Hand check: bar0 C=110.00 (prev close for bar1). bar1 H=108.00,
    L=104.00. high-low = 108.00-104.00 = 4.00. |high-prevclose| =
    |108.00-110.00| = 2.00. |low-prevclose| = |104.00-110.00| = 6.00.
    max(4.00, 2.00, 6.00) = 6.00.
    """
    g = _load("true_range_gap")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    _assert_aligned(out, g["expected"]["true_range"])
    assert out[1] == pytest.approx(6.0, abs=1e-9)


def test_true_range_short_series() -> None:
    """5 bars, no period parameter to fail lookback on — true_range is
    defined for every bar regardless of series length."""
    g = _load("short_series")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    _assert_aligned(out, g["expected"]["true_range"])
    assert all(v is not None for v in out)


def test_true_range_single_bar() -> None:
    g = _load("single_bar")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    _assert_aligned(out, g["expected"]["true_range"])
    assert len(out) == 1 and out[0] is not None


def test_true_range_constant_price() -> None:
    """O=H=L=C constant: no range, no gap -> TR is 0.0 everywhere (never
    None -- true_range has no lookback)."""
    g = _load("constant_price")
    out = true_range(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"])
    _assert_aligned(out, g["expected"]["true_range"])
    assert all(v == pytest.approx(0.0, abs=1e-9) for v in out)


# ---------------------------------------------------------------------------
# atr
# ---------------------------------------------------------------------------


def test_atr_golden_vector() -> None:
    g = _load("atr")
    out = atr(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=14)
    _assert_aligned(out, g["expected"]["atr"])

    # Seed boundary, index period-1=13: simple average of TR[0..13] (14
    # values). TR row (2dp): 1.75, 2.10, 2.72, 1.72, 3.59, 2.85, 2.57,
    # 2.60, 3.71, 2.67, 0.93, 3.03, 1.95, 1.85 -- sum = 34.04, /14 =
    # 2.431428571428571...
    assert out[13] == pytest.approx(34.04 / 14, rel=1e-9)

    # index period=14 (first Wilder recurrence step): TR[14]=2.01.
    # atr[14] = (atr[13]*13 + TR[14]) / 14
    #         = (2.431428571428571*13 + 2.01) / 14 = 2.401326530612245...
    assert out[14] == pytest.approx((34.04 / 14 * 13 + 2.01) / 14, rel=1e-9)

    # index period+1=15: TR[15]=1.23.
    # atr[15] = (atr[14]*13 + TR[15]) / 14 = 2.317660349854226...
    atr14 = (34.04 / 14 * 13 + 2.01) / 14
    assert out[15] == pytest.approx((atr14 * 13 + 1.23) / 14, rel=1e-9)


def test_atr_short_series_all_none() -> None:
    g = _load("short_series")
    out = atr(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=14)
    assert len(out) == len(g["input"]["closes"])
    assert all(v is None for v in out)


def test_atr_constant_price_zero_after_seed() -> None:
    """TR is 0.0 for every bar under constant price, so the Wilder average
    stays 0.0 for every bar once the seed (index 13) is reached."""
    g = _load("constant_price")
    out = atr(g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=14)
    _assert_aligned(out, g["expected"]["atr"])
    assert out[12] is None
    assert out[13] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# bollinger
# ---------------------------------------------------------------------------


def test_bollinger_golden_vector() -> None:
    g = _load("bollinger")
    mid, upper, lower = bollinger(g["input"]["closes"], period=20, k=2.0)
    _assert_aligned(mid, g["expected"]["mid"])
    _assert_aligned(upper, g["expected"]["upper"])
    _assert_aligned(lower, g["expected"]["lower"])

    # Seed boundary, index period-1=19: mid = SMA(20) of closes[0:20].
    # Sum of the 20 closes (2dp) = 1932.62 -> mid = 1932.62/20 = 96.631.
    assert mid[19] == pytest.approx(1932.62 / 20, rel=1e-9)

    # Population variance shortcut: var = mean(x^2) - mean(x)^2. Over the
    # same 20-value window, mean(x^2) = 186805.3706/20 = 9340.26853;
    # mean^2 = 96.631^2 = 9337.550161. var = 9340.26853 - 9337.550161 =
    # 2.718369 (approx, 6dp) -> std = sqrt(2.718369) ~= 1.648748.
    # upper[19] = mid + 2*std ~= 96.631 + 3.297495 ~= 99.928495
    # lower[19] = mid - 2*std ~= 96.631 - 3.297495 ~= 93.333505
    assert upper[19] == pytest.approx(99.928495, abs=5e-6)
    assert lower[19] == pytest.approx(93.333505, abs=5e-6)

    # Rolling-window check one bar later (index 20): mid[20] = mid[19] -
    # closes[0]/20 + closes[20]/20 = 96.631 - 100.00/20 + 94.37/20
    #  = 96.631 - 5.00 + 4.7185 = 96.3495.
    assert mid[20] == pytest.approx(96.3495, rel=1e-9)


def test_bollinger_short_series_all_none() -> None:
    g = _load("short_series")
    mid, upper, lower = bollinger(g["input"]["closes"], period=20, k=2.0)
    assert len(mid) == len(upper) == len(lower) == len(g["input"]["closes"])
    assert all(v is None for v in mid)
    assert all(v is None for v in upper)
    assert all(v is None for v in lower)


def test_bollinger_rejects_degenerate_period() -> None:
    """P1B review LOW-2: period < 1 would silently produce numpy nan
    means/stds from empty rolling windows — guard with a loud ValueError."""
    with pytest.raises(ValueError, match="period must be >= 1"):
        bollinger([1.0, 2.0, 3.0], period=0, k=2.0)


def test_bollinger_constant_price_collapses_to_mid() -> None:
    """Population stdev of a constant window is exactly 0.0, so upper ==
    mid == lower (no band width) once the SMA warms up."""
    g = _load("constant_price")
    mid, upper, lower = bollinger(g["input"]["closes"], period=20, k=2.0)
    assert mid[19] == pytest.approx(100.0, abs=1e-9)
    assert upper[19] == pytest.approx(100.0, abs=1e-9)
    assert lower[19] == pytest.approx(100.0, abs=1e-9)


# ---------------------------------------------------------------------------
# keltner
# ---------------------------------------------------------------------------


def test_keltner_golden_vector() -> None:
    g = _load("keltner")
    mid, upper, lower = keltner(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"],
        ema_period=20, atr_period=10, mult=2.0,
    )
    _assert_aligned(mid, g["expected"]["mid"])
    _assert_aligned(upper, g["expected"]["upper"])
    _assert_aligned(lower, g["expected"]["lower"])

    # Seed boundary, index ema_period-1=19 (the EMA(20) is the binding
    # constraint, not ATR(10) which is already valid from index 9): mid =
    # ema20[19] = 96.631 (same SMA-seed value as bollinger's mid at 19,
    # since EMA also seeds from the SMA of its first `period` values).
    # atr10[19] = 2.1383018811897982 (computed, Wilder-seeded at index 9,
    # 10 recurrence steps applied). Compositional identity check:
    # upper[19] - mid[19] should be EXACTLY 2*atr10[19].
    assert mid[19] == pytest.approx(96.631, rel=1e-9)
    assert upper[19] - mid[19] == pytest.approx(2.0 * 2.1383018811897982, rel=1e-9)
    assert mid[19] - lower[19] == pytest.approx(2.0 * 2.1383018811897982, rel=1e-9)

    # One bar later (index 20): the binding lookback stays at the EMA, and
    # the same identity holds with atr10[20] = 2.1444716930708188.
    assert upper[20] - mid[20] == pytest.approx(2.0 * 2.1444716930708188, rel=1e-9)


def test_keltner_lookback_is_ema_binding_not_atr() -> None:
    """ATR(10) alone would be valid from index 9, but keltner's default
    ema_period=20 > atr_period=10 makes the EMA the binding lookback
    (addendum: keltner(20,10) first non-None = 19, not 9)."""
    g = _load("keltner")
    mid, upper, lower = keltner(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"],
        ema_period=20, atr_period=10, mult=2.0,
    )
    for i in range(19):
        assert mid[i] is None and upper[i] is None and lower[i] is None
    assert mid[19] is not None and upper[19] is not None and lower[19] is not None


def test_keltner_short_series_all_none() -> None:
    g = _load("short_series")
    mid, upper, lower = keltner(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"],
        ema_period=20, atr_period=10, mult=2.0,
    )
    assert all(v is None for v in mid)
    assert all(v is None for v in upper)
    assert all(v is None for v in lower)


# ---------------------------------------------------------------------------
# Property tests (pinned-seed random walk, ~120 bars, stdlib random only)
# ---------------------------------------------------------------------------


def test_true_range_properties_random_walk() -> None:
    highs, lows, closes = _random_walk()
    out = true_range(highs, lows, closes)
    assert len(out) == len(closes)
    assert out[0] is not None
    assert all(v is None or v >= 0.0 for v in out)


def test_atr_properties_random_walk() -> None:
    highs, lows, closes = _random_walk()
    out = atr(highs, lows, closes, period=14)
    assert len(out) == len(closes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 13, "addendum lookback table: atr(14) first non-None = 13"
    assert all(v is not None for v in out[13:])
    assert all(v >= 0.0 for v in out if v is not None)


def test_bollinger_properties_random_walk() -> None:
    _, _, closes = _random_walk()
    mid, upper, lower = bollinger(closes, period=20, k=2.0)
    assert len(mid) == len(upper) == len(lower) == len(closes)
    none_prefix = sum(1 for v in mid if v is None)
    assert none_prefix == 19, "addendum lookback table: bollinger(20) first non-None = 19"
    for m, u, lo in zip(mid, upper, lower, strict=True):
        if m is not None:
            assert u >= m >= lo


def test_keltner_properties_random_walk() -> None:
    highs, lows, closes = _random_walk()
    mid, upper, lower = keltner(highs, lows, closes, ema_period=20, atr_period=10, mult=2.0)
    assert len(mid) == len(upper) == len(lower) == len(closes)
    none_prefix = sum(1 for v in mid if v is None)
    assert none_prefix == 19, "addendum lookback table: keltner(20,10) first non-None = 19"
    for m, u, lo in zip(mid, upper, lower, strict=True):
        if m is not None:
            assert u >= m >= lo
