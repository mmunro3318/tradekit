


# tradekit — ROADMAP

> Derived from [DESIGN.md](DESIGN.md) §17 (v0.2, approved 2026-07-12). Checkbox discipline: a story is checked only when its tests pass and the reviewer has signed off. Every phase ends with a **done-gate** that must be *provable*, not asserted.
> Story granularity ≈ one subagent task (single file or tight file cluster). Cite TD-n / rule IDs, don't restate them.

---

## P0 — Skeleton (audit path before money path)

**Done-gate:** a scripted event sequence appends to the ledger, `verify_chain` passes, `rebuild` is idempotent, and CI is green on Windows + Ubuntu.

### M0.1 Repo bootstrap

- [X] git init on `main`, doc baseline commit, hardened `.gitignore`
- [X] `.gitattributes` (line-ending normalization)
- [X] `pyproject.toml` — uv-managed, py3.12 pinned, deps per DESIGN §3 (P0 subset: pydantic, typer, python-ulid; dev: pytest, pytest-cov, ruff, mypy)
- [X] src-layout skeleton: `tradekit/{contracts,ledger,cli}` + module `__init__` interface stubs
- [X] Ruff + mypy config (strict on contracts/ledger/policy/thesis per TD-1/§3); private-internals import lint via TID251 (probe-verified; known per-file-ignore gap documented in pyproject — revisit with import-linter)
- [X] CI workflow: uv sync → ruff → mypy → pytest, windows-latest + ubuntu-latest matrix (first run once remote exists)
- [ ] GitHub remote created and pushed (Mike's hands: create empty repo `tradekit`)

### M0.2 `tradekit.contracts` (shared leaf; TD-3, TD-23)

- [X] `AssetRef` (symbol/venue/asset_class/tick_size) + `quantize(value, tick_size)` (G2; grid-snap fix reviewer D1)
- [X] Predicate DSL: `price_touch | price_close | time_expiry` discriminated union (§5.2)
- [X] `ThesisContract` + `EntrySpec` + `EVBlock` + `InvalidationSpec` (measurable | structural) (§5.1)
- [X] Event envelope with v1-taxonomy type validation (§6.3); typed per-event payload models land with their producing subsystems (P2/P3 — see tests/ASSUMPTIONS.md item 10)
- [X] `ProposedAction`, `Verdict`/`VerdictToken`, `RuleHit` (§5.3)
- [X] `OrderRequest` / `OrderAck` / `Fill` / `Grade` / `MarketSnapshot` / `RunManifest` (§5.3)
- [X] `json_schemas()` export (feeds `tk schema export`)

### M0.3 `tradekit.ledger` (TD-4, TD-22)

- [X] DB bootstrap: WAL, `busy_timeout`, schema migration v1 (events + FTS5) (§6.2)
- [X] `append(event)` — canonical JSON (strict, no silent coercion), length-prefixed hash preimage over all columns, bounded retry-with-jitter (TD-16)
- [X] `query(filter)` + `search(text)` (FTS5, phrase-quoted input)
- [X] `verify_chain()` (§6.2; also checks stored prev_hash linkage)
- [X] Read-model projection framework + `rebuild()` (idempotent; projections for `runs` + `config_versions` in P0, rest land with their subsystems)
- [X] `run_id` stamping from `TK_RUN_ID` (TD-20)

### M0.4 `tradekit.cli` (thin shell; TD-15)

- [X] `tk` entrypoint: `--json` flag convention, stable exit codes, `TK_RUN_ID` plumbing (env-based, read by ledger at append)
- [X] `tk schema export`
- [X] `tk ledger query|verify|rebuild`
- [X] P0 replay test: scripted sequence → chain verifies, rebuild idempotent (ring-3 harness seed, TD-18)

**P0 done-gate met 2026-07-12** (73 tests green on local Windows; CI matrix pending remote): chain verifies, rebuild idempotent, tamper on any column detected, CLI verbs live.

---

## P1 — MAE core

**Done-gate:** golden-vector suite green; `tk scan` returns real setups from live free APIs on Mike's machine; `tk regime`/`tk size`/`tk metrics`/`tk correl` operational.

### M1.1 Data layer (§9.1)

- [X] `MarketDataPort` + canonical OHLCV frame + provider rate-limiter/retry scaffold — done 2026-07-14, WIRED into providers per review H2
- [X] `cache.db` cache-aside (closed bars immutable; live bar refetch; cached-closed-prefix serve per review M5) (TD-22)
- [X] Kraken provider (OHLCV public; depth/trades deferred to first consumer) — live-smoked 2026-07-14
- [X] Alpaca data provider (equity + crypto bars; crypto response symbol-keyed per review H1; needs paper keys in .env for live use)
- [X] CoinGecko provider (global + markets; Mike's demo key in .env, verified live)
- [X] yfinance macro provider (daily batch, stale-flag degradation) — built P1C batch A per Mike's 2026-07-16 call (yfinance 1.5.1, mae/-internal); never-raise degradation pinned (ASSUMPTIONS 46). First production consumer lands with P2 regime/report narratives — documented non-gating
- [X] `tradekit.costs` v1: venue fee tables + spread/slippage model seeded from SME §5 (TD-8)

### M1.2 Indicators + golden vectors (§3, TD-18) — done 2026-07-15 (P1B)

- [X] volatility: ATR (Wilder), Bollinger, Keltner (+ true_range)
- [X] momentum: RSI, MACD, StochRSI, ROC
- [X] trend: EMA/SMA, ADX, Supertrend
- [X] volume: VWAP (UTC-day anchored), OBV, volume-ratio — CVD DEFERRED to P3 per sprint doc (needs tick trades)
- [X] structure: S/R swing levels (fractal k=2), QFL bases (simplest correct; refinements TODO-P5)
- [X] golden-vector fixtures cross-checked once against reference impls, then frozen — CTO dual-implementation gate + TA-Lib 0.7.0 external check, ASSUMPTIONS 42/43

### M1.3 Metrics & overfit gates (§9.4) — pulled forward, done by Fable 2026-07-12

- [X] Sharpe/Sortino/Calmar/PF/expectancy (net-of-costs) from trade log — conventions pinned in `mae/_metrics.py` docstring, hand-derived golden vectors
- [X] Deflated Sharpe (closed-form, in-house) + n≥30 gate + provisional penalized-Sharpe regime (G1)
- [ ] Walk-forward evaluator (2× IS/OOS flag) — MOVED to M5.2 (backtest engine, SPRINT-P5-PROP)
- [X] `compute_strategy_metrics` verb wiring incl. warnings taxonomy

### M1.4 Sizing & regime — done 2026-07-17 (P1C)

- [X] `size_position`: min(ATR-normalized, quarter-Kelly); purity signature (TD-11) — verb wired over frozen `_sizing` math; `SizingComputed` event emission lands with thesis.submit (P2), per the sprint doc
- [X] HMM regime: pinned seed (1337), persisted artifacts + sidecar, 7-day staleness refit (TD-13); pickle path-validated incl. Windows-backslash vector
- [X] Rules fallback classifier + EWMA 3σ override (G3) — override baseline = calmest state's emission params (ASSUMPTIONS 54; review round 4 caught a pooled-mean defect, now pinned by a discriminating test)
- [X] `get_correlation_matrix` + methodology per §9.1 (inner-join, `insufficient_overlap` null+warning, |r|>0.75 flags)

### M1.5 Scanner & spikes — done 2026-07-17 (P1C)

- [X] `scan_markets`: multi-symbol/multi-TF filter pipeline, regime gate (one regime call per symbol per scan; neutral = no-recommendation per ASSUMPTIONS 53) — live-smoked vs Kraken (scripts/smoke_scan.py, 3 real matches)
- [X] Composio connector spike (D17 — connectors only; timeboxed) — verdict NO for data/broker core, MAYBE for P3+ reporting side-channels; docs/research/composio-spike.md

---

## P2 — Thesis + Policy (the spine and the gates)

**Done-gate:** adversarial replay scenarios green — VOID gaming, micro-series gaming, window cherry-picking, revenge-sizing all *provably* blocked.

### M2.1 Thesis lifecycle (§10) — done 2026-07-17 (P2)

- [x] State machine (draft→submitted→reviewed→approved→active→graded/rejected/void) with event emission — GUARDED (state,event)→state transitions in _machine + projection (out-of-order events can't corrupt state; batch-B catch)
- [x] `submit`: snapshot capture, predicate resolution to absolute quantized prices, EV validation (F5) — validate-everything-then-append, transition marker last
- [x] Grading engine: bar-ordered predicate evaluation, conservative ambiguous-bar rule, `Grade` artifacts — wired over the frozen _grading core; pnl None when no fills (never fabricated, ASSUMPTIONS 71)
- [x] VOID path: measurable auto-eval; structural attestation + reviewer sign-off hook (§10.4) — refused-void leaves the attestation as audit trail; sign-off = ReviewCompleted(kind=void_signoff), P3's review module emits it
- [x] P&L attribution projection (fills → thesis/strategy_tag → `pnl_daily`) — P2 convention: grade-time attribution; FillRecorded-time refinement lands with the P3 broker

### M2.2 Policy engine (§7) — done 2026-07-17 (P2)

- [x] `_context.py` snapshot assembly from read models — anti-permissive: missing data ⇒ insufficient_context deny, fabricated-thesis-id bypass closed (ASSUMPTIONS 81)
- [x] Rules R-001…R-016 as declarative registry with WHYs; `RULES.md` generation — **Mike sign-off on WHYs + dials PENDING (last open DoD item)**
- [x] `evaluate()` pure core + verdict events + policy-version hash stamping — byte-identical verdicts, deny never silent
- [x] Promotion state machine: series accounting (fixed 30-day blocks), clean/complete flags, T0–T2 transitions, demotion triggers (TD-10) — per-account MDD base (review-round HIGH fix), log-relative projection completeness, two-man confirm rule
- [x] `halt`/`resume` + circuit breakers (R-001, R-009)
- [x] Adversarial replay scenario suite (threat-model vectors of §15 as tests) — 11 scenarios, all gates held; P3-only vectors flagged in ASSUMPTIONS 93

---

## P3 — Paper trading, review, reporting

**Done-gate:** end-to-end on paper: scan → thesis → adversarial review → gates → order → simulated fill → grade → memo, all replayable from the ledger.

### M3.1 Execution pipeline — done 2026-07-17/18 (P3)

- [x] `BrokerPort` + conformance suite (TD-6/18) — every adapter passes the same suite; token gate with thesis binding + no-newer-deny (review round 6)
- [x] PaperBroker: named accounts (TD-24 AccountConfig), market fills (mid±spread+fees, quote snapshot on the Fill), limit fills (trade-through ≥1 tick, G5; halt-gated polling per review round 6), deterministic replay
- [x] `broker.execute_order` two-phase pipeline (§8.2) — ordering guarantee pinned; deny leaves zero Order* events
- [x] `reconcile` for paper accounts — BOTH directions (broker-missing AND phantom-ledger-fill) → auto-HaltSet; $5k/$5k seed distribution = OPERATIONAL task with Mike (needs his long-term thesis content, SCOPE Pass C) — not a code box

### M3.2 Review & advisory — done 2026-07-17/18 (P3)

- [x] `LLMReviewerPort` + Codex/Gemini subprocess adapters (TD-21) — timeout/output caps; streaming caps deferred P4 (ASSUMPTIONS 141)
- [x] Attack/defense orchestration + rubric scoring + auto-fail short-circuits (§12.1) — rubric prompt is a DRAFT awaiting Mike (prompts/rubric-thesis-v1.md)
- [x] ManualBroker + `tk fill record` (advisory, D16) — never refuses, ledgers GateViolationDetected under active lockouts (F7 teeth); Kraken read-only tracking DEFERRED until Mike rotates the key
- [x] Advisory rules live: R-009 for advisory pools, R-014 cooling-off (adversarial suite covers the advisory variant)

### M3.3 Reporting, memory, research — done except two deferrals

- [x] `tk brief` (token-budgeted, salience truncation) + `tk search` (AND/phrase pinned) (memory module, TD-20)
- [x] Daily memo + readiness report + P&L snapshot templates (§12.3)
- [ ] Research-loop lead/scout prompts (D14) — DEFERRED to a Mike-paired session (tone/shape approval is his); `tk wiki add` itself is [x] done
- [ ] Derivatives provider: Kraken Futures primary, Coinalyze cross-check (G6) — remains deprioritized per Mike (futures below stocks/crypto); revisit when a scan filter needs funding/OI

---

## P4 — Live proof (MVP done-gate, D4)

**Done-gate:** 3 live trades execute, settle, reconcile vs ledger; P&L snapshot verified by a non-Anthropic model.

- [X] Alpaca paper dress rehearsal: full pipeline against real Alpaca API (order lifecycle parity) — DONE 2026-07-18: AlpacaBroker green vs the shared conformance suite; live paper rehearsal PASSED (submit→filled→fill→account); venue error taxonomy (5xx/429/malformed RAISE, never fabricate) landed same-day per review round 7; live trading structurally fail-closed (dial + live-key env + two-man rule); live_path halts refuse non-manual resume
- [ ] Mike's hands: live keys + fund $50–100 (D12) + rotate BOTH chat-pasted key pairs + approve prompts/rubric-thesis-v1.md
- [ ] Promotion flow exercised for real: readiness report → `tk promote confirm` → 3-trade budget (R-011)
- [ ] 3-trade live sequence + `reconcile` green + auto-revert
- [ ] `verify_claim` second-model verification of the snapshot (D4) — MVP COMPLETE

---

## P5-PROP — Kraken Prop program (pivot 2026-07-19)

Context: Mike holds Kraken Prop Starter Eval 1 ($5,000; MDL $150/day off
00:30 UTC balance snapshot, MDD $300 static lifetime, target $500; fees
4bps/side + 0.033%/day funding per 4h). NO API for Prop (probe-confirmed:
scripts/smoke_kraken_probe.py; zero PROP pairs in public APIs) — execution
is advisory-HUD / execution-bridge; autonomy gated on Kraken's written
stop-persistence answer. Design authority: docs/handoff/SPRINT-P5-PROP.md +
docs/research/prop-questionnaire-answers-CTO-2026-07-18.md (binding) +
docs/research/kraken-prop-report1-2026-07-19.md (venue mechanics).

### M5.1 Prop dials + evaluation barrier simulator (SPRINT-P5-PROP batch A)
- [X] AccountConfig/PolicyDials prop block (mdl/mdd/target/fees/internal buffers; None=disabled) — green 1c4cb14; Starter values shipped commented-out in config.toml (ASSUMPTIONS 143 amendment)
- [ ] R-017/R-018 wired to internal walls (50/70% MDL, 40% MDD reserve) — `prop_account_walls` resolution DONE (0.021/0.036, ASSUMPTIONS 144); PolicyContext wiring for `prop:*` accounts still open (needs its own pinned tests; fold into batch C or a wiring mini-batch)
- [X] `tradekit.prop.simulate_evaluation` Monte Carlo (absorbing barriers, ≥10k paths, seeded) — scripted + parametric green (ASSUMPTIONS 145-153); empirical mode fail-loud until pinned
- [X] Headline: `recommended_max_risk_frac` clearing ruin ≤2%/mo (Q.A.8) — ladder + monthly normalization per ASSUMPTIONS 150

### M5.2 Backtest / walk-forward engine (absorbs M1.3 open box; batches B–D)
- [ ] StrategySpec/CostModel contracts (scanner-vocabulary entries; one fee canon with M5.1)
- [ ] `mae._backtest` bar loop (candle-close signals, next-open entry, stop-wins-ambiguous, delayed-entry stress)
- [ ] Anchored walk-forward driver + embargo
- [ ] Experiment registry (append-only; feeds n_trials → DSR deflation honestly)
- [ ] Kraken OHLC provider + historical CSV ingest + tick collector started
- [ ] Baseline suite on BTC/ETH: buy-and-hold, random-entry-same-exit, SMA trend (Q.L.207)

### M5.3 Execution Bridge + advisory HUD — BRIDGE-UIA (design v2 4ad7d85; may interleave with M5.2)
Feature bridge-read (SPEC-bridge-read.md, branch feature/bridge-read):
- [X] T1: bridge contracts payloads
- [X] T2: bridge skeleton (errors/session/elementmap/grade/import guard)
- [X] T3: panel text parser
- [ ] T4: read verbs over FakeUiaSession
- [ ] T5: tk bridge snapshot CLI
- [ ] T6: pywinauto session + probe script + dep group
- [ ] T7: live probe run + artifact + fixture re-freeze (MIKE-GATED: app open)

### M5.3b Execution Bridge write path (feature 3+4, after bridge-read + probe grade A/B)
- [ ] `BridgeBroker` port: outbox order tickets / inbox fill reports, executor-agnostic
- [ ] Reconcile integration + screenshot cross-check protocol
- [ ] Blocked-external: Kraken support answers (API access; stop persistence = autonomy gate)

### M5.4 Strategy #1 (pullback-continuation family, Q.E.56)
- [ ] tradekit Substrate Contract doc (CTO) for GPT design sequence
- [ ] Strategy #1 spec → M5.2 validation → Q.M.256 robustness gates → paper

## P5+ — Deferred (designed, not built)

- [ ] FastMCP server wrappers + skill descriptors (TD-15)
- [ ] CDP Server Wallet adapter (D3)
- [ ] On-chain oracle behind `OnChainDataPort` (D13; productizable)
- [ ] Embeddings/RAG memory upgrade (D15)
- [ ] Research-loop scheduling (Cowork task, D14)
- [ ] Red-team strategy tournaments (SCOPE vision)
- [ ] Options asset class (Mike: maybe; Alpaca supports)
- [ ] Phase-2 hardening: single-writer key-holding daemon (TD-19)
