"""Momentum indicators (SPRINT P1B story 2): rsi, macd, stoch_rsi, roc. Pure
functions over `Sequence[float]` closes.

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback are `None`, never zero-filled,
never a shorter array. `rsi` uses Wilder smoothing (canon recurrence:
first value = simple average of first `period` gain/loss diffs, then
`w_t = (w_{t-1}*(period-1) + x_t)/period`); `macd`'s EMAs seed from the SMA
of their own first `period` — see `trend.ema` for that same convention.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

from tradekit.mae._indicators.trend import ema as _ema
from tradekit.mae._indicators.trend import sma as _sma


def _apply_on_suffix(
    series: list[float | None], fn: Callable[[list[float], int], list[float | None]], period: int
) -> list[float | None]:
    """Apply `fn` (an sma/ema-shaped smoother) to the contiguous non-None
    suffix of `series` and map the result back onto a full-length output
    aligned with `series`. Assumes `series` has no internal None gaps once
    its lookback prefix ends (true for every indicator suffix in this
    module: rsi/macd_line/stoch raw/k are all defined for every index once
    their own first non-None index is reached).
    """
    n = len(series)
    out: list[float | None] = [None] * n
    start = next((i for i, v in enumerate(series) if v is not None), None)
    if start is None:
        return out
    suffix: list[float] = [v for v in series[start:] if v is not None]
    smoothed = fn(suffix, period)
    for j, sv in enumerate(smoothed):
        if sv is not None:
            out[start + j] = sv
    return out


class Macd(NamedTuple):
    """(macd, signal, histogram) — all `list[float | None]`, aligned to
    input. histogram[i] = macd[i] - signal[i] wherever both are non-None
    (sign convention pinned by the sprint doc: MACD minus signal, not the
    reverse — both conventions exist in the wild)."""

    macd: list[float | None]
    signal: list[float | None]
    histogram: list[float | None]


class StochRsi(NamedTuple):
    """(raw, k, d) — all `list[float | None]`, aligned to input. raw is in
    [0, 100]; k = SMA(k) of raw; d = SMA(d) of k."""

    raw: list[float | None]
    k: list[float | None]
    d: list[float | None]


def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder RSI, aligned 1:1 with input.

    Per-bar diffs: diff[i] = closes[i] - closes[i-1] for i in 1..n-1;
    gain[i] = max(diff[i], 0), loss[i] = max(-diff[i], 0). Seed at index
    `period`: avg_gain = mean(gain[1:period+1]), avg_loss =
    mean(loss[1:period+1]) (the first `period` diffs). Recurrence for
    i > period: avg_gain[i] = (avg_gain[i-1]*(period-1) + gain[i]) /
    period, same shape for avg_loss.

    RS = avg_gain / avg_loss; RSI = 100 - 100/(1+RS) EXCEPT when
    avg_loss == 0, which is pinned to RSI = 100.0 directly (covers both a
    strictly-rising run and a fully constant price series — RS would
    otherwise diverge to infinity/NaN, which is never an acceptable
    output).

    Lookback: first non-None index = period (14 for the default
    period=14 — addendum lookback table; note this is `period`, not
    `period-1`, because RSI needs `period` DIFFS, i.e. `period+1` prices).
    """
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains[i] = max(diff, 0.0)
        losses[i] = max(-diff, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    out[period] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = 100.0 if avg_loss == 0.0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)

    return out


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> Macd:
    """MACD: macd_line = EMA(fast) - EMA(slow) of close (EMA seeding per
    `trend.ema`: SMA of first `period`). signal = EMA(signal) applied to
    the macd_line's own non-None suffix, itself seeded as the SMA of that
    suffix's first `signal` values. histogram = macd_line - signal.

    Lookback: macd_line first non-None index = slow-1 (25 for the default
    fast=12/slow=26, since EMA(26) is the binding constraint over
    EMA(12)); signal/histogram first non-None index = (slow-1) + signal
    (33 for the defaults: the signal EMA needs `signal` non-None macd_line
    values to seed its own SMA — addendum lookback table).
    """
    n = len(closes)
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    macd_line: list[float | None] = [None] * n
    for i in range(n):
        f = ema_fast[i]
        s = ema_slow[i]
        if f is not None and s is not None:
            macd_line[i] = f - s

    signal_line = _apply_on_suffix(macd_line, _ema, signal)
    histogram: list[float | None] = [None] * n

    for i in range(n):
        m = macd_line[i]
        s = signal_line[i]
        if m is not None and s is not None:
            histogram[i] = m - s

    return Macd(macd_line, signal_line, histogram)


def stoch_rsi(
    closes: Sequence[float],
    rsi_period: int = 14,
    stoch_period: int = 14,
    k: int = 3,
    d: int = 3,
) -> StochRsi:
    """Stochastic RSI: raw[i] = (rsi[i] - min(rsi window)) / (max(rsi
    window) - min(rsi window)) * 100, where the window is the trailing
    `stoch_period` RSI values (RSI computed with `rsi_period`, per `rsi`
    above). When the window's max equals its min (flat RSI), raw is
    pinned to 0.0 (never a division by zero / NaN).

    k[i] = SMA(k) of raw over the trailing `k` raw values; d[i] = SMA(d)
    of k over the trailing `d` k values.

    Lookback (defaults rsi_period=14, stoch_period=14, k=3, d=3, per the
    addendum table): raw first non-None index = 27 (rsi's own first
    non-None, 14, plus stoch_period-1); k first non-None index = 29 (27 +
    k-1); d first non-None index = 31 (29 + d-1).
    """
    n = len(closes)
    rsi_vals = rsi(closes, period=rsi_period)

    raw: list[float | None] = [None] * n
    for i in range(stoch_period - 1, n):
        window = rsi_vals[i - stoch_period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        wlist = [v for v in window if v is not None]
        mn = min(wlist)
        mx = max(wlist)
        cur = rsi_vals[i]
        assert cur is not None
        raw[i] = 0.0 if mx == mn else (cur - mn) / (mx - mn) * 100.0

    k_line = _apply_on_suffix(raw, _sma, k)
    d_line = _apply_on_suffix(k_line, _sma, d)

    return StochRsi(raw, k_line, d_line)


def roc(closes: Sequence[float], period: int = 10) -> list[float | None]:
    """Rate of Change: roc[i] = (closes[i]/closes[i-period] - 1) * 100.

    Lookback: first non-None index = period (10 for the default
    period=10 — addendum lookback table).
    """
    n = len(closes)
    out: list[float | None] = [None] * n
    for i in range(period, n):
        out[i] = (closes[i] / closes[i - period] - 1.0) * 100.0
    return out
