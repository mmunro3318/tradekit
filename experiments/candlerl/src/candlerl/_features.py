"""Numeric feature engineering for the RL state vector.

All features are causal (use only rows <= t) and invariant to absolute price
scale. Layout per row: 20 vol-normalized log returns, RSI(14)/100, ATR(14)/close,
MACD histogram/close, Bollinger %B(20, 2), volume z-score(20).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_N_RETURNS = 20
FEATURE_DIM = _N_RETURNS + 5
WARMUP = 40
_EPS = 1e-8


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    delta = np.diff(close, prepend=close[0])
    gain = pd.Series(np.maximum(delta, 0.0)).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    loss = pd.Series(np.maximum(-delta, 0.0)).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    out = np.full(len(close), 50.0)
    active = (gain + loss) > _EPS * np.abs(close)
    out[active] = 100.0 * gain[active] / (gain[active] + loss[active])
    return out


def _atr(high, low, close, period: int = 14) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().to_numpy()


def _macd_hist(close: np.ndarray) -> np.ndarray:
    s = pd.Series(close)
    macd = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    return (macd - signal).to_numpy()


def _pct_b(close: np.ndarray, period: int = 20) -> np.ndarray:
    s = pd.Series(close)
    mid = s.rolling(period, min_periods=1).mean()
    sd = s.rolling(period, min_periods=1).std().fillna(0.0)
    upper = mid + 2 * sd
    lower = mid - 2 * sd
    return ((s - lower) / (upper - lower + _EPS * s.abs())).to_numpy()


def compute_feature_matrix(df: pd.DataFrame) -> np.ndarray:
    h = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    n = len(c)

    log_ret = np.zeros(n)
    log_ret[1:] = np.log(c[1:] / c[:-1])
    ret_sd = (
        pd.Series(log_ret).rolling(_N_RETURNS, min_periods=2).std().fillna(0.0).to_numpy() + _EPS
    )
    norm_ret = log_ret / ret_sd

    ret_block = np.zeros((n, _N_RETURNS))
    for k in range(_N_RETURNS):
        # column k holds the normalized return k bars back
        if k < n:
            ret_block[k:, k] = norm_ret[: n - k] if k else norm_ret
    # note: normalization uses the sd at each return's own time -> causal

    vol_mean = pd.Series(v).rolling(20, min_periods=1).mean().to_numpy()
    vol_sd = pd.Series(v).rolling(20, min_periods=2).std().fillna(0.0).to_numpy()
    vol_z = (v - vol_mean) / (vol_sd + _EPS * np.maximum(vol_mean, 1.0))

    extras = np.stack(
        [
            rsi(c) / 100.0,
            _atr(h, low, c) / c,
            _macd_hist(c) / c,
            _pct_b(c),
            np.clip(vol_z, -5, 5),
        ],
        axis=1,
    )
    feats = np.concatenate([np.clip(ret_block, -5, 5), extras], axis=1).astype(np.float32)
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)
