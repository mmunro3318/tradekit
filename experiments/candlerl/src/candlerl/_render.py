"""Deterministic candlestick chart renderer (OHLC window -> PIL RGB image).

The same code path builds the training set and serves inference, so the vision
model never sees a distribution shift from charting-library artifacts.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

IMG_SIZE = 128
_MARGIN = 4
_BG = (10, 12, 16)
_BULL = (0, 200, 80)
_BEAR = (220, 40, 40)


def render_window(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    size: int = IMG_SIZE,
) -> Image.Image:
    o = np.asarray(open_, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)
    n = len(c)

    p_min, p_max = float(l.min()), float(h.max())
    span = p_max - p_min
    if span <= 0:
        p_min -= 0.5
        span = 1.0

    # Normalize prices first so the pixel mapping is independent of price scale.
    def y(p: np.ndarray) -> np.ndarray:
        frac = (p - p_min) / span
        return np.round((size - 1 - _MARGIN) - frac * (size - 1 - 2 * _MARGIN)).astype(int)

    slot = (size - 2 * _MARGIN) / n
    body_w = max(1, int(slot * 0.6))
    xs_left = (_MARGIN + np.round(np.arange(n) * slot + (slot - body_w) / 2)).astype(int)

    img = Image.new("RGB", (size, size), _BG)
    draw = ImageDraw.Draw(img)
    y_o, y_h, y_l, y_c = y(o), y(h), y(l), y(c)

    for i in range(n):
        color = _BULL if c[i] >= o[i] else _BEAR
        x0 = int(xs_left[i])
        x1 = x0 + body_w - 1
        xc = (x0 + x1) // 2
        draw.line([(xc, int(y_h[i])), (xc, int(y_l[i]))], fill=color, width=1)
        top = int(min(y_o[i], y_c[i]))
        bot = int(max(y_o[i], y_c[i]))
        draw.rectangle([x0, top, x1, bot], fill=color)
    return img


def quantize_prices(open_, high, low, close, size: int = IMG_SIZE):
    """Snap OHLC to the exact pixel grid render_window() draws on.

    Pattern labels are computed on these quantized values so that a label is a
    pure function of the rendered image: two windows with identical pixels get
    identical labels (sub-pixel geometry cannot leak into supervision).
    """
    o = np.asarray(open_, dtype=np.float64)
    h = np.asarray(high, dtype=np.float64)
    l = np.asarray(low, dtype=np.float64)
    c = np.asarray(close, dtype=np.float64)

    p_min, p_max = float(l.min()), float(h.max())
    span = p_max - p_min
    if span <= 0:
        p_min -= 0.5
        span = 1.0

    def y(p):
        frac = (p - p_min) / span
        return np.round((size - 1 - _MARGIN) - frac * (size - 1 - 2 * _MARGIN)).astype(int)

    def grid_price(p):
        # invert y back to a price on the grid; monotone in -y
        return p_min + ((size - 1 - _MARGIN) - y(p).astype(np.float64)) * (
            span / (size - 1 - 2 * _MARGIN)
        )

    return grid_price(o), grid_price(h), grid_price(l), grid_price(c)


def render_array(open_, high, low, close, size: int = IMG_SIZE) -> np.ndarray:
    """(3, size, size) float32 in [0, 1], CHW for torch."""
    img = render_window(open_, high, low, close, size=size)
    a = np.asarray(img, dtype=np.float32) / 255.0
    return a.transpose(2, 0, 1)
