"""tests/unit/mae_indicators/test_momentum.py — SPRINT P1B story 2: rsi,
macd, stoch_rsi, roc (tradekit.mae._indicators.momentum).

TEST-PATH EXCEPTION (tests/ASSUMPTIONS.md, extends entry 23/29): this
module imports `tradekit.mae._indicators.momentum` directly — no public
verb wires `_indicators` in yet (P1C+).

Golden vectors come from the same independent, from-spec reference
implementation as test_volatility.py — see that module's docstring and
scratchpad `gen_golden.py` for full provenance. SERIES_A (same 45-bar
series used by test_volatility.py / test_trend.py) is reused here for its
`closes` only.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from tradekit.mae._indicators.momentum import macd, roc, rsi, stoch_rsi

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


def _random_walk_closes(n: int = 120, seed: int = 42) -> list[float]:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(max(1.0, closes[-1] + rng.uniform(-2.5, 2.5)))
    return closes


# ---------------------------------------------------------------------------
# rsi
# ---------------------------------------------------------------------------


def test_rsi_golden_vector() -> None:
    g = _load("rsi")
    out = rsi(g["input"]["closes"], period=14)
    _assert_aligned(out, g["expected"]["rsi"])

    # Seed boundary, index period=14 (RSI needs `period` DIFFS, i.e.
    # period+1 prices, so the seed lands at index 14 not 13). Closes[0:15]
    # (2dp): 100.00, 98.10, 95.96, 96.46, 98.91, 97.50, 98.98, 97.69,
    # 95.36, 93.52, 94.22, 95.94, 94.17, 95.93, 96.47.
    # diffs 1..14: -1.90,-2.14,+0.50,+2.45,-1.41,+1.48,-1.29,-2.33,-1.84,
    #              +0.70,+1.72,-1.77,+1.76,+0.54
    # gains sum = 0.50+2.45+1.48+0.70+1.72+1.76+0.54 = 9.15 -> avg_gain=0.653571...
    # losses sum = 1.90+2.14+1.41+1.29+2.33+1.84+1.77 = 12.68 -> avg_loss=0.905714...
    # RS = 0.653571/0.905714 = 0.721609...; RSI = 100 - 100/(1+RS) = 41.9148
    avg_gain14 = 9.15 / 14
    avg_loss14 = 12.68 / 14
    rs14 = avg_gain14 / avg_loss14
    assert out[14] == pytest.approx(100.0 - 100.0 / (1.0 + rs14), rel=1e-9)

    # index period+1=15 (first Wilder recurrence step): diff = C15-C14 =
    # 97.03-96.47 = +0.56 -> gain15=0.56, loss15=0.0.
    # avg_gain15 = (avg_gain14*13 + 0.56)/14; avg_loss15 = (avg_loss14*13 + 0)/14
    avg_gain15 = (avg_gain14 * 13 + 0.56) / 14
    avg_loss15 = (avg_loss14 * 13 + 0.0) / 14
    rs15 = avg_gain15 / avg_loss15
    assert out[15] == pytest.approx(100.0 - 100.0 / (1.0 + rs15), rel=1e-9)


def test_rsi_constant_price_pinned_to_100() -> None:
    """Pinned convention (addendum): avg_loss == 0 -> RSI = 100.0 exactly,
    covering the constant-price case where RS would otherwise be 0/0 (NaN)
    rather than the naive "RS -> infinity" interpretation.

    Hand check: 20 bars all C=100.0 -> every diff is 0.0 -> avg_gain=0.0,
    avg_loss=0.0 -> avg_loss==0 branch -> RSI=100.0, not undefined.
    """
    g = _load("constant_price")
    out = rsi(g["input"]["closes"], period=14)
    _assert_aligned(out, g["expected"]["rsi"])
    assert out[14] == 100.0
    assert out[19] == 100.0


def test_rsi_short_series_all_none() -> None:
    g = _load("short_series")
    out = rsi(g["input"]["closes"], period=14)
    assert len(out) == len(g["input"]["closes"])
    assert all(v is None for v in out)


def test_rsi_bounded_0_100_property() -> None:
    closes = _random_walk_closes()
    out = rsi(closes, period=14)
    assert len(out) == len(closes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 14, "addendum lookback table: rsi(14) first non-None = 14"
    for v in out:
        if v is not None:
            assert 0.0 <= v <= 100.0


# ---------------------------------------------------------------------------
# macd
# ---------------------------------------------------------------------------


def test_macd_golden_vector() -> None:
    g = _load("macd")
    m, s, h = macd(g["input"]["closes"], fast=12, slow=26, signal=9)
    _assert_aligned(m, g["expected"]["macd"])
    _assert_aligned(s, g["expected"]["signal"])
    _assert_aligned(h, g["expected"]["histogram"])

    # macd_line seed boundary, index slow-1=25 (EMA(26) is the binding
    # constraint): macd[25] = ema12[25] - ema26[25]
    #   = 96.78068970332222 - 96.62923076923077 = 0.15145893409145...
    assert m[25] == pytest.approx(96.78068970332222 - 96.62923076923077, rel=1e-9)

    # signal seed boundary, index (slow-1)+signal=33: signal[33] = SMA(9)
    # of macd_line[25..33] (its own SMA-of-first-9 seed, same convention
    # as every other EMA in this package). The 9 macd_line values (6dp):
    # 0.151459, 0.178475, 0.382679, 0.346854, 0.176030, 0.198136,
    # 0.079180, 0.125478, 0.151546 -- sum ~= 1.789837, /9 ~= 0.198871.
    assert s[33] == pytest.approx(0.198871, abs=5e-6)

    # histogram sign convention at the same index: hist = macd - signal
    # (NOT signal - macd) ~= 0.151546 - 0.198871 ~= -0.047325.
    assert h[33] == pytest.approx(m[33] - s[33], rel=1e-9)
    assert h[33] == pytest.approx(-0.047325, abs=5e-6)


def test_macd_histogram_sign_convention_is_macd_minus_signal() -> None:
    """Pinned in its own test (sprint doc: 'both conventions exist in the
    wild' — histogram = macd_line - signal_line, never the reverse)."""
    g = _load("macd")
    m, s, h = macd(g["input"]["closes"], fast=12, slow=26, signal=9)
    for mi, si, hi in zip(m, s, h, strict=True):
        if mi is not None and si is not None:
            assert hi == pytest.approx(mi - si, rel=1e-9, abs=1e-12)


def test_macd_constant_price_collapses_to_zero() -> None:
    """Both EMAs seed to the same constant once warmed up, so macd_line,
    signal, and histogram all collapse to 0.0."""
    g = _load("constant_price")
    m, s, h = macd(g["input"]["closes"], fast=12, slow=26, signal=9)
    _assert_aligned(m, g["expected"]["macd"])
    _assert_aligned(s, g["expected"]["macd_signal"])
    _assert_aligned(h, g["expected"]["macd_hist"])


def test_macd_short_series_all_none() -> None:
    g = _load("short_series")
    m, s, h = macd(g["input"]["closes"], fast=12, slow=26, signal=9)
    assert all(v is None for v in m)
    assert all(v is None for v in s)
    assert all(v is None for v in h)


def test_macd_properties_random_walk() -> None:
    closes = _random_walk_closes()
    m, s, h = macd(closes, fast=12, slow=26, signal=9)
    assert len(m) == len(s) == len(h) == len(closes)
    macd_none_prefix = sum(1 for v in m if v is None)
    assert macd_none_prefix == 25, "addendum lookback table: macd line first non-None = 25"
    signal_none_prefix = sum(1 for v in s if v is None)
    assert signal_none_prefix == 33, "addendum lookback table: macd signal first non-None = 33"
    for mi, si, hi in zip(m, s, h, strict=True):
        if mi is not None and si is not None:
            assert hi == pytest.approx(mi - si, rel=1e-9, abs=1e-12)


# ---------------------------------------------------------------------------
# stoch_rsi
# ---------------------------------------------------------------------------


def test_stoch_rsi_golden_vector() -> None:
    g = _load("stoch_rsi")
    raw, k, d = stoch_rsi(g["input"]["closes"], rsi_period=14, stoch_period=14, k=3, d=3)
    _assert_aligned(raw, g["expected"]["raw"])
    _assert_aligned(k, g["expected"]["k"])
    _assert_aligned(d, g["expected"]["d"])

    # raw seed boundary, index 27 (= rsi's own first non-None 14, plus
    # stoch_period-1=13): the trailing 14-RSI window ending at 27 has
    # rsi[27]=53.86249... as its OWN maximum (min=37.98790... at index
    # 20), so raw[27] = (rsi[27]-min)/(max-min)*100 = (max-min)/(max-min)
    # * 100 = 100.0 exactly.
    assert raw[27] == 100.0

    # k seed boundary, index raw_first+k-1=29: k[29] = mean(raw[27],
    # raw[28], raw[29]) = mean(100.0, 61.907357, 37.632643) ~= 66.513333.
    assert k[29] == pytest.approx(66.513333, abs=5e-6)

    # d seed boundary, index k_first+d-1=31: d[31] = mean(k[29], k[30],
    # k[31]) = mean(66.513333, 56.300785, 50.976766) ~= 57.930295.
    assert d[31] == pytest.approx(57.930295, abs=5e-6)


def test_stoch_rsi_max_equals_min_pinned_to_zero() -> None:
    """Pinned convention (addendum): a flat RSI window (max==min) yields
    raw=0.0, never a ZeroDivisionError/NaN. Constant price drives RSI to a
    flat 100.0 plateau after the seed, so every raw is 0.0 there."""
    g = _load("constant_price")
    raw, k, d = stoch_rsi(g["input"]["closes"], rsi_period=14, stoch_period=14, k=3, d=3)
    _assert_aligned(raw, g["expected"]["stoch_rsi_raw"])
    _assert_aligned(k, g["expected"]["stoch_rsi_k"])
    _assert_aligned(d, g["expected"]["stoch_rsi_d"])


def test_stoch_rsi_short_series_all_none() -> None:
    g = _load("short_series")
    raw, k, d = stoch_rsi(g["input"]["closes"], rsi_period=14, stoch_period=14, k=3, d=3)
    assert all(v is None for v in raw)
    assert all(v is None for v in k)
    assert all(v is None for v in d)


def test_stoch_rsi_properties_random_walk() -> None:
    closes = _random_walk_closes()
    raw, k, d = stoch_rsi(closes, rsi_period=14, stoch_period=14, k=3, d=3)
    assert len(raw) == len(k) == len(d) == len(closes)
    raw_none_prefix = sum(1 for v in raw if v is None)
    assert raw_none_prefix == 27, "addendum lookback table: stoch_rsi raw first non-None = 27"
    k_none_prefix = sum(1 for v in k if v is None)
    assert k_none_prefix == 29, "addendum lookback table: stoch_rsi k first non-None = 29"
    d_none_prefix = sum(1 for v in d if v is None)
    assert d_none_prefix == 31, "addendum lookback table: stoch_rsi d first non-None = 31"
    for v in raw:
        if v is not None:
            assert 0.0 <= v <= 100.0


# ---------------------------------------------------------------------------
# roc
# ---------------------------------------------------------------------------


def test_roc_golden_vector() -> None:
    g = _load("roc")
    out = roc(g["input"]["closes"], period=10)
    _assert_aligned(out, g["expected"]["roc"])

    # Lookback boundary, index period=10: roc[10] = (C10/C0 - 1)*100 =
    # (94.22/100.00 - 1)*100 = -5.78 exactly.
    assert out[10] == pytest.approx(-5.78, rel=1e-9)

    # index period+1=11: roc[11] = (C11/C1 - 1)*100 = (95.94/98.10 - 1)*100
    #  ~= -2.201835.
    assert out[11] == pytest.approx((95.94 / 98.10 - 1.0) * 100.0, rel=1e-9)

    # None right before the boundary (index period-1=9): only 9 prior
    # closes exist, one short of the required period=10 lookback.
    assert out[9] is None


def test_roc_short_series_all_none() -> None:
    g = _load("short_series")
    out = roc(g["input"]["closes"], period=10)
    assert len(out) == len(g["input"]["closes"])
    assert all(v is None for v in out)


def test_roc_constant_price_zero() -> None:
    g = _load("constant_price")
    out = roc(g["input"]["closes"], period=10)
    _assert_aligned(out, g["expected"]["roc"])
    assert out[15] == pytest.approx(0.0, abs=1e-9)


def test_roc_properties_random_walk() -> None:
    closes = _random_walk_closes()
    out = roc(closes, period=10)
    assert len(out) == len(closes)
    none_prefix = sum(1 for v in out if v is None)
    assert none_prefix == 10, "addendum lookback table: roc(10) first non-None = 10"
