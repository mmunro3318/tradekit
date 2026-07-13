"""Held-out test evaluation: vision classification metrics + RL backtest."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from torch.utils.data import DataLoader

from candlerl._dataset import TEST_START
from candlerl._rl import backtest_metrics, build_segments, rollout
from candlerl._vision import _eval_split, _MemmapDataset, device, load_thresholds, load_vision


def evaluate_all(
    data: dict[str, pd.DataFrame],
    dataset_dir: Path,
    vision_path: Path,
    ppo_path: Path,
    bridge_dir: Path,
    reports_dir: Path,
) -> dict:
    from stable_baselines3 import PPO

    reports_dir.mkdir(parents=True, exist_ok=True)

    model = load_vision(vision_path).to(device())
    test_dl = DataLoader(_MemmapDataset(dataset_dir, "test"), batch_size=512)
    vision_metrics = _eval_split(model, test_dl, device(), thresholds=load_thresholds(vision_path))

    ppo = PPO.load(ppo_path, device="cpu")
    segments = build_segments(data, bridge_dir, lo=TEST_START, hi=None)
    per_ticker = {}
    for tk, (closes, feats, dates) in segments.items():
        equity, actions = rollout(ppo, closes, feats)
        m = backtest_metrics(equity, actions)
        m["buy_hold_return"] = round(float(closes[-1] / closes[0] - 1), 4)
        per_ticker[tk] = m

    agg = pd.DataFrame(per_ticker).T
    summary = {
        "vision_test_macro_f1": vision_metrics["macro_f1"],
        "vision_test_direction_acc": vision_metrics["direction_acc"],
        "rl_mean_return": round(float(agg["total_return"].mean()), 4),
        "rl_median_sharpe": round(float(agg["sharpe"].median()), 2),
        "rl_mean_max_drawdown": round(float(agg["max_drawdown"].mean()), 4),
        "buy_hold_mean_return": round(float(agg["buy_hold_return"].mean()), 4),
        "tickers_beating_buy_hold": int((agg["total_return"] > agg["buy_hold_return"]).sum()),
        "n_tickers": len(agg),
        "test_period": f"{TEST_START} .. latest",
    }
    report = {"summary": summary, "vision": vision_metrics, "rl_per_ticker": per_ticker}
    (reports_dir / "evaluation.json").write_text(json.dumps(report, indent=2))

    lines = ["# candlerl evaluation\n", "## Summary\n"]
    lines += [f"- **{k}**: {v}" for k, v in summary.items()]
    lines += ["\n## Vision per-pattern (test)\n",
              "| pattern | precision | recall | f1 | support |", "|---|---|---|---|---|"]
    for name, m in vision_metrics["per_pattern"].items():
        lines.append(f"| {name} | {m['precision']} | {m['recall']} | {m['f1']} | {m['support']} |")
    lines += ["\n## RL backtest per ticker (test period)\n", agg.to_markdown()]
    (reports_dir / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    return report
