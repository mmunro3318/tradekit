


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
- [ ] yfinance macro provider (daily batch, stale-flag degradation) — DEFERRED per sprint doc "defer if fragile"; revisit at P1C regime work
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
- [ ] Walk-forward evaluator (2× IS/OOS flag) — lands with the backtest engine (P1C follow-on; bar-based, not trade-log-based)
- [X] `compute_strategy_metrics` verb wiring incl. warnings taxonomy

### M1.4 Sizing & regime

- [ ] `size_position`: min(ATR-normalized, quarter-Kelly); purity signature (TD-11); `SizingComputed` event
- [ ] HMM regime: pinned seed, persisted artifacts, weekly refit schedule (TD-13)
- [ ] Rules fallback classifier + EWMA 3σ override (G3)
- [ ] `get_correlation_matrix` + methodology per §9.1 (inner-join, `insufficient_overlap`)

### M1.5 Scanner & spikes

- [ ] `scan_markets`: multi-symbol/multi-TF filter pipeline, regime gate
- [ ] Composio connector spike (D17 — connectors only; timeboxed, outcome logged to wiki)

---

## P2 — Thesis + Policy (the spine and the gates)

**Done-gate:** adversarial replay scenarios green — VOID gaming, micro-series gaming, window cherry-picking, revenge-sizing all *provably* blocked.

### M2.1 Thesis lifecycle (§10)

- [ ] State machine (draft→submitted→reviewed→approved→active→graded/rejected/void) with event emission
- [ ] `submit`: snapshot capture, predicate resolution to absolute quantized prices, EV validation (F5)
- [ ] Grading engine: bar-ordered predicate evaluation, conservative ambiguous-bar rule, `Grade` artifacts
- [ ] VOID path: measurable auto-eval; structural attestation + reviewer sign-off hook (§10.4)
- [ ] P&L attribution projection (fills → thesis/strategy_tag → `pnl_daily`)

### M2.2 Policy engine (§7)

- [ ] `_context.py` snapshot assembly from read models
- [ ] Rules R-001…R-016 as declarative registry with WHYs; `RULES.md` generation
- [ ] `evaluate()` pure core + verdict events + policy-version hash stamping
- [ ] Promotion state machine: series accounting (fixed 30-day blocks), clean/complete flags, T0–T2 transitions, demotion triggers (TD-10)
- [ ] `halt`/`resume` + circuit breakers (R-001, R-009)
- [ ] Adversarial replay scenario suite (threat-model vectors of §15 as tests)

---

## P3 — Paper trading, review, reporting

**Done-gate:** end-to-end on paper: scan → thesis → adversarial review → gates → order → simulated fill → grade → memo, all replayable from the ledger.

### M3.1 Execution pipeline

- [ ] `BrokerPort` + conformance suite (TD-6/18)
- [ ] PaperBroker: named accounts, market fills (mid±spread+fees), limit fills (trade-through ≥1 tick, G5), deterministic replay
- [ ] `broker.execute_order` two-phase pipeline (§8.2)
- [ ] `reconcile` for paper accounts (self-consistency) + seed $5k/$5k base distribution w/ long-term theses (SCOPE Pass C)

### M3.2 Review & advisory

- [ ] `LLMReviewerPort` + Codex/Gemini subprocess adapters (TD-21)
- [ ] Attack/defense orchestration + rubric scoring + auto-fail short-circuits (§12.1)
- [ ] ManualBroker + `tk fill record` (advisory, D16); Kraken read-only tracking (needs Mike's key)
- [ ] Advisory rules live: R-009 for advisory pools, R-014 cooling-off

### M3.3 Reporting, memory, research

- [ ] `tk brief` (token-budgeted) + `tk search` (memory module, TD-20)
- [ ] Daily memo + readiness report + P&L snapshot templates (§12.3)
- [ ] Research-loop lead/scout prompts (D14, deferred from Pass B) + `tk wiki add`
- [ ] Derivatives provider: Kraken Futures primary, Coinalyze cross-check (G6)

---

## P4 — Live proof (MVP done-gate, D4)

**Done-gate:** 3 live trades execute, settle, reconcile vs ledger; P&L snapshot verified by a non-Anthropic model.

- [ ] Alpaca paper dress rehearsal: full pipeline against real Alpaca API (order lifecycle parity)
- [ ] Mike's hands: live keys + fund $50–100 (D12)
- [ ] Promotion flow exercised for real: readiness report → `tk promote confirm` → 3-trade budget (R-011)
- [ ] 3-trade live sequence + `reconcile` green + auto-revert
- [ ] `verify_claim` second-model verification of the snapshot (D4) — MVP COMPLETE

---

## P5+ — Deferred (designed, not built)

- [ ] FastMCP server wrappers + skill descriptors (TD-15)
- [ ] CDP Server Wallet adapter (D3)
- [ ] On-chain oracle behind `OnChainDataPort` (D13; productizable)
- [ ] Embeddings/RAG memory upgrade (D15)
- [ ] Research-loop scheduling (Cowork task, D14)
- [ ] Red-team strategy tournaments (SCOPE vision)
- [ ] Options asset class (Mike: maybe; Alpaca supports)
- [ ] Phase-2 hardening: single-writer key-holding daemon (TD-19)
