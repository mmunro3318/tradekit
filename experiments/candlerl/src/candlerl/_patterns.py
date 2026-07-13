"""Rule-based candlestick pattern detectors (vectorized numpy).

Thresholds follow TA-Lib's CandleSettings (verified against ta_global.c):
body sizes are measured against the trailing-10 average body, shadows against
the trailing-10 average range. Trend context (which TA-Lib omits but the
classical definitions require) is proxied by net price change over the
previous TREND_LOOKBACK closes, measured at the pattern's first candle.

A pattern is flagged at the index of its completing candle.
"""
from __future__ import annotations

import numpy as np

PATTERN_NAMES = [
    "doji",
    "hammer",
    "inverted_hammer",
    "hanging_man",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
]

TREND_LOOKBACK = 5
_AVG_PERIOD = 10
_PENETRATION = 0.3  # morning/evening star: candle3 must close this far into candle1's body


def _prior_mean(x: np.ndarray, period: int) -> np.ndarray:
    """Mean of up to `period` values strictly before index i; NaN at i=0."""
    n = len(x)
    out = np.full(n, np.nan)
    cs = np.concatenate([[0.0], np.cumsum(x)])
    for i in range(1, n):
        lo = max(0, i - period)
        out[i] = (cs[i] - cs[lo]) / (i - lo)
    return out


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    """x shifted forward by k, NaN-padded (float output; NaN compares False)."""
    out = np.full(len(x), np.nan)
    if k == 0:
        return x.astype(float)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def _shift_b(x: np.ndarray, k: int) -> np.ndarray:
    """Boolean shift: padded positions are False."""
    return _shift(x.astype(float), k) == 1.0


def detect_patterns(
    open_: np.ndarray, high: np.ndarray, low: np.ndarray, close: np.ndarray
) -> dict[str, np.ndarray]:
    o = np.asarray(open_, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)

    body = np.abs(c - o)
    rng = h - l
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    bullish = c > o
    bearish = c < o
    body_hi = np.maximum(o, c)
    body_lo = np.minimum(o, c)

    avg_body = _prior_mean(body, _AVG_PERIOD)
    avg_rng = _prior_mean(rng, _AVG_PERIOD)
    tiny_shadow = 0.1 * avg_rng

    # Trend at index j: net change over TREND_LOOKBACK closes ending at j-1.
    down_at = _shift(c, 1) < _shift(c, 1 + TREND_LOOKBACK)
    up_at = _shift(c, 1) > _shift(c, 1 + TREND_LOOKBACK)

    with np.errstate(invalid="ignore"):
        valid = rng > 0
        small_body = body <= avg_body

        doji = valid & (body <= 0.1 * rng)

        hammer_shape = valid & small_body & (lower >= 2 * body) & (upper <= tiny_shadow)
        hammer = hammer_shape & down_at
        hanging_man = hammer_shape & up_at

        inv_shape = valid & small_body & (upper >= 2 * body) & (lower <= tiny_shadow)
        inverted_hammer = inv_shape & down_at
        shooting_star = inv_shape & up_at

        bull_engulf = (
            _shift_b(bearish, 1)
            & bullish
            & (o <= _shift(c, 1))
            & (c >= _shift(o, 1))
            & (body > _shift(body, 1))
            & down_at
        )
        bear_engulf = (
            _shift_b(bullish, 1)
            & bearish
            & (o >= _shift(c, 1))
            & (c <= _shift(o, 1))
            & (body > _shift(body, 1))
            & up_at
        )

        # Morning/evening star: c1 two bars back, c2 one bar back, c3 current.
        c1_long_bear = _shift_b(bearish, 2) & (_shift(body, 2) >= _shift(avg_body, 2))
        c1_long_bull = _shift_b(bullish, 2) & (_shift(body, 2) >= _shift(avg_body, 2))
        c2_small = _shift(body, 1) <= _shift(avg_body, 1)
        c2_gap_down = _shift(body_hi, 1) < _shift(body_lo, 2)
        c2_gap_up = _shift(body_lo, 1) > _shift(body_hi, 2)

        morning_star = (
            c1_long_bear
            & c2_small
            & c2_gap_down
            & bullish
            & (body >= 0.5 * avg_body)
            & (c > _shift(c, 2) + _PENETRATION * _shift(body, 2))
            & _shift_b(down_at, 2)
        )
        evening_star = (
            c1_long_bull
            & c2_small
            & c2_gap_up
            & bearish
            & (body >= 0.5 * avg_body)
            & (c < _shift(c, 2) - _PENETRATION * _shift(body, 2))
            & _shift_b(up_at, 2)
        )

        def _soldier(k: int) -> np.ndarray:
            """Candle k bars back: long white candle with a short upper shadow."""
            return (
                _shift_b(bullish, k)
                & (_shift(body, k) >= 0.6 * _shift(avg_body, k))
                & (_shift(upper, k) <= np.maximum(0.3 * _shift(body, k), _shift(tiny_shadow, k)))
            )

        def _crow(k: int) -> np.ndarray:
            return (
                _shift_b(bearish, k)
                & (_shift(body, k) >= 0.6 * _shift(avg_body, k))
                & (_shift(lower, k) <= np.maximum(0.3 * _shift(body, k), _shift(tiny_shadow, k)))
            )

        soldiers = (
            _soldier(2)
            & _soldier(1)
            & _soldier(0)
            & (_shift(o, 1) >= _shift(o, 2)) & (_shift(o, 1) <= _shift(c, 2))
            & (o >= _shift(o, 1)) & (o <= _shift(c, 1))
            & (_shift(c, 1) > _shift(c, 2)) & (c > _shift(c, 1))
        )
        crows = (
            _crow(2)
            & _crow(1)
            & _crow(0)
            & (_shift(o, 1) <= _shift(o, 2)) & (_shift(o, 1) >= _shift(c, 2))
            & (o <= _shift(o, 1)) & (o >= _shift(c, 1))
            & (_shift(c, 1) < _shift(c, 2)) & (c < _shift(c, 1))
        )

    return {
        "doji": doji,
        "hammer": hammer,
        "inverted_hammer": inverted_hammer,
        "hanging_man": hanging_man,
        "shooting_star": shooting_star,
        "bullish_engulfing": bull_engulf,
        "bearish_engulfing": bear_engulf,
        "morning_star": morning_star,
        "evening_star": evening_star,
        "three_white_soldiers": soldiers,
        "three_black_crows": crows,
    }


def pattern_matrix(open_, high, low, close) -> np.ndarray:
    """(N, len(PATTERN_NAMES)) float32 matrix of pattern flags."""
    d = detect_patterns(open_, high, low, close)
    return np.stack([d[name] for name in PATTERN_NAMES], axis=1).astype(np.float32)
