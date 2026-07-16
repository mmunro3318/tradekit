# cc-dev-log

Chronological dev log. Newest entry first. One entry per working session; keep entries terse — decisions and deltas, not narration.

## 2026-07-16/17 (Fable) — P1C regime/scanner/sizing/correlation COMPLETE (M1.4, M1.5, P1 done)

- **All four remaining MAE verbs live**: size_position (wired over frozen _sizing),
  get_correlation_matrix, get_regime (HMM + EWMA override + rules fallback),
  scan_markets. Plus story 0 (Mike-approved): yfinance macro provider (never-raise
  degradation, ASSUMPTIONS 46) — closes M1.1's last box. Deps: yfinance 1.5.1,
  pandas 3.0.3, hmmlearn 0.3.3, scipy 1.18.0 — all mae/-internal.
- **The sprint's one new design**: `mae/_runtime.py` ambient data seam (verb
  signatures are pinned portless) — clock/provider-factory/cache-path indirections,
  "/" routing (Kraken vs Alpaca), and THE lookahead chokepoint: get_closed_bars
  strips the live bar so no verb can ever leak an unclosed candle downstream.
- **Three batches, four-stage each** (addendum 6e8b8a9): A = macro+runtime+sizing+
  correlation (030a520→faaa151); B = regime (a41f352→3974493); C = scanner+
  get_closed_bars+smoke (a9ea52d→5711bac). Schema ambiguities escalated by TDD
  agents and CTO-ratified in ASSUMPTIONS 47/51-54/57 (incl. "neutral" as a
  rules-only fourth regime state = anti-permissive default).
- **CTO-gate catches (pre-review)**: batch-A runtime test wrote fixture bars through
  the REAL data/cache.db (closed bars never invalidate → poisoned real scans; six
  fake rows purged, _cache_path seam added — standing rule: every file-writer gets
  a path seam); live smoke_scan crashed on Kraken pair-map gaps → Mike's universe
  (SOL/LINK/NEAR/TAO/EIGEN) mapped, result keys verified against the live endpoint.
- **Review round (Opus, verdict FIX-FIRST — the pre-registered override gate paid
  off)**: HIGH — EWMA override used the POOLED vol mean instead of the calmest
  state's emission mean (threshold ~4.8x inflated → under-fires exactly when vol
  explodes); invisible to the 0.25-spike test which cleared either threshold; fixed
  with a discriminating marginal-spike test (fails on pooled, passes on emission
  mean, proved both directions). MED: 3 uncovered scanner filter branches (now 7 new
  pinning tests). LOWs: macro degraded-path could still raise; monitor-less HMM
  defaulted to converged. Fixes e988c01→b4885a1. Round details agent-metrics #4.
- Composio spike (D17): verdict NO for data/broker core, MAYBE for P3+ reporting
  side-channels — docs/research/composio-spike.md.
- Alpaca PAPER keys landed in .env (account PA3YTZDZ9SXE, verified vs live data API,
  IEX feed). Two dev agents died at usage caps mid-task; both recovered cleanly
  (work was already on disk — check git status + pytest before assuming loss).
- **Final: 338 tests green, ruff clean, mypy clean. P1 (MAE core) COMPLETE.**
  Live: smoke_scan returns 3 real matches (ETH/SOL/LINK dailies via Kraken).
- Next: SPRINT-P2 (thesis lifecycle + policy engine). Note for P2: walk-forward
  evaluator (M1.3 leftover) lands with the backtest engine; strategy-tag registry
  should re-derive _scanner._TAG_STRATEGY/_regime._STRATEGY_TAGS (ASSUMPTIONS 57f).

## 2026-07-15 (Fable) — P1B indicators + golden vectors COMPLETE (M1.2)

- **17 indicators** in `mae/_indicators/{volatility,momentum,trend,volume,structure}.py`,
  pure functions, uniform None-alignment contract, signatures/lookbacks pinned by a
  CTO addendum in the sprint doc (31efe59) BEFORE dispatch. numpy added (stays in mae/).
