"""tests/unit/mae_indicators/test_trend.py — SPRINT P1B story 3: sma, ema,
adx, supertrend (tradekit.mae._indicators.trend).

TEST-PATH EXCEPTION (tests/ASSUMPTIONS.md, extends entry 23/29): this
module imports `tradekit.mae._indicators.trend` directly — no public verb
wires `_indicators` in yet (P1C+).

Golden vectors come from the same independent, from-spec reference
implementation as test_volatility.py / test_momentum.py — see that
module's docstring and scratchpad `gen_golden.py` for full provenance.
SERIES_A (same 45-bar series used across all three test modules) is reused
here.

NOTE (constant-price edge case, adx/supertrend): a strictly constant O=H=L=C
series drives every +DM/-DM/TR to 0.0, making +DI/-DI a 0/0 ratio — this is
a genuinely undefined input for ADX (and, transitively, for a
directional-band indicator like supertrend), not a case the addendum pins a
convention for. Per the sprint doc's "as applicable" qualifier on edge
vectors, adx/supertrend are exercised via the golden vector (which already
has ample real movement) and the property test instead of a constant-price
case.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from tradekit.mae._indicators.trend import adx, ema, sma, supertrend

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
# sma
# ---------------------------------------------------------------------------


def test_sma_golden_vector() -> None:
    g = _load("sma")
    out = sma(g["input"]["values"], period=20)
    _assert_aligned(out, g["expected"]["sma"])

    # Seed boundary, index period-1=19: sum of closes[0:20] (2dp) =
    # 1932.62 -> sma[19] = 1932.62/20 = 96.631.
    assert out[19] == pytest.approx(1932.62 / 20, rel=1e-9)

    # index period=20 (rolling window, drop closes[0]=100.00, add
    # closes[20]=94.37): sma[20] = sma[19] - 100.00/20 + 94.37/20
    #  = 96.631 - 5.00 + 4.7185 = 96.3495.
    assert out[20] == pytest.approx(96.3495, rel=1e-9)

    # index period+1=21 (drop closes[1]=98.10, add closes[21]=95.44):
    # sma[21] = sma[20] - 98.10/20 + 95.44/20 = 96.3495 - 4.905 + 4.772
    #  = 96.2165.
    assert out[21] == pytest.approx(96.3495 - 98.10 / 20 + 95.44 / 20, rel=1e-9)


def test_sma_short_series_all_none() -> None:
    g = _load("short_series")
    out = sma(g["input"]["closes"], period=20)
    assert len(out) == len(g["input"]["closes"])
    assert all(v is None for v in out)


def test_sma_constant_price() -> None:
    g = _load("constant_price")
    out = sma(g["input"]["closes"], period=20)
    _assert_aligned(out, g["expected"]["sma"])
    assert out[19] == pytest.approx(100.0, abs=1e-9)


def test_sma_rejects_degenerate_period() -> None:
    """P1B review LOW-2: period < 1 would silently produce numpy nan means
    (empty rolling windows) instead of failing loudly — and volume_ratio
    reuses this sma, so the guard protects that call site too."""
    with pytest.raises(ValueError, match="period must be >= 1"):
        sma([1.0, 2.0, 3.0], period=0)


def test_sma_properties_random_walk() -> None:
    _, _, closes = _random_walk()
    out = sma(closes, period=20)
    assert len(out) == len(closes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 19, "addendum lookback table: sma(n)/ema(n) first non-None = n-1"


# ---------------------------------------------------------------------------
# ema
# ---------------------------------------------------------------------------


def test_ema_golden_vector() -> None:
    g = _load("ema")
    out = ema(g["input"]["values"], period=20)
    _assert_aligned(out, g["expected"]["ema"])

    # Seed boundary, index period-1=19: SAME seed as sma (SMA of first 20
    # values) -> ema[19] = 96.631.
    assert out[19] == pytest.approx(96.631, rel=1e-9)

    # index period=20 (first EMA recurrence step), k=2/(20+1)=2/21:
    # ema[20] = closes[20]*k + ema[19]*(1-k)
    #         = 94.37*(2/21) + 96.631*(19/21) = 96.41566666666667.
    assert out[20] == pytest.approx(94.37 * (2 / 21) + 96.631 * (19 / 21), rel=1e-9)

    # index period+1=21: ema[21] = closes[21]*k + ema[20]*(1-k)
    #  = 95.44*(2/21) + 96.41566666666667*(19/21).
    ema20 = 94.37 * (2 / 21) + 96.631 * (19 / 21)
    assert out[21] == pytest.approx(95.44 * (2 / 21) + ema20 * (19 / 21), rel=1e-9)


def test_ema_short_series_all_none() -> None:
    g = _load("short_series")
    out = ema(g["input"]["closes"], period=20)
    assert len(out) == len(g["input"]["closes"])
    assert all(v is None for v in out)


def test_ema_constant_price() -> None:
    g = _load("constant_price")
    out = ema(g["input"]["closes"], period=20)
    _assert_aligned(out, g["expected"]["ema"])
    assert out[19] == pytest.approx(100.0, abs=1e-9)


def test_ema_seed_differs_from_pandas_adjust_false_convention() -> None:
    """Documents the pinned convention explicitly (trap flagged by the
    sprint doc): ema's seed is the SMA of the first `period` values, NOT
    the first raw value (pandas'/pandas_ta's `adjust=False` seeding). A 3
    bar, period=2 toy series makes the divergence obvious:

    values = [10.0, 20.0, 100.0]. Pinned convention: ema[0]=None (period
    not met); ema[1] = SMA(values[0:2]) = 15.0 (seed); ema[2] =
    100.0*k + 15.0*(1-k), k=2/3 -> 100*0.6667+15*0.3333 = 71.667.
    `adjust=False` seeding would instead start ema[0]=10.0 (the raw first
    value) and diverge from there — this test pins OUR convention only.
    """
    out = ema([10.0, 20.0, 100.0], period=2)
    assert out[0] is None
    assert out[1] == pytest.approx(15.0, rel=1e-9)
    k = 2 / 3
    assert out[2] == pytest.approx(100.0 * k + 15.0 * (1 - k), rel=1e-9)


def test_ema_properties_random_walk() -> None:
    _, _, closes = _random_walk()
    out = ema(closes, period=20)
    assert len(out) == len(closes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 19, "addendum lookback table: sma(n)/ema(n) first non-None = n-1"


# ---------------------------------------------------------------------------
# adx
# ---------------------------------------------------------------------------


def test_adx_golden_vector() -> None:
    g = _load("adx")
    plus_di, minus_di, adx_line = adx(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=14
    )
    _assert_aligned(plus_di, g["expected"]["plus_di"])
    _assert_aligned(minus_di, g["expected"]["minus_di"])
    _assert_aligned(adx_line, g["expected"]["adx"])

    # DI seed boundary, index 14 (+DM/-DM/TR Wilder-smoothed starting at
    # index 1, so the 14-value seed window is indices 1..14, NOT 0..13
    # like a standalone atr() call). From SERIES_A:
    # +DM[1..14] = [0,0,0.73,2.74,0,1.71,0,0,0,0,2.8,0,1.72,0.95] -> sum=10.65
    # -DM[1..14] = [1.23,2.52,0,0,1.87,0,0.79,2.69,1.29,0,0,0.78,0,0] -> sum=11.17
    #  TR[1..14] = [2.1,2.72,1.72,3.59,2.85,2.57,2.6,3.71,2.67,0.93,3.03,1.95,1.85,2.01]
    #  -> sum=34.30
    # +DI[14] = 100*10.65/34.30 = 31.049562...
    # -DI[14] = 100*11.17/34.30 = 32.565597...
    assert plus_di[14] == pytest.approx(100.0 * 10.65 / 34.30, rel=1e-9)
    assert minus_di[14] == pytest.approx(100.0 * 11.17 / 34.30, rel=1e-9)

    # DX[14] (feeds the ADX seed window) = 100*|+DI-(-DI)|/(+DI+-DI)
    #  = 100*|31.049563-32.565598|/(31.049563+32.565598) ~= 2.383135.
    pd14 = 100.0 * 10.65 / 34.30
    md14 = 100.0 * 11.17 / 34.30
    dx14 = 100.0 * abs(pd14 - md14) / (pd14 + md14)
    assert dx14 == pytest.approx(2.383135, abs=5e-6)

    # ADX seed boundary, index 2*period-1=27: simple average of DX[14..27]
    # (14 values). Reference-script sum(dx[14..27]) = 79.11609013485925,
    # /14 = 5.651149295347089.
    assert adx_line[27] == pytest.approx(79.11609013485925 / 14, rel=1e-9)


def test_adx_short_series_all_none() -> None:
    g = _load("short_series")
    plus_di, minus_di, adx_line = adx(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=14
    )
    assert all(v is None for v in plus_di)
    assert all(v is None for v in minus_di)
    assert all(v is None for v in adx_line)


def test_adx_properties_random_walk() -> None:
    highs, lows, closes = _random_walk()
    plus_di, minus_di, adx_line = adx(highs, lows, closes, period=14)
    assert len(plus_di) == len(minus_di) == len(adx_line) == len(closes)
    di_none_prefix = sum(1 for v in plus_di if v is None)
    assert di_none_prefix == 14, "addendum lookback table: adx(14) DI first non-None = 14"
    adx_none_prefix = sum(1 for v in adx_line if v is None)
    assert adx_none_prefix == 27, (
        "addendum lookback table: adx(14) adx first non-None = 27 (2*period-1)"
    )
    for v in adx_line:
        if v is not None:
            assert v >= 0.0


# ---------------------------------------------------------------------------
# supertrend
# ---------------------------------------------------------------------------


def test_supertrend_golden_vector() -> None:
    g = _load("supertrend")
    line, direction = supertrend(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=10, mult=3.0
    )
    _assert_aligned(line, g["expected"]["line"])
    _assert_aligned(direction, g["expected"]["direction"])

    # First valid index, period-1=9 (initial-direction pin: compare
    # close[9] to basis[9]=(H9+L9)/2). H9=94.94, L9=92.69 -> basis9=93.815.
    # atr10[9] seed = sum(TR[0..9])/10 = 26.28/10 = 2.628.
    # upper_basic9 = 93.815 + 3*2.628 = 101.699
    # lower_basic9 = 93.815 - 3*2.628 = 85.931
    # close9=93.52 < basis9=93.815 -> direction=-1.0 (downtrend, pinned
    # convention), line[9] = upper_basic9 = 101.699.
    assert direction[9] == -1.0
    assert line[9] == pytest.approx(93.815 + 3.0 * (26.28 / 10), rel=1e-9)

    # First ratchet step, index 10: H10=94.45, L10=93.88 ->
    # basis10=94.165. atr10[10] = (atr10[9]*9 + TR10)/10, TR10=0.93 ->
    # (2.628*9 + 0.93)/10 = 2.4582. upper_basic10 = 94.165+3*2.4582 =
    # 101.5396. Ratchet: upper_basic10 (101.5396) < final_upper9 (101.699)
    # -> final_upper10 = 101.5396 (tightens). close9=93.52 is not >
    # final_upper9=101.699, so direction stays -1.0; line[10] =
    # final_upper10 = 101.5396.
    assert direction[10] == -1.0
    assert line[10] == pytest.approx(101.5396, rel=1e-9)


def test_supertrend_initial_direction_pinned_convention() -> None:
    """Pinned in its own test (addendum: 'initial direction pinned by
    golden vector + docstring' — there is no prior bar to run the flip
    rule against at the first valid index)."""
    g = _load("supertrend")
    line, direction = supertrend(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=10, mult=3.0
    )
    for i in range(9):
        assert line[i] is None and direction[i] is None
    assert direction[9] in (1.0, -1.0)


def test_supertrend_short_series_all_none() -> None:
    g = _load("short_series")
    line, direction = supertrend(
        g["input"]["highs"], g["input"]["lows"], g["input"]["closes"], period=10, mult=3.0
    )
    assert all(v is None for v in line)
    assert all(v is None for v in direction)


def test_supertrend_properties_random_walk() -> None:
    highs, lows, closes = _random_walk()
    line, direction = supertrend(highs, lows, closes, period=10, mult=3.0)
    assert len(line) == len(direction) == len(closes)
    none_prefix = sum(1 for v in line if v is None)
    assert none_prefix == 9, "addendum lookback table: supertrend(10) first non-None = 9"
    for d in direction:
        if d is not None:
            assert d in (1.0, -1.0)
