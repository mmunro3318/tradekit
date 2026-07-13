"""PPO trading policy over numeric + vision features (Stable-Baselines3).

Observation = [25 numeric features | 14 vision probs | position] = 40 dims.
Training samples random 256-bar episodes across the whole universe's train
segment; evaluation rolls the deterministic policy over contiguous segments.
"""
from __future__ import annotations

from pathlib import Path

import gymnasium as gym
import numpy as np
import pandas as pd

from candlerl._dataset import VAL_START
from candlerl._env import TradingEnv
from candlerl._features import WARMUP, compute_feature_matrix

COST_BPS = 10.0
EPISODE_LEN = 256
ACTION_NAMES = {0: "flat", 1: "long", 2: "short"}


def make_features(df: pd.DataFrame, bridge: np.ndarray) -> np.ndarray:
    """Full per-bar observation features (numeric ++ vision), float32."""
    numeric = compute_feature_matrix(df)
    assert len(numeric) == len(bridge)
    return np.concatenate([numeric, bridge.astype(np.float32)], axis=1)


def build_segments(
    data: dict[str, pd.DataFrame],
    bridge_dir: Path,
    lo: str | None,
    hi: str | None,
) -> dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]]:
    """Per-ticker (closes, features, dates) restricted to [lo, hi).

    Features are computed on the full history first (indicators need warmup),
    then sliced — so a segment's features never depend on data after `hi`.
    """
    out = {}
    for tk, df in data.items():
        bridge = np.load(bridge_dir / f"{tk}.npy")
        feats = make_features(df, bridge)
        mask = np.ones(len(df), dtype=bool)
        mask[:WARMUP] = False
        if lo:
            mask &= df.index >= pd.Timestamp(lo)
        if hi:
            mask &= df.index < pd.Timestamp(hi)
        idx = np.where(mask)[0]
        if len(idx) < 60:
            continue
        sl = slice(idx[0], idx[-1] + 1)
        out[tk] = (df["close"].to_numpy(float)[sl], feats[sl], df.index[sl])
    return out


class MultiTickerEnv(gym.Env):
    """On each reset, picks a random ticker and a random EPISODE_LEN start."""

    def __init__(self, segments: dict, cost_bps: float = COST_BPS):
        super().__init__()
        self._envs = [
            TradingEnv(closes, feats, cost_bps=cost_bps,
                       random_start=True, episode_len=EPISODE_LEN)
            for closes, feats, _ in segments.values()
        ]
        self.observation_space = self._envs[0].observation_space
        self.action_space = self._envs[0].action_space
        self._current = self._envs[0]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._current = self._envs[int(self.np_random.integers(len(self._envs)))]
        return self._current.reset(seed=int(self.np_random.integers(2**31)))

    def step(self, action):
        return self._current.step(action)


def train_policy(
    data: dict[str, pd.DataFrame],
    bridge_dir: Path,
    model_path: Path,
    total_timesteps: int = 2_000_000,
    seed: int = 0,
    train_cost_bps: float = 25.0,
) -> None:
    """Train with a HIGHER transaction cost than evaluation (25 vs 10 bps).

    First training round churned 0.76 position-flips/bar and bled ~38% to costs
    on the test period; an inflated training cost plus a small entropy bonus
    teaches position persistence without changing the evaluation economics.
    """
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    segments = build_segments(data, bridge_dir, lo=None, hi=VAL_START)
    venv = DummyVecEnv(
        [(lambda: MultiTickerEnv(segments, cost_bps=train_cost_bps)) for _ in range(8)]
    )
    model = PPO(
        "MlpPolicy",
        venv,
        policy_kwargs={"net_arch": [256, 128]},
        learning_rate=3e-4,
        n_steps=1024,
        batch_size=256,
        ent_coef=0.001,
        gamma=0.99,
        seed=seed,
        device="cpu",
        verbose=1,
    )
    model.learn(total_timesteps=total_timesteps, progress_bar=False)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(model_path)


def rollout(model, closes: np.ndarray, feats: np.ndarray, cost_bps: float = COST_BPS):
    """Deterministic policy over a contiguous segment -> (equity_curve, actions)."""
    env = TradingEnv(closes, feats, cost_bps=cost_bps)
    obs, _ = env.reset()
    equity = [1.0]
    actions = []
    done = False
    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _, info = env.step(int(action))
        equity.append(info["equity"])
        actions.append(int(action))
    return np.array(equity), np.array(actions)


def backtest_metrics(equity: np.ndarray, actions: np.ndarray) -> dict:
    rets = np.diff(np.log(equity))
    sharpe = float(rets.mean() / (rets.std() + 1e-12) * np.sqrt(252)) if len(rets) > 2 else 0.0
    peak = np.maximum.accumulate(equity)
    max_dd = float((equity / peak - 1).min())
    positions = np.array([{0: 0, 1: 1, 2: -1}[a] for a in actions])
    trades = int(np.abs(np.diff(positions, prepend=0)).sum())
    return {
        "total_return": round(float(equity[-1] - 1), 4),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 4),
        "trades": trades,
        "bars": len(actions),
        "long_frac": round(float((positions == 1).mean()), 3),
        "short_frac": round(float((positions == -1).mean()), 3),
    }
