"""Gymnasium trading environment over precomputed feature vectors.

Actions {0: flat, 1: long, 2: short} set the target position held over the next
bar. Reward is the position's log return minus proportional transaction costs
on turnover; equity compounds exp(reward), so cumulative reward == log equity.
"""
from __future__ import annotations

import math

import gymnasium as gym
import numpy as np
from gymnasium import spaces

_TARGETS = {0: 0.0, 1: 1.0, 2: -1.0}


class TradingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        closes: np.ndarray,
        features: np.ndarray,
        cost_bps: float = 10.0,
        random_start: bool = False,
        episode_len: int | None = None,
    ):
        super().__init__()
        assert len(closes) == len(features)
        self._closes = np.asarray(closes, dtype=np.float64)
        self._features = np.asarray(features, dtype=np.float32)
        self._cost = cost_bps / 1e4
        self._random_start = random_start
        self._episode_len = episode_len
        obs_dim = self._features.shape[1] + 1
        self.observation_space = spaces.Box(-np.inf, np.inf, shape=(obs_dim,), dtype=np.float32)
        self.action_space = spaces.Discrete(3)
        self._t = 0
        self._pos = 0.0
        self._end = len(self._closes) - 1
        self.equity = 1.0

    def _obs(self) -> np.ndarray:
        return np.concatenate(
            [self._features[self._t], np.array([self._pos], dtype=np.float32)]
        ).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        n = len(self._closes)
        if self._random_start and self._episode_len is not None and n > self._episode_len + 1:
            self._t = int(self.np_random.integers(0, n - self._episode_len))
            self._end = self._t + self._episode_len
        else:
            self._t = 0
            self._end = n - 1
        self._pos = 0.0
        self.equity = 1.0
        return self._obs(), {}

    def step(self, action):
        target = _TARGETS[int(action)]
        turnover = abs(target - self._pos)
        log_ret = math.log(self._closes[self._t + 1] / self._closes[self._t])
        reward = target * log_ret - self._cost * turnover
        self.equity *= math.exp(reward)
        self._pos = target
        self._t += 1
        # terminated = ran out of data (true absorbing state); a mid-series
        # episode time limit is truncation, so the critic still bootstraps.
        terminated = self._t >= len(self._closes) - 1
        truncated = not terminated and self._t >= self._end
        return self._obs(), float(reward), terminated, truncated, {"equity": self.equity}
