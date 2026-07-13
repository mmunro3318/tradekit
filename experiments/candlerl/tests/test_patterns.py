"""Rule-based candlestick pattern detectors — geometry fixtures with generous margins.

Each fixture builds explicit OHLC candles so a human can verify the pattern by eye.
Detectors flag a pattern at the index of its *completing* candle.
"""
import numpy as np
import pytest

from candlerl._patterns import PATTERN_NAMES, detect_patterns


def ohlc(candles):
    a = np.asarray(candles, dtype=float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3]


# Six declining bearish candles: closes 109 -> 104 (downtrend context).
DOWN = [(110.0 - i, 111.0 - i, 108.5 - i, 109.0 - i) for i in range(6)]
# Six rising bullish candles: closes 102 -> 107 (uptrend context).
UP = [(100.0 + i, 102.5 + i, 99.5 + i, 102.0 + i) for i in range(6)]
# A plain candle that should trigger nothing (body ~60% of range).
PLAIN = (104.0, 105.2, 103.6, 104.9)


def detect(candles):
    return detect_patterns(*ohlc(candles))


def test_returns_all_patterns_as_bool_arrays():
    out = detect(DOWN + [PLAIN])
    assert set(out.keys()) == set(PATTERN_NAMES)
    for name, arr in out.items():
        assert arr.dtype == np.bool_, name
        assert arr.shape == (7,), name


def test_short_series_does_not_crash_and_flags_nothing():
    out = detect([PLAIN, PLAIN])
    assert not any(arr.any() for arr in out.values())


def test_zero_range_candle_is_safe():
    flat = (100.0, 100.0, 100.0, 100.0)
    out = detect(DOWN + [flat])
    assert not out["doji"][-1]


def test_doji_tiny_body_wide_range():
    out = detect(DOWN + [(100.0, 101.0, 99.0, 100.05)])
    assert out["doji"][-1]


def test_plain_candle_is_not_doji():
    out = detect(DOWN + [PLAIN])
    assert not out["doji"][-1]


def test_hammer_in_downtrend():
    hammer = (103.8, 104.05, 101.0, 104.0)  # long lower wick, tiny body at top
    out = detect(DOWN + [hammer])
    assert out["hammer"][-1]
    assert not out["hanging_man"][-1]  # wrong trend context


def test_hammer_shape_in_uptrend_is_hanging_man():
    shape = (106.8, 107.05, 104.0, 107.0)
    out = detect(UP + [shape])
    assert out["hanging_man"][-1]
    assert not out["hammer"][-1]


def test_inverted_hammer_in_downtrend():
    inv = (104.0, 107.0, 103.95, 104.2)  # long upper wick, tiny body at bottom
    out = detect(DOWN + [inv])
    assert out["inverted_hammer"][-1]
    assert not out["shooting_star"][-1]


def test_shooting_star_in_uptrend():
    star = (107.2, 110.0, 106.95, 107.0)
    out = detect(UP + [star])
    assert out["shooting_star"][-1]
    assert not out["inverted_hammer"][-1]


def test_bullish_engulfing():
    # Prev candle DOWN[5] = (105, 106, 103.5, 104), bearish body 105->104.
    engulf = (103.8, 105.8, 103.5, 105.5)
    out = detect(DOWN + [engulf])
    assert out["bullish_engulfing"][-1]
    assert not out["bearish_engulfing"][-1]


def test_bearish_engulfing():
    # Prev candle UP[5] = (105, 107.5, 104.5, 107), bullish body 105->107.
    engulf = (107.3, 107.5, 104.5, 104.8)
    out = detect(UP + [engulf])
    assert out["bearish_engulfing"][-1]
    assert not out["bullish_engulfing"][-1]


def test_morning_star():
    c1 = (104.0, 104.2, 101.8, 102.0)   # long bearish
    c2 = (101.5, 101.7, 101.0, 101.3)   # small body, gapped below c1 body
    c3 = (101.6, 103.7, 101.4, 103.5)   # bullish, closes above c1 body midpoint (103)
    out = detect(DOWN + [c1, c2, c3])
    assert out["morning_star"][-1]
    assert not out["evening_star"][-1]


def test_evening_star():
    c1 = (107.0, 109.2, 106.8, 109.0)   # long bullish
    c2 = (109.5, 109.9, 109.3, 109.7)   # small body, gapped above c1 body
    c3 = (109.3, 109.4, 107.3, 107.5)   # bearish, closes below c1 body midpoint (108)
    out = detect(UP + [c1, c2, c3])
    assert out["evening_star"][-1]
    assert not out["morning_star"][-1]


def test_three_white_soldiers():
    c1 = (104.0, 105.7, 103.9, 105.5)
    c2 = (104.8, 106.7, 104.7, 106.5)   # opens within c1 body, closes higher
    c3 = (105.9, 107.7, 105.8, 107.5)   # opens within c2 body, closes higher
    out = detect(DOWN + [c1, c2, c3])
    assert out["three_white_soldiers"][-1]


def test_three_black_crows():
    c1 = (107.0, 107.1, 105.3, 105.5)
    c2 = (106.2, 106.3, 104.3, 104.5)   # opens within c1 body, closes lower
    c3 = (105.1, 105.2, 103.3, 103.5)   # opens within c2 body, closes lower
    out = detect(UP + [c1, c2, c3])
    assert out["three_black_crows"][-1]


def test_plain_candle_triggers_no_single_candle_shapes():
    out = detect(DOWN + [PLAIN])
    for name in ("hammer", "inverted_hammer", "hanging_man", "shooting_star",
                 "bullish_engulfing", "bearish_engulfing"):
        assert not out[name][-1], name


@pytest.mark.parametrize("scale", [0.01, 1.0, 250.0])
def test_detection_is_price_scale_invariant(scale):
    candles = [tuple(v * scale for v in c) for c in DOWN + [(103.8, 104.05, 101.0, 104.0)]]
    out = detect(candles)
    assert out["hammer"][-1]
