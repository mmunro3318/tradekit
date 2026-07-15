"""Trend indicators (SPRINT P1B story 3): sma, ema, adx, supertrend. Pure
functions over `Sequence[float]` values/closes/highs/lows.

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback are `None`, never zero-filled,
never a shorter array. `adx` uses Wilder smoothing throughout (canon
recurrence: first value = simple average of first `period` inputs, then
`w_t = (w_{t-1}*(period-1) + x_t)/period`) for +DM, -DM, TR, AND for the
final DX->ADX smoothing stage.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple, cast

import numpy as np

from tradekit.mae._indicators.volatility import atr as _atr
from tradekit.mae._indicators.volatility import true_range as _true_range


class Adx(NamedTuple):
    """(plus_di, minus_di, adx) — all `list[float | None]`, aligned to
    input."""

    plus_di: list[float | None]
    minus_di: list[float | None]
    adx: list[float | None]


class Supertrend(NamedTuple):
    """(line, direction) — both `list[float | None]`, aligned to input.
    direction values are drawn from {1.0, -1.0, None} — 1.0 = uptrend
    (line tracks the ratcheting lower band), -1.0 = downtrend (line tracks
    the ratcheting upper band), None wherever ATR isn't warmed up yet."""

    line: list[float | None]
    direction: list[float | None]


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Simple moving average, aligned 1:1 with input. sma[i] = mean of
    values[i-period+1 : i+1].

    Lookback: first non-None index = period-1 (addendum lookback table).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    n = len(values)
    out: list[float | None] = [None] * n
    if n < period:
        return out
    arr = np.asarray(values, dtype=np.float64)
    for i in range(period - 1, n):
        out[i] = float(arr[i - period + 1 : i + 1].mean())
    return out


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Exponential moving average, aligned 1:1 with input.

    Seed: ema[period-1] = simple average of values[0:period] (SMA of the
    first `period` values — this is the pinned convention EVERYWHERE ema
    is used in this package, including internally by `momentum.macd` and
    `volatility.keltner`; it does NOT match pandas'/pandas_ta's
    `adjust=False`, which seeds from values[0] alone and gives materially
    different early values). Recurrence for i >= period:
    ema[i] = values[i] * k + ema[i-1] * (1-k), where k = 2/(period+1).

    Lookback: first non-None index = period-1 (addendum lookback table).
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


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Adx:
    """Average Directional Index, Wilder throughout.

    +DM[i]/-DM[i] (i >= 1; index 0 has no prior bar and is excluded from
    every downstream sum): let up = high[i]-high[i-1], dn = low[i-1]-low[i].
    +DM[i] = up if (up > dn and up > 0) else 0.0; -DM[i] = dn if (dn > up
    and dn > 0) else 0.0 (never both nonzero on the same bar).

    +DM, -DM, and true_range (see `volatility.true_range`) are each
    Wilder-smoothed starting from index 1 (the seed averages the 14 values
    at indices 1..period, landing the seed at index `period` — one bar
    later than a standalone `atr()` call, because that seed window
    deliberately excludes index 0 to stay aligned with +DM/-DM, which
    cannot exist at index 0).

    +DI[i] = 100 * smoothed(+DM)[i] / smoothed(TR)[i]; -DI[i] likewise
    with smoothed(-DM). DX[i] = 100 * |+DI[i] - -DI[i]| / (+DI[i] +
    -DI[i]) (0.0 if both DI are zero). adx[i] = Wilder smoothing of DX,
    seeded as the simple average of the first `period` DX values.

    Lookback (default period=14, per the addendum table): plus_di/minus_di
    first non-None index = 14; adx first non-None index = 27
    (= 2*period - 1, since the DX series itself only starts at index 14
    and needs another `period` values to seed its own Wilder average).
    """
    n = len(highs)
    plus_di: list[float | None] = [None] * n
    minus_di: list[float | None] = [None] * n
    adx_line: list[float | None] = [None] * n
    if n <= period:
        return Adx(plus_di, minus_di, adx_line)

    tr = cast(list[float], _true_range(highs, lows, closes))  # TR never None
    plus_dm_raw = [0.0] * n
    minus_dm_raw = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm_raw[i] = up if (up > dn and up > 0.0) else 0.0
        minus_dm_raw[i] = dn if (dn > up and dn > 0.0) else 0.0

    # Wilder-smoothed +DM/-DM/TR, seeded as the MEAN over indices 1..period
    # (14 values), landing the seed at index `period` (one bar later than a
    # standalone atr() call). The seed must be the average, not the sum: the
    # recurrence below is the average-form (w*(period-1) + x)/period, and a
    # sum-form seed would underweight each new observation by `period`
    # (invisible at the seed index itself, since a ratio of sums equals a
    # ratio of averages, but divergent from index period+1 on).
    smoothed_plus_dm = sum(plus_dm_raw[1 : period + 1]) / period
    smoothed_minus_dm = sum(minus_dm_raw[1 : period + 1]) / period
    smoothed_tr = sum(tr[1 : period + 1]) / period

    dx: list[float | None] = [None] * n

    def _di_and_dx(i: int, sp_dm: float, sm_dm: float, s_tr: float) -> tuple[float, float, float]:
        if s_tr == 0.0:
            pd, md = 0.0, 0.0
        else:
            pd = 100.0 * sp_dm / s_tr
            md = 100.0 * sm_dm / s_tr
        total = pd + md
        dxv = 0.0 if total == 0.0 else 100.0 * abs(pd - md) / total
        return pd, md, dxv

    pd, md, dxv = _di_and_dx(period, smoothed_plus_dm, smoothed_minus_dm, smoothed_tr)
    plus_di[period] = pd
    minus_di[period] = md
    dx[period] = dxv

    for i in range(period + 1, n):
        smoothed_plus_dm = (smoothed_plus_dm * (period - 1) + plus_dm_raw[i]) / period
        smoothed_minus_dm = (smoothed_minus_dm * (period - 1) + minus_dm_raw[i]) / period
        smoothed_tr = (smoothed_tr * (period - 1) + tr[i]) / period
        pd, md, dxv = _di_and_dx(i, smoothed_plus_dm, smoothed_minus_dm, smoothed_tr)
        plus_di[i] = pd
        minus_di[i] = md
        dx[i] = dxv

    # adx = Wilder smoothing of DX, seeded as the simple average of the
    # first `period` DX values (indices period .. 2*period-1).
    seed_end = 2 * period - 1
    if seed_end < n:
        dx_window = cast(list[float], dx[period : 2 * period])  # non-None in this window
        prev = sum(dx_window) / period
        adx_line[seed_end] = prev
        for i in range(seed_end + 1, n):
            dxi = cast(float, dx[i])  # non-None: dx is contiguous from `period` onward
            prev = (prev * (period - 1) + dxi) / period
            adx_line[i] = prev

    return Adx(plus_di, minus_di, adx_line)


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 10,
    mult: float = 3.0,
) -> Supertrend:
    """Supertrend: basis[i] = (high[i]+low[i])/2; upper_basic[i] =
    basis[i] + mult*ATR(period)[i]; lower_basic[i] = basis[i] -
    mult*ATR(period)[i] (see `volatility.atr` for the Wilder seeding
    convention).

    Ratcheting final bands (standard Supertrend recurrence, i > first
    valid index): final_upper[i] = upper_basic[i] if (upper_basic[i] <
    final_upper[i-1] or close[i-1] > final_upper[i-1]) else
    final_upper[i-1]; final_lower[i] = lower_basic[i] if (lower_basic[i] >
    final_lower[i-1] or close[i-1] < final_lower[i-1]) else
    final_lower[i-1].

    Direction flip rule: if direction[i-1] == 1.0 (uptrend), flip to -1.0
    only when close[i] < final_lower[i]; if direction[i-1] == -1.0
    (downtrend), flip to 1.0 only when close[i] > final_upper[i].
    line[i] = final_lower[i] when direction[i] == 1.0, else
    final_upper[i].

    INITIAL DIRECTION (CTO-pinned convention, addendum: "initial direction
    pinned by golden vector + docstring" — there is no prior bar to apply
    the flip rule to at the first valid index): at the first index where
    ATR(period) is non-None, direction = 1.0 (uptrend, line =
    lower_basic) if close[i] >= basis[i], else -1.0 (downtrend, line =
    upper_basic); a tie (close == basis) resolves to uptrend.

    Lookback: first non-None index = period-1 (9 for the default
    period=10 — addendum lookback table, matching ATR(period)'s own first
    non-None index).
    """
    n = len(highs)
    line: list[float | None] = [None] * n
    direction: list[float | None] = [None] * n
    atr_vals = _atr(highs, lows, closes, period=period)

    first = period - 1
    if first >= n or atr_vals[first] is None:
        return Supertrend(line, direction)

    basis0 = (highs[first] + lows[first]) / 2.0
    a0 = atr_vals[first]
    assert a0 is not None
    final_upper = basis0 + mult * a0
    final_lower = basis0 - mult * a0
    dir_prev = 1.0 if closes[first] >= basis0 else -1.0
    direction[first] = dir_prev
    line[first] = final_lower if dir_prev == 1.0 else final_upper

    for i in range(first + 1, n):
        a = atr_vals[i]
        assert a is not None  # atr is non-None for all i >= period-1
        basis = (highs[i] + lows[i]) / 2.0
        upper_basic = basis + mult * a
        lower_basic = basis - mult * a

        if upper_basic < final_upper or closes[i - 1] > final_upper:
            final_upper = upper_basic
        # else final_upper unchanged (ratchet holds)

        if lower_basic > final_lower or closes[i - 1] < final_lower:
            final_lower = lower_basic
        # else final_lower unchanged (ratchet holds)

        if dir_prev == 1.0:
            dir_cur = -1.0 if closes[i] < final_lower else 1.0
        else:
            dir_cur = 1.0 if closes[i] > final_upper else -1.0

        direction[i] = dir_cur
        line[i] = final_lower if dir_cur == 1.0 else final_upper
        dir_prev = dir_cur

    return Supertrend(line, direction)
