"""Volume indicators (SPRINT P1B story 4): vwap, obv, volume_ratio.

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback are `None`, never zero-filled,
never a shorter array. Unlike every other module in `_indicators`, `vwap`
takes `Sequence[Bar]` directly (addendum: "Only `vwap` takes `Sequence[Bar]`")
— Decimal->float conversion happens INSIDE `vwap`, because this is the
analysis-layer boundary (DESIGN §13): bars carry Decimal prices parsed from
venue strings (TD-17), but every indicator downstream of this module
operates on floats. `obv` and `volume_ratio` take plain `Sequence[float]`
closes/volumes, matching every other indicator's scalar-input contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC

from tradekit.contracts import Bar
from tradekit.mae._indicators.trend import sma as _sma


def vwap(bars: Sequence[Bar]) -> list[float | None]:
    """Volume-Weighted Average Price, session-anchored, aligned 1:1 with
    `bars`.

    Per-bar typical price: tp[i] = (float(high[i]) + float(low[i]) +
    float(close[i])) / 3.0. Decimal->float conversion happens HERE, inside
    `vwap` — this is the analysis-layer boundary (DESIGN §13); every other
    indicator in this package already operates on plain floats, but `vwap`
    is the one function that receives `Bar` objects directly and therefore
    owns the Decimal->float crossing.

    Session = the UTC calendar day of `ts_open` (i.e. `ts_open.date()` after
    normalizing to UTC). vwap[i] = cumulative(tp*volume) / cumulative(volume)
    over all bars in the SAME session up to and including index i; the
    running sums reset to zero at every UTC-day boundary (the first bar of a
    new UTC day starts a fresh accumulation, independent of any prior day).

    Why a UTC-day reset also serves US-equity RTH sessions, not just crypto:
    the addendum requires documenting this explicitly. US equity regular
    trading hours (09:30-16:00 America/New_York) map to 13:30-20:00 UTC (or
    14:30-21:00 UTC during DST) on a SINGLE UTC calendar date — the RTH
    session never straddles UTC midnight (UTC midnight falls at 19:00 or
    20:00 America/New_York, hours after the 16:00 close). So resetting VWAP
    at the UTC day boundary happens to coincide with "no bars in the RTH
    session yet" for equities too, even though the reset instant itself
    (00:00 UTC) is well outside RTH. This is a convenient coincidence of the
    US equity calendar, not a general claim that UTC-day resets equal
    exchange-session resets everywhere (a market with a session crossing UTC
    midnight would need a different anchor); crypto trades 24/7 so "UTC
    calendar day" is simply the natural, unambiguous session definition
    there.

    Zero-volume rule: if the cumulative volume within the current session
    (from the session's first bar through index i) is 0.0, vwap[i] is
    `None` — never a division by zero, never a 0.0 placeholder. This can
    happen at the very start of a session (e.g. a session-opening bar with
    volume=0) and the None propagates until the first bar with nonzero
    volume in that session.

    Lookback: first non-None index = 0 (addendum lookback table) UNLESS the
    first bar's own volume is 0 (see the zero-volume rule above), in which
    case None persists until cumulative volume in that session becomes
    nonzero.
    """
    n = len(bars)
    out: list[float | None] = [None] * n
    cum_tv = 0.0
    cum_v = 0.0
    session_day = None
    for i, bar in enumerate(bars):
        day = bar.ts_open.astimezone(UTC).date()
        if day != session_day:
            session_day = day
            cum_tv = 0.0
            cum_v = 0.0
        tp = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
        vol = float(bar.volume)
        cum_tv += tp * vol
        cum_v += vol
        out[i] = (cum_tv / cum_v) if cum_v != 0.0 else None
    return out


def obv(closes: Sequence[float], volumes: Sequence[float]) -> list[float | None]:
    """On-Balance Volume, aligned 1:1 with input.

    obv[0] = 0.0 (pinned convention — addendum: "obv[0] = 0.0"; there is no
    prior close to compare against, so the running total starts at zero
    rather than None).

    For i >= 1: obv[i] = obv[i-1] + volume[i] if close[i] > close[i-1];
    obv[i] = obv[i-1] - volume[i] if close[i] < close[i-1]; obv[i] =
    obv[i-1] (unchanged) if close[i] == close[i-1].

    Lookback: first non-None index = 0 (addendum lookback table) — obv is
    NEVER None, unlike every lookback-bound indicator elsewhere in this
    package; it is a running total defined from the first bar.
    """
    n = len(closes)
    out: list[float | None] = [0.0] * n
    prev = 0.0
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            prev = prev + volumes[i]
        elif closes[i] < closes[i - 1]:
            prev = prev - volumes[i]
        out[i] = prev
    return out


def volume_ratio(volumes: Sequence[float], period: int = 20) -> list[float | None]:
    """Volume Ratio: volume_ratio[i] = volume[i] / SMA(period)(volumes)[i],
    where SMA(period) is the trailing `period`-bar simple moving average of
    volume (see `trend.sma`).

    Zero-SMA pin (addendum: "Pin the zero-SMA case"): if the trailing
    volume SMA at index i is exactly 0.0 (i.e. every volume value in the
    trailing `period`-bar window is 0.0), volume_ratio[i] is `None` — NOT a
    division-by-zero crash and NOT an inf/NaN placeholder. This is
    independent of the ordinary lookback prefix below; it can also occur
    mid-series if a `period`-bar window happens to be all zero-volume bars.

    Lookback: first non-None index = period-1 (19 for the default
    period=20 — addendum lookback table), subject to the zero-SMA
    override above.
    """
    n = len(volumes)
    out: list[float | None] = [None] * n
    sma_vals = _sma(volumes, period)
    for i in range(n):
        s = sma_vals[i]
        if s is None or s == 0.0:
            continue
        out[i] = volumes[i] / s
    return out
