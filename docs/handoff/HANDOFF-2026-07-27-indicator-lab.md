# HANDOFF — Indicator Lab (sift wheat from chaff, teach while testing)

> Seed for a fresh session. Mode: exploration/research fork, NOT production
> code. Mike co-pilots this one live. Written 2026-07-27 by CTO session
> (Fable); zero conversation context assumed.

## Mission

Mike wants to (a) understand what each indicator *means* and how indicators
correlate with each other and with trends, and (b) systematically evaluate
NEW candidate indicators/strategies for the scanner — separating signal from
folklore. He is running Perplexity deep-research reports on indicators in
parallel; expect pasted reports as input. Your job: adjudicate them against
DATA, not vibes.

## Ground truth available (all local, all free)

- **90 days of 4h OHLCV** per greenlist pair via `mae` provider chain
  (Kraken REST; 720-candle/interval cap — ladder 15m=7.5d/1h=30d/4h=120d/1d=720d).
- **Tick data**: `D:\tradekit-data\ticks\<PAIR>\<date>\trades-<HH>.parquet`
  (Kraken WS + REST backfill; gap-free from each pair's first hour,
  2026-07-19 onward for the oldest).
- **Order books ×3 venues**: `D:\tradekit-data\books\<venue>\...` (kraken
  via ticks tree, binance.us 7 pairs, coinbase 11 pairs; top-20 depth,
  1 Hz, schema ts + bid/ask_price/qty_1..20). Started 2026-07-26 — shallow
  history, growing ~24 GB/month.
- **Indicator implementations** (formula-verified 2026-07-25 against
  StockCharts/Tulip references — trust them): `src/tradekit/mae/_indicators/`
  (momentum: rsi/macd; volatility: atr/bollinger/keltner; volume:
  volume_ratio). Conventions: Wilder seeds, SMA-seeded EMA, population stdev.
- **Scan audit log** (`uv run tk hud --equity N --audit exhaustive`) — the
  teaching instrument: per-gate purpose/reading/vars lines were built
  precisely for Mike's learning loop. Extend it before building anything new.

## Method (CTO-pinned)

1. Experiments live in `experiments/indicator-lab/` — NEVER in `src/`.
   Promotion to the scanner is a separate spec'd batch with tests.
2. For each candidate indicator: implement against the same list[float|None]
   conventions; compute over the full greenlist history; measure
   (i) correlation with existing indicators (redundancy check — an indicator
   correlated >0.9 with RSI teaches nothing new), (ii) forward-return
   stratification (does the signal's firing cohort differ from base rate?),
   (iii) stability across pairs/timeframes.
3. House lesson (PAXG probe, dev-log 2026-07-19): run the NEXT-PERIOD-ENTRY
   check on every backtest before believing it — same-bar entry is how a 96%
   win rate turned out to be an artifact.
4. Teaching duty: every experiment ends with a Mike-facing plain-English
   summary (what the indicator measures, what values mean, when it lies) —
   the house pattern from docs/primers/.
5. Perplexity reports are HYPOTHESIS SOURCES, not authorities: extract
   testable claims, test them, grade the report.

## Non-goals

- No scanner/filter changes in src/ from this fork.
- No strategy goes near paper/live money without the tk-spec → tk-implement
  path and CTO+Mike sign-off (see the parallel paper-sprint thread).

## First actions

1. Read docs/design/MTF-SCAN.md + docs/design/STRATEGY-PACK.md (S2 pullback /
   S3 breakout / S4 reversion already designed with exact filters — evaluate
   candidates AGAINST these, avoid reinventing).
2. Build the correlation matrix of EXISTING indicators over the greenlist
   first — it's the baseline every new candidate must beat, and it's the
   perfect first teaching artifact for Mike.
