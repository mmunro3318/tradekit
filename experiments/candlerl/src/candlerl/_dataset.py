"""Windowing, labeling, leak-safe chronological splits, and image-dataset build."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

VAL_START = "2023-01-01"
TEST_START = "2024-01-01"
# A pattern counts for a window if it completes in the window's last K bars.
LABEL_TAIL = 3

WINDOW = 32   # candles per chart image
HORIZON = 5   # bars ahead for the direction label

DIR_DOWN, DIR_FLAT, DIR_UP = 0, 1, 2


def direction_labels(close: np.ndarray, threshold: float = 0.01) -> np.ndarray:
    """Bucketed forward log return over HORIZON bars; -1 where undefined."""
    close = np.asarray(close, dtype=float)
    n = len(close)
    out = np.full(n, -1, dtype=np.int64)
    if n <= HORIZON:
        return out
    fwd = np.log(close[HORIZON:] / close[:-HORIZON])
    out[: n - HORIZON] = np.where(
        fwd > threshold, DIR_UP, np.where(fwd < -threshold, DIR_DOWN, DIR_FLAT)
    )
    return out


def window_indices(n: int) -> np.ndarray:
    """End-indices t such that [t-WINDOW+1, t] is a full window and t+HORIZON < n."""
    return np.arange(WINDOW - 1, n - HORIZON)


def split_by_date(
    ends: np.ndarray, dates: pd.DatetimeIndex, val_start: str, test_start: str
):
    """Chronological split with a HORIZON-bar embargo before each boundary.

    Returns index arrays into `ends` for (train, val, test). A window belongs to
    a segment by its END bar; its label horizon must not cross the next boundary.
    """
    v = int(np.searchsorted(dates, pd.Timestamp(val_start)))
    t = int(np.searchsorted(dates, pd.Timestamp(test_start)))
    train = np.where(ends + HORIZON < v)[0]
    val = np.where((ends >= v) & (ends + HORIZON < t))[0]
    test = np.where(ends >= t)[0]
    return train, val, test


def build_image_dataset(
    data: dict[str, pd.DataFrame],
    out_dir: Path,
    caps: dict[str, int] | None = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Render labeled window images into uint8 memmaps per split.

    Train split: pattern-positive windows (capped at half the budget) plus
    random negatives filling the cap — patterns are rare, so uniform sampling
    would drown them. Val/test: uniform random subsample so metrics reflect
    true base rates.
    """
    from candlerl._patterns import PATTERN_NAMES, pattern_matrix
    from candlerl._render import IMG_SIZE, quantize_prices, render_window

    caps = caps or {"train": 60_000, "val": 8_000, "test": 12_000}
    rows: list[dict] = []
    for tk, df in data.items():
        o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        dl = direction_labels(c)
        ends = window_indices(len(df))
        tr, va, te = split_by_date(ends, df.index, VAL_START, TEST_START)
        split_of = np.full(len(ends), "", dtype=object)
        split_of[tr], split_of[va], split_of[te] = "train", "val", "test"
        for j, t in enumerate(ends):
            if not split_of[j] or dl[t] < 0:
                continue
            # Label on pixel-grid-quantized prices: the label is then a pure
            # function of the rendered image (see _render.quantize_prices).
            sl = slice(t - WINDOW + 1, t + 1)
            pm_win = pattern_matrix(*quantize_prices(o[sl], h[sl], l[sl], c[sl]))
            tail = pm_win[-LABEL_TAIL:].max(axis=0)
            rows.append(
                {"ticker": tk, "end_idx": int(t), "end_date": df.index[t],
                 "split": split_of[j], "direction": int(dl[t]),
                 **{f"p_{name}": float(tail[k]) for k, name in enumerate(PATTERN_NAMES)}}
            )
    meta = pd.DataFrame(rows)
    pcols = [f"p_{n}" for n in PATTERN_NAMES]

    keep_frames = []
    for split, cap in caps.items():
        m = meta[meta["split"] == split]
        if split == "train":
            pos = m[m[pcols].sum(axis=1) > 0]
            neg = m[m[pcols].sum(axis=1) == 0]
            if len(pos) > cap // 2:
                pos = pos.sample(n=cap // 2, random_state=seed)
            n_neg = min(len(neg), cap - len(pos))
            keep = pd.concat([pos, neg.sample(n=n_neg, random_state=seed)])
        else:
            keep = m.sample(n=min(len(m), cap), random_state=seed)
        keep_frames.append(keep.sort_values(["ticker", "end_idx"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    all_meta = []
    for keep, split in zip(keep_frames, caps.keys()):
        n = len(keep)
        images = np.lib.format.open_memmap(
            out_dir / f"images_{split}.npy", mode="w+",
            dtype=np.uint8, shape=(n, 3, IMG_SIZE, IMG_SIZE),
        )
        for i, (_, r) in enumerate(keep.iterrows()):
            df = data[r["ticker"]]
            t = r["end_idx"]
            sl = slice(t - WINDOW + 1, t + 1)
            img = render_window(
                df["open"].to_numpy()[sl], df["high"].to_numpy()[sl],
                df["low"].to_numpy()[sl], df["close"].to_numpy()[sl],
            )
            images[i] = np.asarray(img, dtype=np.uint8).transpose(2, 0, 1)
        images.flush()
        np.save(out_dir / f"patterns_{split}.npy", keep[pcols].to_numpy(np.float32))
        np.save(out_dir / f"direction_{split}.npy", keep["direction"].to_numpy(np.int64))
        keep = keep.copy()
        keep["row"] = np.arange(n)
        all_meta.append(keep)
    full = pd.concat(all_meta, ignore_index=True)
    full.to_parquet(out_dir / "meta.parquet")
    return full
