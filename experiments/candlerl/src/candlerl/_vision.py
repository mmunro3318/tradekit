"""Vision model: multi-label pattern head + direction head over chart images.

Compact CNN trained from scratch — labels are a deterministic function of the
rendered geometry, so ImageNet transfer is unnecessary and the whole net fits
easily on an 8GB GPU (or CPU in a pinch).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from candlerl._patterns import PATTERN_NAMES

N_PATTERNS = len(PATTERN_NAMES)
N_DIRECTIONS = 3
VISION_DIM = N_PATTERNS + N_DIRECTIONS  # bridge vector fed to the RL agent


def device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


class VisionNet(nn.Module):
    def __init__(self, width: int = 32):
        super().__init__()
        chans = [3, width, width * 2, width * 4, width * 8]
        blocks = []
        for cin, cout in zip(chans[:-1], chans[1:]):
            blocks += [
                nn.Conv2d(cin, cout, 3, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(cout),
                nn.ReLU(inplace=True),
                nn.Conv2d(cout, cout, 3, padding=1, bias=False),
                nn.BatchNorm2d(cout),
                nn.ReLU(inplace=True),
            ]
        self.trunk = nn.Sequential(*blocks, nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.neck = nn.Sequential(nn.Linear(chans[-1], 256), nn.ReLU(inplace=True), nn.Dropout(0.3))
        self.pattern_head = nn.Linear(256, N_PATTERNS)
        self.direction_head = nn.Linear(256, N_DIRECTIONS)

    def forward(self, x):
        z = self.neck(self.trunk(x))
        return self.pattern_head(z), self.direction_head(z)


class _MemmapDataset(Dataset):
    def __init__(self, root: Path, split: str):
        self.images = np.load(root / f"images_{split}.npy", mmap_mode="r")
        self.patterns = np.load(root / f"patterns_{split}.npy")
        self.direction = np.load(root / f"direction_{split}.npy")

    def __len__(self):
        return len(self.direction)

    def __getitem__(self, i):
        img = torch.from_numpy(np.asarray(self.images[i], dtype=np.float32) / 255.0)
        return img, torch.from_numpy(self.patterns[i]), int(self.direction[i])


@torch.no_grad()
def _collect_probs(model, loader, dev):
    model.eval()
    probs, trues, dir_pred, dir_true = [], [], [], []
    for img, pat, direc in loader:
        p_logit, d_logit = model(img.to(dev, non_blocking=True))
        probs.append(torch.sigmoid(p_logit).cpu().numpy())
        trues.append(pat.numpy() > 0.5)
        dir_pred.append(d_logit.argmax(1).cpu().numpy())
        dir_true.append(np.asarray(direc))
    return (np.concatenate(probs), np.concatenate(trues),
            np.concatenate(dir_pred), np.concatenate(dir_true))


def _f1_counts(pred, true):
    tp = (pred & true).sum(axis=0)
    fp = (pred & ~true).sum(axis=0)
    fn = (~pred & true).sum(axis=0)
    prec = tp / np.maximum(tp + fp, 1)
    rec = tp / np.maximum(tp + fn, 1)
    f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-9)
    return prec, rec, f1, tp, fn


def calibrate_thresholds(probs: np.ndarray, trues: np.ndarray) -> np.ndarray:
    """Per-class decision threshold maximizing F1 (tuned on validation only)."""
    grid = np.arange(0.05, 0.96, 0.05)
    best = np.full(N_PATTERNS, 0.5)
    for k in range(N_PATTERNS):
        scores = [
            _f1_counts((probs[:, k : k + 1] > t), trues[:, k : k + 1])[2][0] for t in grid
        ]
        best[k] = float(grid[int(np.argmax(scores))])
    return best


@torch.no_grad()
def _eval_split(model, loader, dev, thresholds: np.ndarray | None = None) -> dict:
    probs, trues, dir_pred, dir_true = _collect_probs(model, loader, dev)
    thr = thresholds if thresholds is not None else np.full(N_PATTERNS, 0.5)
    pred = probs > thr[None, :]
    prec, rec, f1, tp, fn = _f1_counts(pred, trues)
    dir_ok, dir_n = int((dir_pred == dir_true).sum()), len(dir_true)
    return {
        "per_pattern": {
            name: {"precision": round(float(prec[k]), 4), "recall": round(float(rec[k]), 4),
                   "f1": round(float(f1[k]), 4), "support": int(tp[k] + fn[k])}
            for k, name in enumerate(PATTERN_NAMES)
        },
        "macro_f1": round(float(f1.mean()), 4),
        "direction_acc": round(dir_ok / max(dir_n, 1), 4),
    }


def train_vision(dataset_dir: Path, model_path: Path, epochs: int = 8, batch: int = 256) -> dict:
    dev = device()
    train_ds = _MemmapDataset(dataset_dir, "train")
    val_ds = _MemmapDataset(dataset_dir, "val")
    pin = torch.cuda.is_available()
    train_dl = DataLoader(train_ds, batch_size=batch, shuffle=True, num_workers=0, pin_memory=pin)
    val_dl = DataLoader(val_ds, batch_size=batch, num_workers=0, pin_memory=pin)

    pos = train_ds.patterns.sum(axis=0)
    neg = len(train_ds) - pos
    pos_weight = torch.tensor(np.clip(neg / np.maximum(pos, 1), 1.0, 30.0), dtype=torch.float32)

    model = VisionNet().to(dev)
    bce = nn.BCEWithLogitsLoss(pos_weight=pos_weight.to(dev))
    ce = nn.CrossEntropyLoss()
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    best = {"macro_f1": -1.0}
    for ep in range(epochs):
        model.train()
        total = 0.0
        for img, pat, direc in train_dl:
            img, pat, direc = img.to(dev), pat.to(dev), direc.to(dev)
            opt.zero_grad(set_to_none=True)
            p_logit, d_logit = model(img)
            loss = bce(p_logit, pat) + 0.5 * ce(d_logit, direc)
            loss.backward()
            opt.step()
            total += float(loss) * len(img)
        sched.step()
        metrics = _eval_split(model, val_dl, dev)
        print(f"[vision] epoch {ep + 1}/{epochs} loss={total / len(train_ds):.4f} "
              f"val_macro_f1={metrics['macro_f1']} dir_acc={metrics['direction_acc']}", flush=True)
        if metrics["macro_f1"] > best["macro_f1"]:
            best = metrics | {"epoch": ep + 1}
            model_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), model_path)

    # Calibrate per-class thresholds on val with the best checkpoint, then
    # report val metrics at the calibrated operating point.
    model.load_state_dict(torch.load(model_path, map_location=dev, weights_only=True))
    probs, trues, _, _ = _collect_probs(model, val_dl, dev)
    thr = calibrate_thresholds(probs, trues)
    (model_path.parent / "thresholds.json").write_text(
        json.dumps({name: float(thr[k]) for k, name in enumerate(PATTERN_NAMES)}, indent=2)
    )
    best = _eval_split(model, val_dl, dev, thresholds=thr) | {"epoch": best.get("epoch")}
    print(f"[vision] calibrated val_macro_f1={best['macro_f1']}", flush=True)
    (model_path.parent / "vision_val_metrics.json").write_text(json.dumps(best, indent=2))
    return best


def load_vision(model_path: Path) -> VisionNet:
    model = VisionNet()
    model.load_state_dict(torch.load(model_path, map_location="cpu", weights_only=True))
    model.eval()
    return model


def load_thresholds(model_path: Path) -> np.ndarray:
    """Calibrated per-pattern decision thresholds (0.5 fallback)."""
    f = model_path.parent / "thresholds.json"
    if not f.exists():
        return np.full(N_PATTERNS, 0.5)
    d = json.loads(f.read_text())
    return np.array([d.get(name, 0.5) for name in PATTERN_NAMES])


@torch.no_grad()
def vision_probs(model: VisionNet, images: np.ndarray, dev=None, batch: int = 512) -> np.ndarray:
    """images: (N, 3, H, W) float32 in [0,1] -> (N, VISION_DIM) [pattern probs, dir softmax]."""
    dev = dev or device()
    model = model.to(dev).eval()
    out = []
    for i in range(0, len(images), batch):
        x = torch.from_numpy(images[i : i + batch]).to(dev)
        p_logit, d_logit = model(x)
        out.append(
            torch.cat([torch.sigmoid(p_logit), torch.softmax(d_logit, dim=1)], dim=1).cpu().numpy()
        )
    return np.concatenate(out, axis=0).astype(np.float32)
