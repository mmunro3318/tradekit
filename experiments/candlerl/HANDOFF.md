# candlerl HANDOFF — state, gaps, backlog

Written by Fable (final session, 2026-07-13) for Mike + follow-on models (Opus/Sonnet/Haiku).
Read README.md first for architecture and pipeline. Everything below is ordered by value.

## What is DONE and verified
- 39 unit tests green (`uv run pytest`): pattern geometry vs TA-Lib-derived thresholds,
  feature causality + price-scale invariance, renderer determinism, env reward arithmetic,
  split embargo. TDD throughout — trust these as the spec.
- Full pipeline runs end-to-end via CLI (fetch → build → train-vision → bridge →
  train-rl → evaluate → demo/predict). Results in `artifacts/reports/` (evaluation.md /
  evaluation.json / demo/).
- Data cached in `artifacts/data/*.parquet` (22 tickers, Stooq daily, through 2026-07).

## Known limitations (accepted for the prototype)
1. **Vision model only understands its own renderer.** TradingView/exchange screenshots
   will be out-of-distribution. Backlog: augmentation pass (candle width/color/background
   jitter, axis/gridline overlays) or a screenshot-normalization preprocessor.
2. **Image-only `predict --image` uses a direction heuristic**, not the PPO policy —
   indicator features aren't recoverable from pixels. Backlog options: (a) train a second
   vision-only PPO policy (cheap: reuse `_rl.py` with bridge-only features), or
   (b) OCR/parse own-format renders back to OHLC.
3. **Binary position sizing** (±1/0). The DeepSeek plan's continuous `Box(-1,1)` sizing is
   a drop-in change: swap `spaces.Discrete(3)` for `Box` in `_env.py`, make reward use the
   continuous position, retrain. Kelly/ATR sizing already exists in tradekit `mae._sizing`.
4. **RL beating buy-and-hold is NOT guaranteed** — the direction signal in daily bars is
   weak; the honest deliverable is classification + a cost-aware policy. Judge the RL leg
   by Sharpe/drawdown vs buy-and-hold in `evaluation.md`, not by total return alone.
5. **No walk-forward retraining** — single chronological split. Backlog: rolling
   train/test folds, per-regime evaluation.
6. **Direction-label threshold is fixed** (±1% 5-bar log return) — crypto and stocks get
   the same bucket edges. Backlog: vol-scaled thresholds (e.g., ±0.5×ATR).

## Backlog (priority order)
- B1: Continuous position sizing (see #3) + drawdown penalty term in reward.
- B2: Render augmentation + external-screenshot robustness (see #1).
- B3: Vision-only policy head for image-only inputs (see #2).
- B4: Baselines for the paper: pattern-rules-only strategy, direction-head-only strategy
  (buy if p(up)>0.6), vs PPO — quantifies what RL adds. `_rl.rollout` makes this ~30 lines.
- B5: Intraday bars (Stooq has hourly for some symbols; Kraken public API for crypto —
  note Binance fapi is US-geo-blocked, see tradekit docs G6).
- B6: Attention/saliency maps (Grad-CAM on VisionNet trunk) for interpretability.
- B7: ONNX export for Node.js deployment (the original ask mentioned JS; export both
  models with `torch.onnx.export` + `sb3` policy extraction).
- B8: Vision accuracy on the hammer family (~0.45 F1) and 3-candle stars (rare, F1 0.2-0.3):
  (a) render at 224px (more pixels per candle; slot width 6.9px vs 3.9px),
  (b) replace GAP with spatial attention or add coordinate channels — the failure mode is
  relational (shadow vs trailing-10 average range) not textural,
  (c) oversample rare patterns harder + synthetic pattern injection (paste rule-perfect
  stars into real context windows) to fix support counts of 9-47 in val.
- B9: Vision best-checkpoint selection should combine pattern F1 + direction accuracy
  (dir head regressed to 0.41 at the checkpointed epoch; ~0.435 was reachable).

## Deferred code-review findings (from Fable's review agent, all minor)
- Sharpe annualizes with √252 for crypto too (BTCUSD/ETHUSD trade 365d/y) — metrics
  slightly understate crypto Sharpe. `_rl.backtest_metrics`.
- `MultiTickerEnv` samples tickers uniformly, over-weighting short histories per bar;
  weight the draw by segment length. Also guard the empty-segments case.
- `backtest_metrics` counts a long→short flip as 2 trades (it is 2 units of turnover;
  fine, but document when reporting).
- `build_image_dataset` with a partial `caps` dict silently drops splits; iterate a
  canonical ("train","val","test") tuple instead.
- Vision best-checkpoint selection uses pattern macro-F1 only; the direction head may
  regress in the saved epoch. Consider `macro_f1 + 0.5*dir_acc`.
- Engulfing trend filter measures trend up to and including the engulfed candle
  (classical definitions vary; stars measure strictly before candle1). Intentional,
  documented here for consistency hunters.

## Operational notes for lesser-model sessions
- ALWAYS run `uv run pytest` before and after changes; do not touch `_env.py` reward math
  or `_dataset.py` split logic without adding a failing test first (Mike's TDD rule).
- Retraining: `train-vision` ~ minutes on the RTX 5060 Ti; `bridge` ~2-4 min;
  `train-rl` ~15-30 min CPU. `build` only needs re-running if renderer/labels change —
  delete `artifacts/dataset/` first (memmaps are overwritten by shape, stale otherwise).
- `artifacts/` is gitignored (≈4 GB). Models are small (vision.pt ~6 MB, ppo ~1 MB) —
  copy them if you need to preserve a trained state before experimenting.
- Stooq occasionally rate-limits; cached parquet means you rarely refetch. `fetch
  --refresh` re-downloads everything.

## Results snapshot (end of Fable's session, 2026-07-13)
Full details: `artifacts/reports/evaluation.md` + `artifacts/reports/demo/demo_report.md`.

**Vision (test, 12k windows, ≥2024, calibrated thresholds):** macro-F1 **0.463**
(val 0.482 — no overfit). Per-pattern: doji 0.87, bearish engulfing 0.78, bullish
engulfing 0.76, hammer family 0.40–0.46, morning/evening star 0.21–0.28 (val support
only 9–47 — see B8). Direction head 40.6% (3-class; barely above majority — daily-bar
forward returns are genuinely noisy; this is honest).

**RL (test 2024-01→2026-07, 10 bps costs):** round 1 churned (0.76 flips/bar, −38% cost
drag, mean −21.6%). Round 2 (trained at 25 bps, ent 0.001, γ0.99): mean **+11.8%**,
0.43 flips/bar, long-tilted (57%/8% long/short); winners NVDA +190% (Sharpe 1.05),
IBM +92%, CAT +89%; median Sharpe −0.2 vs buy-and-hold mean **+94.5%** in a strongly
bullish period. Verdict: the policy is cost-aware and functional but does NOT beat
buy-and-hold on this period — consistent with the weak direction signal, and reported
honestly rather than tuned until it flattered. Next lever: B4 baselines, then B1 sizing;
consider raising train cost to 50 bps or adding a minimum-hold constraint to push churn
below ~0.2/bar.

**Demo (12 random test windows):** every rule-truth pattern recovered; extra predictions
are geometrically adjacent shapes (doji↔hanging_man). Charts in reports/demo/*.png.
