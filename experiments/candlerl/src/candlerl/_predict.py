"""End-user inference: classify a window, suggest an action. Paper only."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from candlerl._data import load_ohlcv
from candlerl._dataset import WINDOW
from candlerl._features import WARMUP
from candlerl._patterns import PATTERN_NAMES
from candlerl._render import IMG_SIZE, render_window
from candlerl._rl import ACTION_NAMES, make_features
from candlerl._vision import load_thresholds, load_vision, vision_probs

_DIR_NAMES = ["down", "flat", "up"]
_CONF = 0.45  # direction softmax needed before the image-only heuristic acts


def _classify(images: np.ndarray, vision_path: Path) -> tuple[dict, dict, dict]:
    probs = vision_probs(load_vision(vision_path), images)[0]
    thr = load_thresholds(vision_path)
    patterns = {name: round(float(probs[i]), 4) for i, name in enumerate(PATTERN_NAMES)}
    detected = {name: patterns[name] for i, name in enumerate(PATTERN_NAMES)
                if probs[i] > thr[i]}
    direction = {name: round(float(probs[len(PATTERN_NAMES) + i]), 4)
                 for i, name in enumerate(_DIR_NAMES)}
    return patterns, detected, direction


def _heuristic_action(direction: dict) -> str:
    best = max(direction, key=direction.get)
    if direction[best] < _CONF:
        return "flat"
    return {"up": "long", "down": "short", "flat": "flat"}[best]


def _policy_action(df: pd.DataFrame, vision_vec: np.ndarray, ppo_path: Path,
                   position: float = 0.0) -> str:
    from stable_baselines3 import PPO

    bridge = np.zeros((len(df), vision_vec.shape[0]), dtype=np.float32)
    bridge[-1] = vision_vec
    feats = make_features(df, bridge)
    obs = np.concatenate([feats[-1], [position]]).astype(np.float32)
    ppo = PPO.load(ppo_path, device="cpu")
    action, _ = ppo.predict(obs, deterministic=True)
    return ACTION_NAMES[int(action)]


def _predict_frame(df: pd.DataFrame, vision_path: Path, ppo_path: Path) -> dict:
    if len(df) < WINDOW:
        raise ValueError(f"need at least {WINDOW} rows, got {len(df)}")
    tail = df.iloc[-WINDOW:]
    img = render_window(*(tail[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    images = (np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0)[None]
    patterns, detected, direction = _classify(images, vision_path)
    vision_vec = np.array(
        [patterns[n] for n in PATTERN_NAMES] + [direction[n] for n in _DIR_NAMES],
        dtype=np.float32,
    )
    out = {
        "window_end": str(df.index[-1]) if isinstance(df.index, pd.DatetimeIndex) else len(df) - 1,
        "patterns_detected": detected,
        "pattern_probs": patterns,
        "direction_probs": direction,
        "suggested_action": _policy_action(df, vision_vec, ppo_path),
        "action_source": "ppo_policy",
        "note": "paper suggestion only — not financial advice, nothing is executed",
    }
    if len(df) < WARMUP:
        out["warning"] = f"fewer than {WARMUP} rows: indicator features partially warmed up"
    return out


def predict_csv(path: Path, vision_path: Path, ppo_path: Path) -> dict:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    if "date" in df.columns:
        # vendor exports are often newest-first; the model needs oldest-first
        df = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["date"]))).sort_index()
    return _predict_frame(df, vision_path, ppo_path)


def predict_ticker(ticker: str, vision_path: Path, ppo_path: Path) -> dict:
    df = load_ohlcv(ticker.upper())
    out = _predict_frame(df, vision_path, ppo_path)
    out["ticker"] = ticker.upper()
    return out


def predict_image(path: Path, vision_path: Path) -> dict:
    from PIL import Image

    img = Image.open(path).convert("RGB")
    if img.size != (IMG_SIZE, IMG_SIZE):
        img = img.resize((IMG_SIZE, IMG_SIZE), Image.NEAREST)
    images = (np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0)[None]
    patterns, detected, direction = _classify(images, vision_path)
    return {
        "image": str(path),
        "patterns_detected": detected,
        "pattern_probs": patterns,
        "direction_probs": direction,
        "suggested_action": _heuristic_action(direction),
        "action_source": "direction_heuristic (image-only input lacks indicator features; "
                         "use --csv/--ticker for the full RL policy)",
        "note": "paper suggestion only — not financial advice, nothing is executed",
    }


def run_demo(n: int, seed: int, dataset_dir: Path, vision_path: Path, ppo_path: Path,
             reports_dir: Path) -> Path:
    """Sample held-out test windows; render, classify, act; write a markdown report."""
    from PIL import Image
    from stable_baselines3 import PPO

    from candlerl._bridge import compute_bridge
    from candlerl._data import load_universe
    from candlerl._dataset import HORIZON

    rng = np.random.default_rng(seed)
    meta = pd.read_parquet(dataset_dir / "meta.parquet")
    test = meta[meta.split == "test"].reset_index(drop=True)
    picks = test.iloc[rng.choice(len(test), size=min(n, len(test)), replace=False)]

    images = np.load(dataset_dir / "images_test.npy", mmap_mode="r")
    model = load_vision(vision_path)
    thr = load_thresholds(vision_path)
    ppo = PPO.load(ppo_path, device="cpu")
    data = load_universe(sorted(picks["ticker"].unique()))

    out_dir = reports_dir / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    feats_cache: dict[str, np.ndarray] = {}
    rows = []
    for _, r in picks.iterrows():
        tk, t = r["ticker"], int(r["end_idx"])
        df = data[tk]
        if df.index[t] != pd.Timestamp(r["end_date"]):
            raise RuntimeError(
                f"{tk}: cached OHLCV no longer aligns with the built dataset "
                f"(data refreshed after `build`?) — re-run `candlerl build`"
            )
        if tk not in feats_cache:
            bridge = compute_bridge(df, model)
            feats_cache[tk] = make_features(df, bridge)
        img_arr = np.asarray(images[r["row"]], dtype=np.float32) / 255.0
        probs = vision_probs(model, img_arr[None])[0]
        patterns = {PATTERN_NAMES[i]: float(probs[i]) for i in range(len(PATTERN_NAMES))}
        true = [p for p in PATTERN_NAMES if r[f"p_{p}"] > 0.5]
        obs = np.concatenate([feats_cache[tk][t], [0.0]]).astype(np.float32)
        action = ACTION_NAMES[int(ppo.predict(obs, deterministic=True)[0])]
        closes = df["close"].to_numpy(float)
        fwd = float(np.log(closes[t + HORIZON] / closes[t])) if t + HORIZON < len(closes) else None
        png = out_dir / f"{tk}_{pd.Timestamp(r['end_date']).date()}.png"
        Image.fromarray(np.asarray(images[r["row"]]).transpose(1, 2, 0)).resize(
            (256, 256), Image.NEAREST).save(png)
        rows.append({
            "chart": png.name, "ticker": tk, "date": str(pd.Timestamp(r["end_date"]).date()),
            "true_patterns": ", ".join(true) or "—",
            "predicted": ", ".join(
                k for i, k in enumerate(PATTERN_NAMES) if probs[i] > thr[i]) or "—",
            "action": action,
            "fwd_5bar_logret": round(fwd, 4) if fwd is not None else "n/a",
        })
    table = pd.DataFrame(rows)
    report = out_dir / "demo_report.md"
    body = ["# candlerl demo — held-out test windows\n",
            "Charts rendered from test-set OHLCV; classification vs rule-based truth; "
            "action from the PPO policy (flat position assumed).\n",
            table.to_markdown(index=False)]
    report.write_text("\n".join(body), encoding="utf-8")
    return report