- **Golden-vector freeze gate (the sprint's point, new process):** TDD agents derived
  vectors via independent from-spec scripts (pandas_ta rejected — its adjust=False
  seeding contradicts the pinned SMA-seed Wilder/EMA convention); CTO then verified
  every value with a SECOND independent implementation + TA-Lib 0.7.0 external
  cross-check (throwaway venv) before committing red. Exact TA-Lib matches: sma, ema,
  rsi, roc, bollinger, TR[1:], macd-line-via-EMAs, obv (modulo pinned obv[0]=0), DI/ADX
  divergences hand-reproduced as TA-Lib's 1..13-seed quirk. ASSUMPTIONS 39-43; vectors
  now FROZEN (regeneration requires redoing the gate).
- **Four-stage workflow, two batches:** tdd-p1b → dev-p1b (stories 1-3, c5e101a →
  08fcf70); tdd-p1b-2 → dev-p1b-2 (stories 4-5, 08cc8f7 → 61fb78a). All Sonnet.
  One dev defect, caught by the frozen goldens pre-commit: ADX Wilder smoother seeded
  with the SUM under the average-form recurrence (invisible at seed index — ratio of
  sums == ratio of averages — divergent after); dev-p1b initially blamed the golden,
  STOPped correctly, fixed on CTO push-back with exact arithmetic. Commandment 4's
  record intact. (Agent also died at a usage cap mid-fix; fix had already landed.)
- **Review round (Opus): verdict PASS — first zero-HIGH round in three sprints.**
  Reviewer independently recomputed 11 indicators against the goldens. 3 LOW fixed
  same-day (e519719): QFL gloss, degenerate-param guards (period<1/k<1 now ValueError),
  close-out items. Details in docs/reviews/agent-metrics.md round 3.
- CVD deferred to P3 (tick trades); CTO pins of record: supertrend initial direction
  (ASSUMPTIONS 41), ADX seed window (40), vwap UTC-day anchor + qfl same-bar crack (43).
- **Final: 258 tests green, ruff clean, mypy clean.** ROADMAP M1.2 all boxes checked.
- Next: SPRINT-P1C (regime/scanner/sizing — needs hmmlearn + the deferred yfinance
  macro provider decision). Mike's hands: still only the optional Alpaca paper keys.

## 2026-07-14/15 (Fable) — P1A data layer COMPLETE (stories 3-8 + review round)

- Keys landed: CoinGecko demo + Kraken read-only in `.env` (gitignored; CoinGecko
  verified live). Kraken key was pasted in chat — consider rotating before P3 live use.
- **Four-stage workflow, two rounds**: tdd-p1a (Sonnet) → dev-p1a (Sonnet) for stories
  3-5 (cache/Kraken/ratelimit, commits 7643c29→70121e9); tdd-p1a-2 → dev-p1a-2 (both
  Sonnet) for 6-8 (Alpaca/CoinGecko/conformance + live smoke, d051db2→e85e083).
- **Review round (Opus, verdict FIX-FIRST — third round running with HIGH catches):**
  H1 Alpaca crypto endpoint is multi-symbol (`bars` keyed by symbol) — flat-list mock
  hid a live-API crash; H2 ratelimit module was an orphan (nothing called it); M3 4xx
  mistyped as ProviderUnavailable; M4 malformed-200 bodies raised untyped; M5 cache was
  write-only whenever a live bar was in range (i.e. always, in production). Fix agent
  (Sonnet, fix-p1a; survived a usage-cap interruption mid-task and was resumed from
  transcript) landed red 48c5bdd → green 3fae4c9. ASSUMPTIONS 27-38 added across rounds.
- Ratelimit now wired: providers take injected clock/sleeper, token bucket + retry on
  every call; 4xx never retries; timeouts retry. Cache serves cached closed prefix and
  fetches only the uncovered suffix. Smoke re-run live post-wiring: 720x 1h BTC bars OK.
- **Final: 178 tests green, ruff clean, mypy clean.** M1.1 boxes checked except
  yfinance macro provider (deferred per sprint doc; revisit at P1C).
- Next: SPRINT-P1B indicators + golden vectors. Mike's hands: Alpaca PAPER keys
  (app.alpaca.markets) into .env as ALPACA_API_KEY_ID/ALPACA_API_SECRET when convenient
  (needed for Alpaca live smoke; tests don't need them).

## 2026-07-13 (Fable) — candlerl experiment: vision pattern classifier + PPO trader

- **New isolated sub-project `experiments/candlerl/`** (own uv env, py3.11, torch 2.11
  cu128 — RTX 5060 Ti/Blackwell works). Two decoupled models per the hierarchical
  master/slave plan Mike supplied: rendered 32-bar chart (128px) → CNN (11-pattern
  multi-label + 3-class 5-bar direction heads) → precomputed per-bar vision vectors +
  25 numeric indicators → SB3 PPO {flat,long,short}, reward = pos·logret − 10 bps·turnover.
- **Key finding (the expensive lesson)**: TA-Lib-style pattern labels are NOT learnable
  from images unless computed on **pixel-grid-quantized** prices — sub-pixel thresholds
  put identical-looking charts in different classes (macro-F1 0.34). After quantization +
  per-class val-calibrated thresholds: test macro-F1 0.46 — doji 0.87/engulfing 0.76-0.78
  strong, hammer family ~0.45 (relational judgments vs trailing averages), 3-candle stars
  weak (val support 9-47). Improvement paths in HANDOFF B8.
- **RL round 1 churned** (0.76 flips/bar → −38% cost drag, −21.6% mean vs +94.5% B&H on
  2024→2026 test). Round 2: training cost 25 bps (eval stays 10), ent_coef 0.001, γ 0.99.
- Rule-based detectors verified against TA-Lib C source (research agent); Stooq keyless
  daily data (22 tickers, 136.6k bars); leak-safe chrono splits with HORIZON embargo;
  43 tests green (TDD), review-agent pass fixed truncated-vs-terminated PPO bias + 6 more.
- CLI: fetch/build/train-vision/bridge/train-rl/evaluate/demo/predict (--ticker/--csv/
  --image). Paper suggestions only. README + HANDOFF.md (backlog B1–B9) for successors.

## 2026-07-12 (Fable bonus hour) — grading engine core, sizing math, cost model

- **Grading engine** (`thesis/_grading.evaluate_criteria`, P2 story-2 core, pre-built): pure arithmetic per DESIGN §10.2 with every ambiguity resolved against the agent — same-bar priority failure > invalidation > success (VOID can't erase a loss), stop-first on stop+target bars, lookahead guard inside the engine, per-predicate `by` deadlines never resurrect, time_expiry fires at deadline (an inverted-logic bug I caught pre-commit and pinned with a test). 12 tests. MVP constraint: one timeframe per thesis (ASSUMPTIONS 24).
- **Sizing math** (`mae/_sizing.py`, P1C story-1 core): Kelly with negative-edge clamp + ATR position identity (stopped out = lose exactly risk_usd). My own first golden vector was wrong by 3e-5 — re-derived by exact fractions (f* = .574 − 71/262); implementation was right. Canonical doc's 0.2102 example remains wrong.
- **Cost model** (`tradekit.costs`, P1A story-2): TD-8 shared friction tables (Alpaca equity/crypto, Kraken crypto), slippage-free under $100, unknown venues die loudly. Provisional until P4 live fills (ASSUMPTIONS 26).
- **Contracts**: Bar (OHLC-coherence validator), BarSeries (strict ascending), Friction, CriteriaOutcome, TIMEFRAME_SECONDS — P1A story-1 done. 28 schemas exported.
- ASSUMPTIONS 23–26 added (incl. the temporary internal-test exception — re-point + TID251-ban when verbs land). Sprint docs P1A/P1C/P2 updated with DONE markers. **Final: 108 tests green, ruff + mypy clean.**

## 2026-07-12 (final Fable session) — metrics core + full handoff package

- **Fairy-godmother handoff**: Fable 5 access ending; project handed to Opus/Sonnet/Haiku.
- Pulled M1.3 forward and completed it personally (the math most likely to be silently botched): `mae.compute_strategy_metrics` — pnl/win-rate/expectancy/PF, trade-level Sharpe+Sortino with pinned annualization convention (√(trades/yr) over log span), drawdown vs peak equity, Calmar, in-house Bailey–López de Prado PSR/DSR with n_trials selection penalty, G1 regime (DSR n≥30 / penalized 10–29 / descriptive <10), deterministic edge_verdict table. Conventions BINDING via `_metrics.py` docstring + 10 hand-derived golden-vector tests. `TradeRecord`/`StrategyMetrics` contracts added (24 schemas). **83 tests green, ruff+mypy clean.**
- Wrote **README.md** (setup, usage, current capability) and the **handoff package** in `docs/handoff/`: HANDOFF-PRIMER (ten working rules, model role assignments, state of world, known traps, session bootstrap checklist) + sprint docs P1A (data layer + costs), P1B (indicators + golden vectors), P1C (regime/scanner/sizing — incl. hand-derived Kelly vectors; canonical doc's example arithmetic is WRONG, ours is right), P2 (thesis/policy — Opus-required stories flagged), P3–P4 (paper→live).
- Remaining Mike's-hands: GitHub remote (URGENT — no offsite backup), CoinGecko key, Kraken read-only key (P3), Alpaca live keys (P4 only).
- Successor sessions start at HANDOFF-PRIMER §6 bootstrap checklist. Active sprint: **P1A**.

## 2026-07-12 (evening) — git init; ROADMAP; P0 COMPLETE (done-gate met)

- `git init` on main; baseline commit of doc set. `.gitignore` hardened (.env, data/, *.db never committable); `.gitattributes` normalizes line endings.
- **ROADMAP.md** written (P0–P5, milestone/story checkboxes, done-gates per phase).
- **P0 built via the four-stage workflow**: CTO pinned interfaces → TDD team (agent tdd-p0) wrote 38 failing tests + 19 ratified ASSUMPTIONS → dev team (dev-p0) implemented contracts + ledger to green → reviewer (reviewer-p0) verdict FIX-FIRST with 9 defects, all verified by execution.
- Notable review catches: **D1 quantize matched tick exponent, not grid** (0.05/0.5/5 ticks passed through un-quantized — falsified the G2 guarantee); D2 naive datetimes read as machine-local time in query bounds; D3 hash-preimage delimiter forgeable via control chars in identity fields; D5 the deep-module lint wasn't actually enforcing. All fixed by CTO same session; enforcement probe-verified. Agent metrics started at docs/reviews/agent-metrics.md (tdd-p0: B+, dev-p0: B).
- M0.4: `tk schema export` (22 schemas → docs/schemas/), `tk ledger verify|rebuild|query`, P0 replay done-gate test. **Final: 73 tests green, ruff clean, mypy clean (strict flags on contracts/ledger), real-CLI smoke `chain OK`.**
- ASSUMPTIONS.md now 22 items (20–22 added in fix round). Commits: 7f37184 → 7768e74 → d446ffb (red) → 5f93f15 (green) → c31cbf1 (fixes) → this.
- Next: P1 MAE core (data layer first — Kraken needs no key; CoinGecko demo key is Mike's remaining hands-item, plus creating the GitHub remote for first CI run).

## 2026-07-12 (later) — Adversarial review incorporated; DESIGN.md → v0.2

- Mike approved all v0.1 decisions incl. the three §18 asks (TD-10 promotion tightening, $25 live cap, advisory cooling-off). Confirmed rolling our own paper engine; futures *signals* deprioritized below stocks/crypto (we never trade futures — it's positioning data for spot theses); options = "maybe, later" → P5+ deferred list.
- Gemini adversarial review (Codex usage-capped) archived verbatim with dispositions at `docs/research/gemini-adversarial-review.md` (G1–G6).
- Accepted: G1 DSR gates only at n≥30/strategy, provisional penalized-Sharpe regime below (TD-14); G2 tick-size `quantize` at MAE boundary (new TD-23); G3 EWMA 3σ vol override on stale HMM (TD-13); G5 limit fills need trade-through ≥1 tick; G6 derivatives chain = Kraken Futures → Coinalyze → Binance, implementation → P3.
- **Partially rejected G4** (in-process write queue): wrong topology — tradekit is many short-lived CLI processes, not one threaded process. Kept: bounded retry-with-jitter on `append`; scouts write wiki files, not events. Escalation stays the Phase-2 daemon (TD-16).
- All three former Perplexity questions (Q1–Q3) resolved by the review; none open.
- Answered Gemini's closing question by specifying correlation methodology in DESIGN §9.1 (30d Pearson, daily log-returns, UTC inner-join, ≥20 overlap else `insufficient_overlap` → unmeasured ≠ pass).
- Next: ROADMAP.md, then P0 implementation. Repo still needs `git init` + GitHub remote (Mike's call to make now).

## 2026-07-12 — Pass B: DESIGN.md produced (Claude Code, Fable)

- Read all Pass-A inputs: SCOPE.md (D1–D17), Perplexity SME pass (F1–F7), canonical MAE doc.
- Wrote **docs/DESIGN.md** — full architecture doc: TD-1…TD-22 decision register, tech stack, 7 deep modules + 2 shared leaves + 2 thin shells, contracts (thesis contract + predicate DSL), event-sourced hash-chained ledger DDL, policy rules catalog R-001…R-016 with WHYs, promotion state machine (series hardened per SME F2/F3), two-phase order pipeline owned by `broker.execute_order`, own PaperBroker (TD-7), MAE port with derivatives-provider fallback chain, threat model, three-ring test strategy, build phasing P0–P5.
- Notable overrides of SCOPE (all flagged inline): promotion series locked to fixed 30-day blocks/≥10 trades/≥30 total (F2/F3); paper daily trade cap 20/day (anti-gaming); CoinMarketCap dropped.
- Key risk surfaced: **Binance fapi is US-geo-blocked (HTTP 451)** — canonical MAE's primary derivatives source; made derivatives a pluggable port, fallback question queued for Perplexity (DESIGN §18 Q1).
- Ran a cold-read consistency review via subagent: 20 defects found (2 HIGH), all fixed same-session.
- Next: Mike reviews DESIGN.md (§18 has 3 decisions for him + paste-ready Perplexity script) → adversarial review via Codex/gstack → ROADMAP.md → P0 implementation.

Blockers for Mike (from SCOPE §8, still open): CoinGecko demo key, Kraken read-only key, GitHub repo `tradekit` + `git init` (folder is not a git repo yet).
