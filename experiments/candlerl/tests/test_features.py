"""Numeric feature engineering for the RL state vector.

Contract: `compute_feature_matrix(df)` -> float32 matrix (N, FEATURE_DIM); rows at
index >= WARMUP are finite; features are invariant to absolute price scale.
"""
import numpy as np
import pandas as pd
import pytest

from candlerl._features import FEATURE_DIM, WARMUP, compute_feature_matrix, rsi


def make_df(closes, volume=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    rng = np.random.default_rng(7)
    if volume is None:
        volume = rng.uniform(1e6, 2e6, n)
    return pd.DataFrame(
        {
            "open": closes * (1 + rng.normal(0, 0.002, n)),
            "high": closes * (1 + np.abs(rng.normal(0, 0.004, n))),
            "low": closes * (1 - np.abs(rng.normal(0, 0.004, n))),
            "close": closes,
            "volume": volume,
        }
    )


def trending_df(n=120, drift=0.001, seed=3):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return make_df(closes)


def test_rsi_extremes():
    all_up = np.linspace(100, 160, 40)
    all_down = np.linspace(160, 100, 40)
    assert rsi(all_up, 14)[-1] == pytest.approx(100.0, abs=1e-6)
    assert rsi(all_down, 14)[-1] == pytest.approx(0.0, abs=1e-6)


def test_feature_matrix_shape_and_finiteness():
    df = trending_df(150)
    feats = compute_feature_matrix(df)
    assert feats.shape == (150, FEATURE_DIM)
    assert feats.dtype == np.float32
    assert np.isfinite(feats[WARMUP:]).all()


def test_features_are_price_scale_invariant():
    df = trending_df(150)
    df10 = df.copy()
    for col in ("open", "high", "low", "close"):
        df10[col] = df10[col] * 10
    a = compute_feature_matrix(df)
    b = compute_feature_matrix(df10)
    np.testing.assert_allclose(a[WARMUP:], b[WARMUP:], rtol=1e-4, atol=1e-5)


def test_features_are_causal():
    """Feature at row t must not change when future rows change."""
    df = trending_df(150)
    feats_full = compute_feature_matrix(df)
    feats_cut = compute_feature_matrix(df.iloc[:100].reset_index(drop=True))
    np.testing.assert_allclose(feats_full[WARMUP:100], feats_cut[WARMUP:100], rtol=1e-5, atol=1e-6)
