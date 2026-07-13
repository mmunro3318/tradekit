# candlerl — vision candlestick classifier + PPO trading policy

Self-contained experiment (isolated from tradekit's core deps). Two decoupled models:

1. **VisionNet** (compact CNN, ~1.5M params, trained from scratch on GPU): consumes a
   rendered 32-bar candlestick chart (128×128 RGB), outputs **11 pattern probabilities**
   (doji, hammer, inverted hammer, hanging man, shooting star, bullish/bearish engulfing,
   morning/evening star, three white soldiers/black crows) plus a **3-class 5-bar
   forward-direction** head. Labels come from rule-based detectors implementing TA-Lib's
   canonical thresholds (verified against `ta_global.c` / `ta_CDL*.c`), with classic
   trend-context requirements added back. Detectors run on **pixel-grid-quantized**
   prices (`_render.quantize_prices`), so a label is a pure function of the rendered
   image — first-round training proved sub-pixel thresholds are unlearnable (macro-F1
   0.34) because visually identical charts carried different labels.
2. **PPO policy** (SB3 MlpPolicy [256,128]): observes `[25 numeric indicator features |
   14 vision probabilities | current position]` and picks {flat, long, short} per bar.
   Reward = position × log-return − 10 bps × turnover. Vision outputs are **precomputed
   per bar** ("the parquet trick") so RL training is pure-numeric and fast.

**Paper trading only.** The CLI suggests actions; nothing ever touches an exchange.

## Design decisions (the "hard questions", answered)

- **Rendered charts, not GAF**: the acceptance test is "load candlestick chart samples" —
  so the vision model consumes the same deterministic renders it was trained on
  (`_render.py` builds both training data and inference inputs; zero train/serve skew).
- **From-scratch CNN, no ImageNet transfer**: labels are a deterministic function of the
  rendered geometry (all detection context — trailing-10 body/range averages, 5-bar trend —
  fits inside the 32-bar window), so a small CNN learns them directly; transfer weights add
  download/licensing friction for no gain at this image size.
- **Weak supervision is intentional**: the CNN distills the rule-based detectors into a
  probabilistic classifier that also works from pixels alone; the direction head learns a
  (noisy) forward-return signal the rules don't contain.
- **Discrete actions** {flat, long, short} match the ask ("exit, short, long, nothing");
  position sizing is backlogged (see HANDOFF).
- **Leak control**: chronological splits (train < 2023-01-01, val 2023, test ≥ 2024-01-01)
  with a `HORIZON`-bar embargo at each boundary; features are strictly causal
  (tested: `test_features_are_causal`).
- **Data**: Stooq daily OHLCV (keyless, 20 stocks 2000→present + BTC/ETH), yfinance
  fallback, cached to parquet in `artifacts/data/`.

## Pipeline

```bash
cd experiments/candlerl
uv sync                          # torch cu128 (RTX 50xx OK), SB3, gymnasium
uv run candlerl fetch            # cache daily OHLCV (Stooq)
uv run candlerl build            # render labeled image dataset (memmaps, ~3 GB)
uv run candlerl train-vision     # ~minutes on GPU; saves artifacts/models/vision.pt
uv run candlerl bridge           # precompute per-bar vision vectors for all tickers
uv run candlerl train-rl         # PPO 1.5M steps on CPU; saves ppo_trader.zip
uv run candlerl evaluate         # vision test metrics + RL backtest vs buy&hold
uv run candlerl demo --n 12      # sample test charts -> PNGs + report
```

## Inference

```bash
uv run candlerl predict --ticker AAPL        # latest cached window, full RL action
uv run candlerl predict --csv my_window.csv  # open,high,low,close[,volume][,date]
uv run candlerl predict --image chart.png    # classification + direction heuristic
```

`--image` gives pattern/direction probabilities only plus a heuristic suggestion — the RL
policy also needs indicator features that can't be recovered from pixels; use
`--csv`/`--ticker` for the real policy action.

Tests: `uv run pytest` (39 tests: pattern geometry, feature causality/scale-invariance,
renderer determinism, env reward arithmetic, split embargo).

See `HANDOFF.md` for known gaps and the backlog.
