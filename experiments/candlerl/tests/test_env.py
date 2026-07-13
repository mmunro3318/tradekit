"""Gymnasium trading environment: reward arithmetic must be exact.

Position semantics: action k in {0: flat, 1: long, 2: short} sets the target
position p in {0, +1, -1} which is held over the next bar. Reward:
    r_t = p * log(close[t+1] / close[t]) - cost_frac * |p - p_prev|
"""
import math

import numpy as np
import pytest

from candlerl._env import TradingEnv

FLAT, LONG, SHORT = 0, 1, 2


def make_env(closes, cost_bps=10.0, feat_dim=3):
    closes = np.asarray(closes, dtype=float)
    feats = np.zeros((len(closes), feat_dim), dtype=np.float32)
    return TradingEnv(closes=closes, features=feats, cost_bps=cost_bps)


def test_observation_shape_includes_position():
    env = make_env([100, 101, 102, 103], feat_dim=5)
    obs, info = env.reset()
    assert obs.shape == (6,)
    assert env.observation_space.shape == (6,)
    assert env.action_space.n == 3


def test_long_reward_is_log_return_minus_entry_cost():
    env = make_env([100, 101, 100, 102], cost_bps=10)
    env.reset()
    obs, reward, terminated, truncated, info = env.step(LONG)
    assert reward == pytest.approx(math.log(101 / 100) - 0.001)
    assert obs[-1] == 1.0
    assert not terminated


def test_flip_long_to_short_pays_double_turnover():
    env = make_env([100, 101, 100, 102], cost_bps=10)
    env.reset()
    env.step(LONG)
    obs, reward, terminated, truncated, info = env.step(SHORT)
    assert reward == pytest.approx(-math.log(100 / 101) - 0.002)
    assert obs[-1] == -1.0


def test_flat_hold_costs_nothing():
    env = make_env([100, 101, 100, 102], cost_bps=10)
    env.reset()
    obs, reward, *_ = env.step(FLAT)
    assert reward == 0.0
    assert obs[-1] == 0.0


def test_episode_terminates_at_last_bar():
    env = make_env([100, 101, 100, 102])
    env.reset()
    env.step(FLAT)
    env.step(FLAT)
    obs, reward, terminated, truncated, info = env.step(FLAT)
    assert terminated


def test_equity_tracks_compounded_pnl():
    env = make_env([100, 101, 100, 102], cost_bps=0)
    env.reset()
    env.step(LONG)   # 100 -> 101
    env.step(LONG)   # 101 -> 100
    env.step(LONG)   # 100 -> 102
    assert env.equity == pytest.approx((101 / 100) * (100 / 101) * (102 / 100))


def test_time_limit_truncates_not_terminates():
    """Random-start training episodes end by time limit -> truncated, so the
    value function still bootstraps; terminated is reserved for the data end."""
    closes = np.linspace(100, 120, 200)
    feats = np.zeros((200, 2), dtype=np.float32)
    env = TradingEnv(closes=closes, features=feats, random_start=True, episode_len=5)
    env.reset(seed=1)
    assert env._end < len(closes) - 1  # start clear of the data end for this seed
    terminated = truncated = False
    steps = 0
    while not (terminated or truncated):
        _, _, terminated, truncated, _ = env.step(FLAT)
        steps += 1
    assert steps == 5
    assert truncated and not terminated


def test_random_start_can_reach_final_bar():
    """Off-by-one guard: the last bar must be reachable as an episode end."""
    n, ep = 20, 10
    closes = np.linspace(100, 120, n)
    feats = np.zeros((n, 2), dtype=np.float32)
    env = TradingEnv(closes=closes, features=feats, random_start=True, episode_len=ep)
    ends = set()
    for s in range(200):
        env.reset(seed=s)
        ends.add(env._end)
    assert (n - 1) in ends


def test_reset_restores_initial_state():
    env = make_env([100, 101, 100, 102])
    env.reset()
    env.step(LONG)
    obs, info = env.reset()
    assert obs[-1] == 0.0
    assert env.equity == pytest.approx(1.0)
