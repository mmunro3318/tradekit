"""Trend indicators (SPRINT P1B story 3): sma, ema, adx, supertrend. Pure
functions over `Sequence[float]` values/closes/highs/lows — no numpy here
(the dev agent adds it when implementing).

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback are `None`, never zero-filled,
never a shorter array. `adx` uses Wilder smoothing throughout (canon
recurrence: first value = simple average of first `period` inputs, then
`w_t = (w_{t-1}*(period-1) + x_t)/period`) for +DM, -DM, TR, AND for the
final DX->ADX smoothing stage.

STUBS ONLY: every function body raises `NotImplementedError`. A separate
dev agent implements the bodies against tests/golden/indicators/*.json.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError
