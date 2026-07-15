"""Volatility indicators (SPRINT P1B story 1): true_range, atr, bollinger,
keltner. Pure functions over `Sequence[float]` closes/highs/lows — no
Bar/BarSeries coupling.

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback are `None`, never zero-filled,
never a shorter array. Wilder smoothing (`atr`) uses the canon recurrence:
first value = simple average of first `period` inputs, then
`w_t = (w_{t-1}*(period-1) + x_t)/period` — never EMA smoothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, cast

import numpy as np


class Bollinger(NamedTuple):
    """(mid, upper, lower) — all `list[float | None]`, aligned to input."""

    mid: list[float | None]
    upper: list[float | None]
    lower: list[float | None]


class Keltner(NamedTuple):
    """(mid, upper, lower) — all `list[float | None]`, aligned to input."""

    mid: list[float | None]
    upper: list[float | None]
    lower: list[float | None]


def true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float | None]:
    """True Range per bar, aligned 1:1 with input (length preserved).

    TR[0] = high[0] - low[0] — NEVER None (there is no previous close to
    gap against, so the plain high-low range is the only defined value).

    For i >= 1: TR[i] = max(high[i]-low[i], |high[i]-close[i-1]|,
    |low[i]-close[i-1]|). The two absolute-difference branches are what
    catch gap bars (e.g. a gap-down bar where high[i] < close[i-1] makes
    |low[i]-close[i-1]| the dominant term, not high[i]-low[i]).

    Lookback: first non-None index = 0 (see addendum lookback table).
    """
    n = len(highs)
    out: list[float | None] = [None] * n
    if n == 0:
        return out
    out[0] = float(highs[0] - lows[0])
    for i in range(1, n):
        prev_close = closes[i - 1]
        out[i] = float(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return out


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Average True Range, Wilder smoothing, aligned 1:1 with input.

    Seed: atr[period-1] = simple average of true_range()[0:period] (the
    first `period` TR values, INCLUDING TR[0]). Recurrence for i >= period:
    atr[i] = (atr[i-1]*(period-1) + TR[i]) / period.

    Lookback: first non-None index = period-1 (13 for the default
    period=14 — addendum lookback table).
    """
    tr = cast(list[float], true_range(highs, lows, closes))  # TR never None
    n = len(tr)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def bollinger(closes: Sequence[float], period: int = 20, k: float = 2.0) -> Bollinger:
    """Bollinger Bands: mid = SMA(period) of close; upper/lower = mid +/- k
    times the POPULATION standard deviation (ddof=0, i.e. divide the sum of
    squared deviations by `period`, not `period-1`) of the same trailing
    window used for the SMA.

    All three outputs share one lookback: first non-None index = period-1
    (19 for the default period=20 — addendum lookback table). Before that,
    mid/upper/lower are all None at the same positions (no partial bands).
    """
    n = len(closes)
    mid: list[float | None] = [None] * n
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    if n < period:
        return Bollinger(mid, upper, lower)
    arr = np.asarray(closes, dtype=np.float64)
    for i in range(period - 1, n):
        window = arr[i - period + 1 : i + 1]
        m = float(window.mean())
        std = float(window.std(ddof=0))
        mid[i] = m
        upper[i] = m + k * std
        lower[i] = m - k * std
    return Bollinger(mid, upper, lower)


def _ema(values: Sequence[float], period: int) -> list[float | None]:
    """Private local EMA matching `trend.ema`'s seeding convention exactly
    (SMA of first `period` values). Duplicated here (rather than imported)
    to avoid a volatility<->trend import cycle: `trend.supertrend` depends
    on `volatility.atr`, so `volatility` cannot depend back on `trend`.
    """
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    k = 2.0 / (period + 1)
    for i in range(period, n):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def keltner(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    ema_period: int = 20,
    atr_period: int = 10,
    mult: float = 2.0,
) -> Keltner:
    """Keltner Channel: mid = EMA(ema_period) of close (see `trend.ema` for
    the seeding convention); upper/lower = mid +/- mult * ATR(atr_period)
    (see `atr` above for the Wilder seeding convention).

    A position is non-None only once BOTH the EMA and the ATR are
    non-None; with the defaults (ema_period=20 > atr_period=10) the EMA is
    always the binding constraint, so first non-None index = ema_period-1
    (19 for the defaults — addendum lookback table), even though ATR(10)
    alone would already be valid from index 9.
    """
    n = len(closes)
    mid = _ema(closes, ema_period)
    atr_vals = atr(highs, lows, closes, period=atr_period)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(n):
        m = mid[i]
        a = atr_vals[i]
        if m is not None and a is not None:
            upper[i] = m + mult * a
            lower[i] = m - mult * a
    return Keltner(mid, upper, lower)
