"""Precompute vision outputs for every bar of every ticker (the 'parquet trick').

The RL environment then consumes static numeric vectors — no rendering or CNN
inference inside the training loop.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from candlerl._dataset import WINDOW
from candlerl._render import IMG_SIZE
from candlerl._vision import VISION_DIM, load_vision, vision_probs


def compute_bridge(df: pd.DataFrame, model, batch: int = 1024) -> np.ndarray:
    """(N, VISION_DIM) vision vector per bar; zeros before the first full window."""
    from candlerl._render import render_window

    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(df)
    out = np.zeros((n, VISION_DIM), dtype=np.float32)
    ends = np.arange(WINDOW - 1, n)
    imgs = np.empty((len(ends), 3, IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for i, t in enumerate(ends):
        sl = slice(t - WINDOW + 1, t + 1)
        img = render_window(o[sl], h[sl], l[sl], c[sl])
        imgs[i] = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
    out[ends] = vision_probs(model, imgs, batch=batch)
    return out


def build_all_bridges(data: dict[str, pd.DataFrame], model_path: Path, out_dir: Path) -> None:
    model = load_vision(model_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_mtime = model_path.stat().st_mtime
    for tk, df in data.items():
        target = out_dir / f"{tk}.npy"
        if target.exists() and target.stat().st_mtime > model_mtime:
            if len(np.load(target, mmap_mode="r")) == len(df):
                continue  # fresh: newer than the vision model and same length
        np.save(target, compute_bridge(df, model))
        print(f"[bridge] {tk}: {len(df)} bars", flush=True)
