"""Deterministic candlestick renderer: OHLC window -> RGB image.

The same renderer is used to build the training set and at inference time, so the
train/serve distributions match by construction.
"""
import numpy as np

from candlerl._render import IMG_SIZE, render_window


def make_window(n=32, seed=1, drift=0.0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    return open_, high, low, close


def test_output_is_rgb_square():
    img = render_window(*make_window())
    assert img.mode == "RGB"
    assert img.size == (IMG_SIZE, IMG_SIZE)


def test_render_is_deterministic():
    a = render_window(*make_window())
    b = render_window(*make_window())
    assert a.tobytes() == b.tobytes()


def test_render_is_price_scale_invariant():
    o, h, l, c = make_window()
    a = render_window(o, h, l, c)
    b = render_window(o * 50, h * 50, l * 50, c * 50)
    assert a.tobytes() == b.tobytes()


def test_bullish_and_bearish_candles_use_distinct_colors():
    # Strictly rising closes with open below close -> all bullish candles.
    n = 32
    close = np.linspace(100, 120, n)
    open_ = close - 0.4
    high = close + 0.1
    low = open_ - 0.1
    up_img = np.asarray(render_window(open_, high, low, close), dtype=int)
    down_img = np.asarray(render_window(close, high, low, open_), dtype=int)

    def count(img, mask_fn):
        r, g, b = img[..., 0], img[..., 1], img[..., 2]
        return int(mask_fn(r, g, b).sum())

    bull = lambda r, g, b: (g > r + 40) & (g > b + 40)
    bear = lambda r, g, b: (r > g + 40) & (r > b + 40)
    assert count(up_img, bull) > 50 and count(up_img, bear) == 0
    assert count(down_img, bear) > 50 and count(down_img, bull) == 0


def test_quantize_matches_render_grid():
    """Windows that render to identical pixels must quantize identically."""
    from candlerl._render import quantize_prices

    o, h, l, c = make_window()
    q = quantize_prices(o, h, l, c)
    # rendering the quantized prices reproduces the original image
    a = render_window(o, h, l, c)
    b = render_window(*q)
    assert a.tobytes() == b.tobytes()
    # idempotent: quantizing again changes nothing
    q2 = quantize_prices(*q)
    for x, y in zip(q, q2):
        np.testing.assert_allclose(x, y)


def test_quantized_hammer_is_still_a_hammer():
    from candlerl._patterns import detect_patterns
    from candlerl._render import quantize_prices

    down = [(110.0 - i, 111.0 - i, 108.5 - i, 109.0 - i) for i in range(6)]
    candles = np.array(down + [(103.8, 104.05, 101.0, 104.0)], dtype=float)
    o, h, l, c = candles[:, 0], candles[:, 1], candles[:, 2], candles[:, 3]
    q = quantize_prices(o, h, l, c)
    assert detect_patterns(*q)["hammer"][-1]


def test_flat_window_does_not_crash():
    n = 32
    flat = np.full(n, 100.0)
    img = render_window(flat, flat, flat, flat)
    assert img.size == (IMG_SIZE, IMG_SIZE)
