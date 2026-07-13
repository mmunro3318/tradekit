"""candlerl CLI — pipeline orchestration and inference.

Pipeline order: fetch -> build -> train-vision -> bridge -> train-rl -> evaluate.
`predict` and `demo` serve the finished models. Paper trading only: this tool
suggests actions; it never touches an exchange.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from candlerl._data import ARTIFACTS, load_universe

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)

DATASET_DIR = ARTIFACTS / "dataset"
MODELS_DIR = ARTIFACTS / "models"
BRIDGE_DIR = ARTIFACTS / "bridge"
REPORTS_DIR = ARTIFACTS / "reports"
VISION_PATH = MODELS_DIR / "vision.pt"
PPO_PATH = MODELS_DIR / "ppo_trader.zip"


@app.command()
def fetch(refresh: bool = False):
    """Download/cache daily OHLCV for the universe."""
    from candlerl._data import summarize

    data = load_universe(refresh=refresh)
    print(summarize(data).to_string())


@app.command()
def build():
    """Render the labeled image dataset (train/val/test memmaps)."""
    from candlerl._dataset import build_image_dataset

    data = load_universe()
    meta = build_image_dataset(data, DATASET_DIR)
    print(meta.groupby("split").size().to_string())
    pcols = [c for c in meta.columns if c.startswith("p_")]
    print("pattern base rates (train):")
    print(meta[meta.split == "train"][pcols].mean().round(4).to_string())


@app.command("train-vision")
def train_vision_cmd(epochs: int = 8):
    from candlerl._vision import train_vision

    best = train_vision(DATASET_DIR, VISION_PATH, epochs=epochs)
    print(json.dumps(best, indent=2))


@app.command()
def bridge():
    """Precompute vision vectors for every bar (feeds the RL env)."""
    from candlerl._bridge import build_all_bridges

    build_all_bridges(load_universe(), VISION_PATH, BRIDGE_DIR)


@app.command("train-rl")
def train_rl_cmd(timesteps: int = 1_500_000):
    from candlerl._rl import train_policy

    train_policy(load_universe(), BRIDGE_DIR, PPO_PATH, total_timesteps=timesteps)


@app.command()
def evaluate():
    """Vision test metrics + RL backtest on the held-out test period."""
    from candlerl._evaluate import evaluate_all

    report = evaluate_all(load_universe(), DATASET_DIR, VISION_PATH, PPO_PATH, BRIDGE_DIR,
                          REPORTS_DIR)
    print(json.dumps(report["summary"], indent=2))


@app.command()
def predict(
    csv: Path = typer.Option(None, help="CSV with open,high,low,close[,volume] columns"),
    image: Path = typer.Option(None, help="Chart PNG rendered by candlerl (classification only)"),
    ticker: str = typer.Option(None, help="Ticker from the cached universe (uses latest bars)"),
):
    """Classify a candlestick window and suggest an action (paper suggestion only)."""
    from candlerl._predict import predict_csv, predict_image, predict_ticker

    if sum(x is not None for x in (csv, image, ticker)) != 1:
        raise typer.BadParameter("provide exactly one of --csv, --image, --ticker")
    if csv:
        out = predict_csv(csv, VISION_PATH, PPO_PATH)
    elif image:
        out = predict_image(image, VISION_PATH)
    else:
        out = predict_ticker(ticker, VISION_PATH, PPO_PATH)
    print(json.dumps(out, indent=2, default=str))


@app.command()
def demo(n: int = 12, seed: int = 0):
    """Sample test-set windows: render, classify, suggest actions, write a report."""
    from candlerl._predict import run_demo

    out = run_demo(n=n, seed=seed, dataset_dir=DATASET_DIR, vision_path=VISION_PATH,
                   ppo_path=PPO_PATH, reports_dir=REPORTS_DIR)
    print(f"report: {out}")


if __name__ == "__main__":
    app()
