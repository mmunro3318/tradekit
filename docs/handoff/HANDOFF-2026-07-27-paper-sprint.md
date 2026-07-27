# HANDOFF — Paper-Record Sprint (the road to T2 and the 3 live trades)

> Seed for a fresh session. Mode: sprint (tk-spec → tk-tasks → tk-implement).
> Written 2026-07-27 by CTO session; zero conversation context assumed.
> This is the CRITICAL PATH to P4 "done."

## Ratified frame (Mike + CTO, 2026-07-26 — do not relitigate)

- P4 "done" = Option A: ~30 graded paper trades with positive edge →
  T2 grant (all four `promotion_status()` criteria) → Mike runs
  `tk promote confirm` (two-man) → 3 probationary LIVE trades through the
  GATED pipeline (`live_sequence_remaining=3`). "Done" means the bot can
  SURVIVE going live, not merely trade live.
- The ladder stands UNWEAKENED. The 30-trade dial exists to vet the
  autonomous bot (the actual product). Never lower it, never hand-inject
  grants, never edit R-rule tests.
- Live execution rail already PROVEN (2026-07-26 Mike-run $5 ETH round
  trip, flat, net -$0.02). Keys live in .env (ALPACA_LIVE_KEY_ID/SECRET).
  crypto_status ACTIVE, $50 funded.

## The actual problem this sprint solves

`tk promote status`: T1, **1 of ≥30** graded, all four T2 criteria false.
The funnel emits almost no candidates: current setup scan = 4h
`macd_signal: bullish_cross` + `volume_spike: 1.5`, and crypto has been in
a broad downtrend — MACD histogram negative across the whole greenlist for
a week+ (verified real, not a bug; formulas independently cross-checked).
At this signal rate, 30 graded trades ≈ months. The sprint's job:
**more compliant candidate flow**, not looser gates.

Legitimate throughput levers (design-driven, each its own spec'd change):
1. **MTF-SCAN T-MTF-2..4** (docs/design/MTF-SCAN.md — `scan_confluence`
   verb + strategy registry; T-MTF-1 already merged).
2. **STRATEGY-PACK S2/S3/S4** (docs/design/STRATEGY-PACK.md — pullback /
   breakout / restricted reversion, exact filters + new vocab pinned,
   build order S2→S3→S4). Downtrends produce S4-style setups; a
   long-only bullish_cross funnel is structurally starved in a bear leg —
   breadth of STRATEGY, not looseness of THRESHOLD, is the honest fix.
3. More timeframes (1h=30d window is viable) and (later) more symbols.
4. Autonomous cadence: scheduled scan→thesis→paper-submit runs. Paper
   account only; Mike explicitly OK with autonomous PAPER trading
   ("you probably don't need me... only touching the paper account") BUT
   equally explicit: **no guessing/gambling while he's away** — every
   submitted paper trade must pass the full funnel (setup → sizing →
   policy verdict PASS). Zero discretionary entries. If the funnel says
   wait, we wait; report the drought, don't force trades.

## Blocking pre-work (small batches, do before volume arrives)

- **In-kind fee fix (PINNED)**: Alpaca deducts crypto fees in the ASSET
  (buy filled 0.002602483 ETH, position held 0.002595976), while
  CostModel/ledger assume USD fees (ASSUMPTIONS 144). Fix
  reconcile/CostModel before grading many paper crypto trades, or edge
  metrics will be systematically wrong. Money-path adjacent → review round
  required.
- Wound-scale migration batch (_rubric.py minor/major/fatal) is pending
  and touches grading — sequence it before or early in the sprint.

## Key mechanics for a fresh session

- Grading/series: `policy.promotion_status()` self-evaluates grants and
  demotions (read-verb-that-may-write, idempotent); series = fixed 30-day
  blocks from `series_epoch` dial; criteria = 3-of-last-4 clean +
  most-recent complete clean + ≥30 non-void + R-016 positive edge.
- Paper account: `paper:alpha` (default_account_ref dial). Alpaca paper
  keys env: ALPACA_API_KEY_ID / ALPACA_API_SECRET.
- Determinism seams for tests: `mae._runtime.get_closed_bars` / `_clock`
  only. Gate: `uv run pytest -q && uv run ruff check . && uv run mypy`.
- Commit discipline: `(red)` commits; green only on GATE: green verbatim.

## Suggested sprint shape

1. tk-spec the in-kind fee fix → implement (batch, review round).
2. tk-spec S2 pullback (long) + S4 restricted reversion (the
   regime-appropriate one) from STRATEGY-PACK → implement behind the
   existing filter vocabulary.
3. MTF-SCAN T-MTF-2 (scan_confluence) so strategies stack evidence.
4. Wire the autonomous paper cadence (scheduled task or loop) with a
   daily Mike-facing digest (trades taken, funnel attrition, series
   progress toward 30).
5. Watch promotion_status() move; report weekly series stats to Mike.
