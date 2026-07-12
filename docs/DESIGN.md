# tradekit — Architecture & Design Document (Pass B)

> Status: **v0.2 — Mike approved v0.1 decisions; adversarial review incorporated** · Session 2026-07-12 (Claude Code, Fable) · Author: CTO-agent
> Inputs: [SCOPE.md](SCOPE.md) (decisions D1–D17), [MAE canonical doc](research/Market%20Analysis%20Engine%20—%20Comprehensive%20Design%20Document.md), [Perplexity SME pass](research/perplexity-SME.md) (flags F1–F7), [Gemini adversarial review](research/gemini-adversarial-review.md) (findings G1–G6, dispositions therein; G4 partially rejected).
> This doc converts *what the system must do* into *how we build it and why*. Where it overrides SCOPE details, the override is called out inline and justified.

---

## 0. How to read this doc

- **§1** — design philosophy and the constraints everything else answers to.
- **§2** — the **Technical Decision register (TD-1…TD-22)**. Every major choice gets a number; later sections cite these instead of re-arguing them. If a TD changes, this table is the sync point.
- **§3–§13** — the build: stack, module architecture, contracts, and each subsystem in depth.
- **§14–§16** — trade-offs, bottlenecks, threat model, test strategy.
- **§17–§18** — build phasing (ROADMAP seed) and open questions (incl. a paste-ready Perplexity script).

Terminology: "**verb**" = a whitelisted operation the agent can invoke (CLI subcommand, later MCP tool). "**deep module**" = per Ousterhout (*A Philosophy of Software Design*): small, stable public interface; substantial hidden implementation; the interface communicates everything a caller needs.

---

## 1. Design philosophy & governing constraints

**Axiom (SCOPE §1):** deterministic core, thin LLM shell. Every judgment call happens in the model; every enforcement, math, and money-touching operation happens in boring, testable Python reachable only through whitelisted verbs.

Four consequences drive the whole architecture:

1. **Deep modules, hard boundaries.** Python has no `interface` keyword, so we enforce it structurally: each subsystem exposes its public surface *only* via its package `__init__.py` (≤ ~6 verbs each); everything else is `_private`. Cross-module imports of another module's internals are a lint failure (enforced with a custom Ruff/import-linter rule from day one). A subagent should be able to understand what a subsystem *provides and takes* from its interface file alone.
2. **Everything replayable.** State is an append-only event log (TD-4). Any number — a position, a P&L snapshot, a promotion tier — must be recomputable from events plus market data. This is what makes auditor agents, the experiment registry (D15), and the verification layer (D4) cheap.
3. **The model is cooperative but must not be *trusted for arithmetic or restraint*.** Gates are deterministic code. The threat model (§15) is explicit about what "non-bypassable" honestly means in a single-user local deployment and what we harden later.
4. **Smallest thing that can't lie.** Where a simpler mechanism gives the same guarantee, we take it (e.g., no message bus, no daemon, no Postgres in MVP). Complexity is spent only where SCOPE demands a guarantee (hash-chained ledger, predicate-based grading).

---

## 2. Technical Decision register

Cited throughout as TD-n. SCOPE decisions remain D-n; SME flags F-n.

| # | Decision | Summary (why → section) |
|---|----------|--------------------------|
| TD-1 | **Python 3.12 + uv**, src-layout monorepo, one package `tradekit`, CLI `tk` | §3 |
| TD-2 | **7 deep modules** (`ledger, policy, mae, thesis, broker, review, memory`) + 2 shared leaf modules (`contracts`, `costs`) + 2 thin shells (`cli`, `report`); public surface = package `__init__` only, ≤ ~6 verbs each | §4 |
| TD-3 | **Contracts-first**: all cross-module payloads are Pydantic v2 models in `tradekit.contracts`; JSON Schema exported for non-Python agents; `Decimal` for money/quantities, `float` allowed only inside analysis math | §5 |
| TD-4 | **Event-sourced ledger**: single append-only, hash-chained `events` table (SQLite WAL) = source of truth; read models are rebuildable projections | §6 |
| TD-5 | **Policy engine**: `evaluate(action) -> Verdict` — pure rule core over an internally assembled context snapshot; rules are declarative data with inline WHY; verdict written to ledger *before* any broker call (two-phase order pipeline) | §7 |
| TD-6 | **`BrokerPort`** abstraction; adapters: AlpacaBroker (paper+live), PaperBroker (ours), ManualBroker (advisory/D16); CDP wallet adapter deferred per SCOPE §6 | §8 |
| TD-7 | **We build our own PaperBroker** (deterministic fill sim off live quotes). Alpaca's single paper account is reserved as the execution-path dress rehearsal, not the experimentation venue | §8.3 |
| TD-8 | **One cost model** (`tradekit.costs`, shared leaf module): fees/spread/slippage shared by PaperBroker, backtester, and metrics — paper results, backtests, and edge math can never disagree about friction | §8.3, §9.4 |
| TD-9 | **Grading = predicate DSL**, PASS/FAIL/**VOID**; invalidation ≠ stop-loss (F1); VOID guarded against gaming (reviewer sign-off + ≤20% void-rate audit trigger) | §10 |
| TD-10 | **Promotion criteria hardened per SME (F2, F3)**: series = fixed 30-day calendar blocks, ≥10 graded non-void theses each; promote on 3-of-last-4 clean + most recent clean + ≥30 non-void total + metric gates. *Overrides SCOPE §5's underspecified series* | §7.3 |
| TD-11 | **Sizing purity (F6)**: `size_position` accepts no P&L-history or account-state inputs beyond current equity; enforced by contract signature | §9.3 |
| TD-12 | MAE keeps the canonical **6-verb surface**; CoinMarketCap dropped (redundant); **derivatives data is a pluggable port** — Binance fapi is geo-blocked for US IPs, fallback chain required (open question Q1) | §9 |
| TD-13 | **Regime: HMM with pinned seed + persisted model artifact** per (symbol, window); deterministic rules-based classifier as fallback and cross-check; **EWMA realized-vol 3σ monitor overrides a stale fit to risk-off** (G3) | §9.2 |
| TD-14 | **Overfit checks (F4)**: walk-forward + Deflated Sharpe Ratio implemented in-house (closed-form; no mlfinlab dependency — it's now paywalled/heavy); **DSR gates only at n ≥ 30 per strategy — 10 ≤ n < 30 is a provisional regime** (penalized Sharpe + hard MDD bound, ineligible for promotion) (G1) | §9.4 |
| TD-15 | **CLI-first** (`tk`, Typer); FastMCP wrappers are Phase-2 thin decorators over the same functions (D9); skills = ~200-token descriptors | §4.4, §17 |
| TD-16 | **No daemons, no async in MVP core.** Single-process CLI invocations; SQLite WAL + `busy_timeout` + bounded retry-with-jitter on every `ledger.append`; parallel fetch inside MAE only where rate limits allow. Write-storm escalation = the Phase-2 single-writer daemon, *not* in-process queues (can't serialize across our multi-process CLI topology — G4 partially rejected) | §14 |
| TD-17 | **UTC everywhere**, injected `Clock` port; bar timestamps canonical at bar *open* | §13 |
| TD-18 | **Three test rings**: pure-unit w/ golden vectors → contract tests w/ recorded fixtures → replay E2E. Zero network in CI | §16 |
| TD-19 | **Secrets**: `.env` held by the `tk` process; agent sandboxes never see keys. Phase-2 hardening: local key-holding daemon with verb-token auth. Threat model states the honest limits | §15 |
| TD-20 | **Memory**: FTS5 keyword search + auto-generated session brief; experiment registry stamps every event with `run_id` (`TK_RUN_ID` env) | §11 |
| TD-21 | **Adversarial review via `LLMReviewerPort`**: subprocess adapters to Codex/Gemini CLIs; rubric scoring deterministic in Python; artifacts ledgered | §12 |
| TD-22 | **Ledger DB and cache DB are separate files** (`ledger.db` sacred, `cache.db` disposable) | §6.1 |
| TD-23 | **Tick-size quantization boundary** (G2): every float→Decimal conversion at the MAE boundary goes through `contracts.quantize(value, asset.tick_size)` — float noise can never flip a grading predicate | §13 |

---

## 3. Tech stack

| Layer | Choice | Why (and what was rejected) |
|---|---|---|
| Runtime | Python 3.12 | hmmlearn/pandas wheels stable on Windows; 3.13 gains nothing we need. Pinned in `pyproject.toml`. |
| Package mgmt | **uv** | Lockfile, fast, first-class on Windows. Rejected poetry (slow) and bare pip (no lock). |
| Contracts | **Pydantic v2** + pydantic-settings | Validation at every boundary; JSON Schema export gives non-Python agents typed contracts for free (D9). |
| CLI | **Typer** | Subcommand tree maps 1:1 to verb surface; `--json` output flag on every verb for agent consumption. |
| HTTP | **httpx** + tenacity | One client lib, sync in MVP (TD-16); tenacity for provider retry/backoff policies. |
| Broker SDK | **alpaca-py** (official) behind our port | Maintained + typed; raw httpx for Kraken/Binance/CoinGecko (simple GETs, no SDK worth the dependency). |
| Analysis | pandas + numpy; **hmmlearn** for HMM | Indicators implemented in-house on numpy (no TA-Lib: C build pain on Windows, and we want every formula unit-tested against golden vectors, TD-18). |
| Macro data | yfinance (daily batch only) | Per canonical doc caveats; wrapped in cache + retry; never on a real-time path. |
| State | **SQLite** (stdlib), WAL mode, FTS5 | D10. Zero infra, single file, FTS5 built in. Scale path in §14. |
| IDs | ULID (`python-ulid`) | Sortable, collision-free event/thesis IDs. |
| MCP | FastMCP (Phase 2) | Thin decorators over the same pure functions (D9). |
| Tests/quality | pytest, pytest-cov, **ruff**, mypy (strict on `contracts`, `policy`, `ledger`, `thesis`) | Strict typing exactly where money and state live; pragmatic elsewhere. |
| CI | GitHub Actions: windows-latest + ubuntu-latest | Dev is Windows-first (D11); CI catches path/locale drift both ways. |

Deferred deps (designed-for, not installed): `websockets` (streaming), `fastmcp`, CDP SDK, embeddings stack (D15 phase 2).

---

## 4. System architecture

### 4.1 Runtime topology

```
┌── LLM / Agent (any model) ─────────────────────────────────────────┐
│  skill descriptors (~200 tok) → invokes `tk <verb>` (CLI, --json)  │
└───────────────┬────────────────────────────────────────────────────┘
                ▼
┌── tradekit.cli  (thin shell: parse → contracts → dispatch) ────────┐
│   read verbs ──────────────► mae · memory · report · ledger.query │
│   mutating verbs ─► policy.evaluate ─► thesis/broker ─► ledger    │
└───────────────┬───────────────────────────────┬────────────────────┘
                ▼                               ▼
        tradekit.ledger  ◄────events──── every subsystem
        (append-only, hash-chained, projections, FTS5)
                │
                ▼
        External: Alpaca · Kraken · Binance* · CoinGecko · yfinance
                  Codex/Gemini CLIs (review) · [CDP wallet: deferred]
```

Key property: **there is exactly one mutating path** — CLI verb → contract validation → `policy.evaluate` → verdict event → subsystem action → outcome event. Read verbs bypass policy (they can't spend money) but still stamp `run_id` for the experiment registry.

### 4.2 Deep-module map (TD-2)

Fine-grained module candidates from SCOPE §3 and the MAE doc, grouped under the deep interfaces that hide them:

| Deep module | Public interface (complete) | Hides (internal submodules) |
|---|---|---|
| `tradekit.contracts` *(shared leaf)* | the Pydantic models + `json_schemas()` export | schema versioning, Decimal coercion, predicate DSL validation |
| `tradekit.costs` *(shared leaf)* | `price_friction(venue, asset_class, order_ctx) -> Friction` | venue fee schedules, spread/slippage models (TD-8) |
| `tradekit.ledger` | `append(event)` · `query(filter)` · `models` (typed read-model accessors) · `rebuild()` · `verify_chain()` · `search(text)` | SQLite/WAL/FTS5, hash chain, projections, migrations, run-id stamping |
| `tradekit.policy` | `evaluate(action) -> Verdict` · `status()` · `promotion_status()` · `confirm_promotion()` · `halt(reason)` / `resume()` | rules catalog + WHYs, promotion state machine, circuit breakers, dials, series accounting |
| `tradekit.mae` | `scan_markets` · `get_regime` · `get_derivatives_context` · `compute_strategy_metrics` · `size_position` · `get_correlation_matrix` | all data providers + normalization + cache + rate limiting, indicators, HMM, backtest engine, walk-forward/DSR |
| `tradekit.thesis` | `draft` · `submit` · `approve` / `reject` · `grade` · `void` | contract validation, state machine, market-snapshot capture, grading arithmetic vs predicates; activation-on-fill (internal, invoked by the broker pipeline) |
| `tradekit.broker` | `get(account_ref) -> BrokerPort` · `execute_order(thesis_id) -> OrderOutcome` · `reconcile(account_ref)` · `record_manual_fill(...)` | two-phase pipeline orchestration (§8.2), Alpaca adapter, PaperBroker fill sim, ManualBroker, order polling, venue quirks |
| `tradekit.review` | `run_review(thesis_id) -> ReviewArtifact` · `verify_claim(claim) -> Verification` | reviewer-model adapters (Codex/Gemini subprocess), rubric scoring, attack/defense transcript mgmt |
| `tradekit.memory` | `brief() -> str` · `search(query, k)` · `record_lesson(note, salience)` | FTS queries, salience ranking, brief token-budgeting, wiki front-matter |
| `tradekit.cli` *(thin)* | `tk` verb tree | Typer wiring only — no logic |
| `tradekit.report` *(thin)* | `daily_memo` · `readiness_report` · `pnl_snapshot` | markdown templating over ledger read models |

Rules of the map:
- **Depth test:** if a module's interface grows past ~6 verbs, that's a design smell — split responsibilities or push logic down, don't widen the surface.
- `mae._backtest` is *internal* to MAE — reached only through `compute_strategy_metrics` (walk-forward/DSR run inside it); no raw backtest verb is exposed, so the agent never orchestrates backtest plumbing.
- Read-only `show`/`list` CLI verbs (`tk thesis show`, `tk grade show`, …) are dispatch to `ledger.models` read accessors — they are not part of any subsystem's mutating interface.
- The **research loop** (D14) is deliberately *not* a code subsystem: it's prompt assets + scheduled agents writing to `docs/wiki/`, using `memory.record_lesson` and read verbs. No code to maintain beyond one `tk wiki add` verb. The lead/scout prompt content itself (Sonnet lead + 3 Haiku scouts per D14) is an **explicit deferral of a SCOPE §8 Pass-B item to Phase 3** — writing those prompts before the wiki and memory verbs exist would be designing against vapor.

### 4.3 Repository layout

```
tradekit/
├── pyproject.toml            # uv-managed; pinned py3.12
├── src/tradekit/
│   ├── contracts/            # §5 — models, predicate DSL, schema export
│   ├── costs.py              # shared fee/spread/slippage model (TD-8)
│   ├── ledger/               # §6
│   ├── policy/               # §7 — incl. rules.py (catalog w/ WHYs)
│   ├── mae/
│   │   ├── _data/            #   kraken, binance, alpaca_data, coingecko, macro, cache
│   │   ├── _indicators/      #   momentum, trend, volatility, volume, structure
│   │   ├── _regime/          #   hmm + rules fallback
│   │   ├── _risk/            #   sizing, portfolio
│   │   ├── _metrics/         #   sharpe/sortino/calmar/PF/expectancy, DSR, walk-forward
│   │   └── _backtest/        #   vectorized engine
│   ├── thesis/               # §10
│   ├── broker/               # §8 — port + alpaca/paper/manual adapters
│   ├── review/               # §12
│   ├── memory/               # §11
│   ├── report/               # §12.3
│   └── cli/                  # tk entrypoint
├── prompts/                  # research-loop lead/scout prompts, reviewer rubrics
├── rules/RULES.md            # human-readable rules catalog (generated from policy/rules.py)
├── docs/                     # SCOPE, DESIGN (this), ROADMAP, wiki/, reports/
├── data/                     # ledger.db, cache.db, models/ (HMM artifacts) — gitignored
└── tests/                    # unit/ contract/ replay/ + golden/ fixtures
```

Leading underscore on MAE internals is the "we enforce it *hard*" convention: importing `tradekit.mae._indicators` from outside `tradekit.mae` fails lint (§1, consequence 1).

### 4.4 Verb surface (CLI, TD-15)

Every verb: `--json` structured output, `--run-id`/`TK_RUN_ID` stamping, non-zero exit on gate denial with the Verdict as payload.

```
tk scan|regime|derivs|metrics|size|correl     # MAE verbs (§9)
tk thesis draft|submit|show|approve|reject|void  # thesis lifecycle (§10)
tk order submit|status|cancel                  # execution pipeline (§8.2)
tk grade sweep|show                            # grading engine (§10.3)
tk account list|balance|positions|reconcile    # accounts (§8)
tk fill record                                 # manual advisory fills (D16, §8.4)
tk policy status|halt|resume                   # gates & kill switch (§7)
tk promote status|confirm                      # ladder; `confirm` is Mike-only (§7.3)
tk brief / tk search / tk wiki add             # memory (§11)
tk review run|verify                           # adversarial review (§12)
tk report memo|readiness|snapshot              # reporting (§12.3)
tk ledger query|rebuild|verify                 # audit surface (§6)
tk schema export                               # JSON Schemas for non-Python agents (§5)
```

---

## 5. Contracts (`tradekit.contracts`, TD-3)

All cross-boundary payloads live here — the one module everything may import, which imports nothing from tradekit. Pydantic v2, `model_config = ConfigDict(frozen=True)` — no in-place mutation ever; late-bound fields (`market_snapshot_id`, `review_artifact_id`) are attached via `model_copy(update=…)` producing a superseding version, and no version may follow `submit` (§10.1). `Decimal` for money/qty (TD-3). `tk schema export` writes JSON Schemas to `docs/schemas/` so Codex/Gemini agents get typed contracts without reading Python.

### 5.1 Thesis contract (the spine)

Incorporates SME F1 (invalidation ≠ stop), F5 (explicit numeric EV mandatory):

```python
class ThesisContract(BaseModel):
    thesis_id: str                      # ULID, assigned at draft
    schema_ver: int = 1
    account_ref: str                    # "paper:alpha" | "live:alpaca" | "advisory:kraken" | "advisory:cashapp"
    asset: AssetRef                     # symbol + venue + asset_class
    direction: Literal["long", "short"]
    strategy_tag: str                   # links to wiki strategy page + experiment registry
    rationale: str                      # falsifiable catalyst, prose (reviewed, not graded)

    entry: EntrySpec                    # order_type, limit/trigger price, valid_until
    horizon_end: datetime               # UTC; grading hard stop
    target_price: Decimal               # success predicate anchor
    stop_price: Decimal                 # failure predicate anchor (price-based)
    invalidation: InvalidationSpec      # structural; separate from stop (F1) — see §5.2

    size_usd: Decimal                   # from mae.size_position; sizing method recorded
    sizing_method: Literal["min_atr_kelly"]
    ev_block: EVBlock                   # p_win, reward_usd, risk_usd, ev_usd — numeric, mandatory (F5)

    success_criteria: list[Predicate]   # machine-checkable (§5.2)
    failure_criteria: list[Predicate]
    market_snapshot_id: str             # decision-time snapshot event (D15), set at submit
    review_artifact_id: str | None      # set when adversarial review completes
```

### 5.2 Predicate DSL — grading must be arithmetic, so criteria must be *machine-checkable*

Free-text criteria would make "grading = pure arithmetic" (D-SCOPE §3.2) a lie. MVP grammar is deliberately tiny — price-and-time only:

```python
class Predicate(BaseModel):
    kind: Literal["price_touch", "price_close", "time_expiry"]
    cmp: Literal["gte", "lte"]
    value: Decimal                      # absolute price (not %) — resolved at submit time
    timeframe: str = "1h"               # bar granularity used for evaluation
    by: datetime                        # deadline (usually horizon_end)
```

`cmp`/`value` apply to the price kinds only; `time_expiry` uses `by` alone (a discriminated union in the implementation — the sketch above is flattened for readability).

`InvalidationSpec` is one of:
- `MeasurableInvalidation(predicate: Predicate)` — auto-evaluated by the grader (e.g., "BTC closes < 57 000 before entry fills");
- `StructuralInvalidation(description: str, requires_attestation=True)` — catalyst-based conditions no formula can check ("FOMC surprises hawkish"). Triggering one requires an attestation event **plus reviewer-model sign-off** (§10.4) — the anti-gaming guard on VOID.

Grading semantics (F1): success predicate hit within horizon → **PASS**; stop/failure predicate hit or horizon expiry → **FAIL**; invalidation triggered → **VOID**, excluded from win-rate stats but *counted and capped* (§10.4).

### 5.3 Other core contracts (field-level detail in schema export)

| Contract | Carries | Produced by → consumed by |
|---|---|---|
| `ProposedAction` | action kind (submit_order/cancel/promote/void/…), account_ref, thesis_id, order params, requested_by | cli → policy |
| `Verdict` | allow/deny, `rule_hits: list[RuleHit]` (rule_id, outcome, measured value, limit), policy_version_hash, verdict_id | policy → cli/broker; always ledgered |
| `OrderRequest / OrderAck / Fill` | venue-neutral order lifecycle; Fill carries fees + quote snapshot used | broker adapters ↔ thesis/ledger |
| `Event` | envelope: event_id (ULID), ts_utc, type, actor, run_id, schema_ver, payload | everyone → ledger |
| `MarketSnapshot` | prices, regime state, derivatives context, correlations at decision time (D15) | thesis.submit → ledger |
| `ReviewArtifact` | attack/defense transcript refs, rubric scores, unresolved attacks, reviewer model+version | review → thesis/ledger |
| `Grade` | PASS/FAIL/VOID, evaluated predicates w/ measured values, pnl_usd net of fees | thesis.grade → ledger/policy |
| `RunManifest` | run_id, model, framework, prompt verbatim + sha256, config_version (D15) | session bootstrap → ledger |

---

## 6. Ledger & event store (`tradekit.ledger`, TD-4)

### 6.1 Why event-sourced (trade-off made explicit)

Alternative considered: conventional mutable tables per entity (theses, trades, …) with audit triggers. Rejected because SCOPE independently demands (a) append-only replayable history (D10), (b) an experiment registry correlating *every* action with harness metadata (D15), (c) tamper-evident verification (D4). With mutable tables each demand is a bolt-on; with one event log all three are the *same mechanism*. The cost — eventual projections — is trivial at our write volume (tens of events/day). Two SQLite files (TD-22): `ledger.db` (sacred, backed up) and `cache.db` (market-data cache, deletable anytime).

### 6.2 DDL (core)

```sql
CREATE TABLE events (
  seq        INTEGER PRIMARY KEY,          -- monotonic, assigned by SQLite
  event_id   TEXT NOT NULL UNIQUE,         -- ULID
  ts_utc     TEXT NOT NULL,                -- ISO-8601
  type       TEXT NOT NULL,                -- taxonomy §6.3
  actor      TEXT NOT NULL,                -- 'agent:<model>' | 'mike' | 'system:<job>'
  run_id     TEXT,                         -- experiment registry key (D15)
  schema_ver INTEGER NOT NULL,
  payload    TEXT NOT NULL,                -- canonical JSON (sorted keys, RFC-8785 style)
  prev_hash  TEXT NOT NULL,
  hash       TEXT NOT NULL                 -- sha256 over prev_hash ‖ ALL other columns
                                           -- (event_id, ts_utc, type, actor, run_id,
                                           --  schema_ver, payload) — nothing editable
                                           -- outside the chain
);
CREATE VIRTUAL TABLE events_fts USING fts5(event_id, type, payload_text);
```

Read models (projections; rebuildable via `tk ledger rebuild`): `theses`, `orders`, `fills`, `positions`, `pnl_daily`, `series`, `promotion_state`, `runs`, `config_versions`, `snapshots`. Projections are *caches*, never written directly by subsystems.

`verify_chain()` recomputes the hash chain; it's the first step of `tk report snapshot` and of the second-model verification (D4). Honest scope: the chain proves *the file wasn't silently edited*, not that the operator is honest — see §15.

### 6.3 Event taxonomy (v1)

```
RunStarted · ConfigChanged · PolicyVersionLoaded
ThesisDrafted · ThesisSubmitted · MarketSnapshotTaken · SizingComputed · ReviewCompleted
ThesisApproved · ThesisRejected · ThesisActivated
ActionProposed · VerdictIssued                      ← two-phase pipeline (§8.2)
OrderSubmitted · OrderAck · OrderCancelled · FillRecorded
InvalidationAttested · ThesisGraded (PASS|FAIL|VOID)
SeriesClosed · PromotionGranted · PromotionConfirmed · Demoted
CircuitBreakerTripped · HaltSet · HaltCleared · GateViolationDetected
LessonRecorded · ReconciliationRun (ok|mismatch)
```

Every event type has a versioned Pydantic payload model in `contracts` — the taxonomy *is* a contract, not stringly-typed convention.

---

## 7. Policy engine (`tradekit.policy`, TD-5)

### 7.1 Shape

`evaluate(action: ProposedAction) -> Verdict` is a **pure function** of (action, context snapshot, rules version). Context (balances, open positions, tier, today's trade count, breaker states) is assembled from ledger read models by a private `_context.py`; the evaluation itself does no I/O — which makes every rule unit-testable with a synthetic context and makes verdicts replayable byte-for-byte.

Rules are declarative entries in `policy/rules.py`:

```python
Rule(
  id="R-005", applies_to={"submit_order"},
  check=lambda a, ctx: a.order.notional_usd <= ctx.dials.max_position_usd,
  why="Caps single-position blast radius; a $100 bankroll survives being wrong, "
      "not being wrong big. Dial: max_position_usd (D12).",
)
```

`rules/RULES.md` is *generated* from this registry (`tk policy status --rules`), so the human-readable catalog can never drift from the code — one source of truth, per SCOPE §3.4's "WHY inline" requirement.

### 7.2 Rules catalog v1 (IDs stable forever; dials in config)

| ID | Gate | Default dial |
|---|---|---|
| R-001 | Kill switch: any `HaltSet` unresolved → deny everything mutating | — |
| R-002 | Promotion tier permits this account_ref + action (T0 research / T1 paper / T2 live) | — |
| R-003 | Sufficient settled balance incl. fees | — |
| R-004 | Per-asset allowlist (live: liquid large-caps + BTC/ETH only, per SME §5) | list |
| R-005 | Max position notional | live: $25; paper: 10% equity |
| R-006 | Max total live exposure | $100 (D12) |
| R-007 | Daily trade count (paper cap deliberately tightens SCOPE §5's "unlimited" — anti-gaming, cheap to dial up) | live: 3/day; paper: 20/day |
| R-008 | **Min notional $10** — blocks micro-trade series gaming and fee-noise grading (SME §5) | $10 |
| R-009 | Drawdown circuit breaker: account drawdown ≥ 10% (30d peak) → no new positions until graded review (F7 — applies to advisory too) | 10% |
| R-010 | Thesis prerequisites: approved review artifact + numeric EV block + snapshot present | — |
| R-011 | Live sequence budget: T2 grants max 3 live trades, then auto-revert to review (SCOPE §5) | 3 |
| R-012 | Sizing purity (F6): reject if submitted size ≠ recorded `size_position` output for this thesis | tolerance 1% |
| R-013 | Correlation cap: new position with |r| > 0.75 to an open position requires explicit review flag | 0.75 |
| R-014 | Advisory cooling-off: manual trades > $200 need thesis age ≥ 24h (F-guardrail 5) | $200/24h |
| R-015 | VOID-rate audit: >20% voids in trailing 20 graded theses → block new submissions until process review (§10.4) | 20% |
| R-016 | Promotion metric gates: strategy acceptance table (§9.4) must pass at promotion evaluation | per §9.4 |

Deny verdicts are never silent: `GateViolationDetected` events feed the promotion ladder's "process-compliant" definition.

### 7.3 Promotion state machine (TD-10; overrides SCOPE §5 details per F2/F3)

```
        ┌────────────────────────────────────────────────┐
        ▼                                                │ demotion:
  T0 research ──enable──► T1 paper ──criteria met──► T2 live (3-trade    │ R-009 trip,
                              ▲     + Mike confirms      sequence)──────┘ gate violation,
                              └───────auto-revert────────┘   or failed live grading
```

**Series (locked per F2):** fixed, calendar-aligned 30-day blocks (no rolling windows — nothing to cherry-pick). A series is *complete* when the window closes with ≥ 10 graded non-void theses; *clean* = zero gate violations AND expectancy > 0 net of simulated fees AND max intra-series drawdown < 15%.

**T1→T2 (locked per F3):** 3 of last 4 complete series clean ∧ most recent clean ∧ ≥ 30 non-void graded theses across those series ∧ strategy metrics pass §9.4 gates. Then `PromotionGranted` (machine) → readiness report → `tk promote confirm` (Mike, D6) → `PromotionConfirmed` with a 3-trade live budget (R-011).

Attempt statistics are surfaced in every `tk brief` (D7 — stakes without deception). The state machine lives *inside* policy because promotion state is an input to gates — one module owns both, no sync problem.

---

## 8. Broker & execution (`tradekit.broker`, TD-6/7)

### 8.1 The port

```python
class BrokerPort(Protocol):
    def account(self) -> AccountState            # equity, settled cash, buying power
    def positions(self) -> list[Position]
    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck  # adapters refuse without an allow-verdict (§8.2, §15)
    def order_status(self, order_id: str) -> OrderStatus
    def fills(self, since: datetime) -> list[Fill]
```

Five methods; every venue quirk (Alpaca fractional rules, crypto symbol mapping, paper-sim internals) is hidden behind them. `broker.get(account_ref)` resolves `"paper:alpha"` → PaperBroker instance, `"live:alpaca"` → AlpacaBroker, `"advisory:*"` → ManualBroker.

### 8.2 Two-phase order pipeline (the money path)

Owned by `broker.execute_order(thesis_id)` — the pipeline sequencing below is *its* internal logic (`broker/_pipeline.py`); the CLI verb is pure dispatch (TD-2), so the money path never lives in a thin shell.

```
tk order submit --thesis TH-01H…   →  broker.execute_order(thesis_id)
 1. load thesis (must be approved) → build ProposedAction
 2. ActionProposed event                         ← intent recorded BEFORE evaluation
 3. policy.evaluate → VerdictIssued event        ← verdict recorded BEFORE broker call
 4. deny → exit(1) with Verdict          allow ↓
 5. broker.submit → OrderSubmitted / OrderAck events
 6. `tk order status` polling → FillRecorded → thesis.activate
 7. tk account reconcile (scheduled + pre-snapshot): broker records vs ledger;
    mismatch → ReconciliationRun(mismatch) + automatic HaltSet          (D4)
```

Ordering guarantee: an order without a preceding allow-verdict in the chain is *structurally impossible* through the verb surface, and *detectable* if done out-of-band (reconcile finds broker fills with no ledger trail → halt + audit).

### 8.3 PaperBroker — ours, deterministic (TD-7)

Alpaca provides exactly one paper account; SCOPE requires many named ones ("spin up paper accounts to study distributions"). So paper accounts are rows in our ledger, and fills are simulated:

- **Market orders:** fill at latest cached quote mid ± half modeled spread (side-dependent), plus venue fee from `mae.costs`. Quote snapshot stored on the Fill — every paper fill is auditable.
- **Limit orders:** fill only when a subsequent bar trades **through** the limit price by ≥ 1 tick — an exact touch is *not* a fill (at-touch retail limits often rest unexecuted because the spread never swept through; G5). Conservative rule: assume worst price within the bar, no partial fills in MVP.
- **Costs (TD-8):** the *same* `mae.costs` tables used by the backtester and by `compute_strategy_metrics`' net-of-fee expectancy — SME §5 numbers seed it (equities ≈ 0 commission + 1–2 bps spread on large caps; Alpaca crypto 25 bps taker + spread). One source of truth means paper results, backtests, and gate math can never disagree about friction.
- Determinism: given the same cached market data, replaying the event log reproduces identical fills (TD-18 ring 3 depends on this).

Known gap, stated honestly: our fill model is *optimistic about liquidity* (no queue position, no partial fills). Acceptable at ≤ $25 notionals on liquid symbols; revisit before any size increase (§18 Q2). The Alpaca *paper* account is used only as a dress rehearsal of the real API path before each live sequence.

### 8.4 ManualBroker (advisory mode, D16)

`submit` is disabled (raises `AdvisoryOnly`); the flow is: framework produces thesis + recommendation → Mike executes on Kraken/Cash App → `tk fill record --thesis … --price … --qty … --fees …` writes a `FillRecorded` event with `actor=mike`. Grading is then identical to bot positions. Kraken read-only key (Query Funds/Orders only) drives balance/position tracking and reconcile-style sanity checks; Cash App is manual-entry only. Advisory accounts get the *same* R-009 drawdown breaker and R-014 cooling-off (F7 — Mike is down ~13%, which is precisely the loss-recovery-bias zone the SME flagged; the pipeline exists to catch that, so it applies to Mike too).

CDP Server Wallet adapter: interface reserved (`"wallet:cdp"` account_ref), implementation deferred per SCOPE §6.

---

## 9. Market Analysis Engine (`tradekit.mae`, TD-12)

Ported from the canonical doc; the 6-verb public surface is preserved verbatim (schemas per canonical §3, re-expressed as `contracts` models). This section records only the **deltas and hardening** — the canonical doc remains the reference for endpoint mechanics.

### 9.1 Data layer deltas

- **Providers behind `MarketDataPort`** with a canonical OHLCV frame (UTC open-time indexed, Decimal-safe columns); per-provider rate-limiter + tenacity retry; cache-aside into `cache.db` keyed (provider, symbol, timeframe, range). Bars are immutable once closed → cache never invalidates closed bars; only the live bar refetches.
- **CoinMarketCap dropped** (TD-12): fully redundant with CoinGecko at our needs; one fewer key, one fewer failure mode.
- **⚠ Binance geo-block (TD-12, resolved G6):** `fapi.binance.com` returns HTTP 451 from US IPs — the canonical doc's primary derivatives source fails on Mike's machine. `get_derivatives_context` sits on a `DerivativesPort` with the chain: **Kraken Futures public first** (`futures.kraken.com/derivatives/api/v3/tickers` — funding + aggregate OI, no auth, US-accessible per G6) → **Coinalyze free API** as aggregator cross-check → Binance when reachable → degrade gracefully (`"provider": "unavailable"`, partial output flagged). Note this module never *trades* futures — it reads positioning data to inform spot crypto theses. Per Mike (2026-07-12), futures signals rank below stocks/crypto: implementation slips to Phase 3; the port is designed now.
- **Correlation methodology (feeds R-013):** Pearson on daily log-returns over a 30-day window, inner-joined on UTC days where *both* assets have bars (crypto weekend bars drop when paired with equities). Fewer than 20 overlapping observations → `insufficient_overlap` flag, and R-013 treats the pair as *unmeasured* — which requires an explicit review flag, never a silent pass.
- yfinance: daily macro batch only, cached same-day; a failed macro fetch degrades `get_correlation_matrix` (macro columns marked stale) rather than failing the verb.

### 9.2 Regime (TD-13)

`hmmlearn` GaussianHMM per canonical, hardened for reproducibility: fixed seed, fitted model persisted to `data/models/hmm-{symbol}-{window}.pkl` with training-window metadata; refit only on schedule (weekly) or explicit `--refit`, never implicitly — so two calls in one session can't disagree. A deterministic fallback classifier (realized-vol percentile × ADX trend rule) serves when history is insufficient and doubles as an HMM sanity cross-check; output schema identical, `"method": "hmm" | "rules" | "ewma_override"`.

**Non-stationarity guard (G3):** a weekly-refit HMM is blind to a Tuesday shock — it will report "low-vol trend" into a freefall. An EWMA realized-vol monitor runs beside the fitted model on *every* call; if current vol deviates > 3σ from the fitted state's expected variance, the verb returns a forced risk-off regime (`"method": "ewma_override"`, `recommended_strategies: []`), bypassing the stale fit. Deterministic, no refit, no discretion — the sizing and gating layers downstream never see the blind spot.

### 9.3 Sizing (TD-11)

Per canonical (`min(ATR-normalized, quarter-Kelly)`), with the F6 purity constraint enforced structurally: the signature accepts current equity, ATR inputs, and Kelly parameters — **no P&L history, no drawdown state, no "amount to recover"**. The accepted sizing output is ledgered as a `SizingComputed` event at thesis submit, and R-012 closes the loop: an order sized differently from that recorded output is denied.

### 9.4 Metrics, backtest, and overfit gates (TD-14)

`compute_strategy_metrics` per canonical, plus (F4): **walk-forward evaluation** (train ≤T, test (T, T+N], slide; flag if in-sample Sharpe > 2× out-of-sample) and **Deflated Sharpe Ratio** implemented in-house from the Bailey–López de Prado closed form (inputs: observed Sharpe, n trials tested, skew, kurtosis, track length). DSR is *the* multi-strategy overfitting gate: every strategy_tag's trial count is queryable from the experiment registry, so "number of strategies tested" is a fact, not an estimate.

**Small-sample regime (G1, resolves former Q3):** PSR/DSR variance estimates lean on sample skew and kurtosis, which are garbage below n = 30 — one outlier trade detonates the kurtosis term and the normal approximation breaks down. So DSR gates only at **n ≥ 30 per strategy_tag**. In the 10 ≤ n < 30 range a strategy is **provisional**: reported with a penalized Sharpe (observed SR haircut by 1/√n) and a hard MDD bound, allowed to keep paper trading, but *ineligible to underwrite promotion*. Below n = 10, metrics are reported descriptively with a `sample_size_insufficient` warning and no verdict.

Strategy acceptance gates (from SME §4, enforced by policy R-016 at promotion evaluation):

| Metric | Paper gate | Live gate |
|---|---|---|
| Sharpe (ann.) | ≥ 0.5 | ≥ 0.75 |
| Sortino | ≥ 1.0 | ≥ 1.0 |
| Profit factor | ≥ 1.3 | ≥ 1.3 |
| Expectancy (net of `mae.costs`) | > 0 | > 0 |
| Max drawdown | < 20% | < 15% |
| DSR (n ≥ 30 per strategy; provisional regime below — G1) | > 0.5 | > 0.5 |

The backtest engine stays per canonical (vectorized, bar-based, single-asset MVP) and **must** price friction through `tradekit.costs` (TD-8).

### 9.5 On-chain data port (D13 — interface now, implementation later)

`OnChainDataPort.get_chain_metrics(asset, metrics, window) -> ChainMetrics` — a reserved Protocol + contract model, no provider until the oracle phase (Etherscan / DeFiLlama / Dune free tiers / direct RPC per D13). Designing the port now costs one Protocol and one contract; it keeps MAE's verb surface stable when the oracle lands, and the oracle-as-product idea (D13) hangs off this port, not off MAE internals.

---

## 10. Thesis lifecycle & grading (`tradekit.thesis`, TD-9)

### 10.1 State machine

```
draft ─submit→ submitted ─review→ reviewed ─┬─approve→ approved ─activate(fill)→ active
                                            └─reject→ rejected (terminal, why logged)
active ─grade→ PASS | FAIL (terminal)        active/approved ─void(attested+signed)→ VOID
```

`submit` is where determinism gets locked in: market snapshot taken (D15), predicates resolved to absolute prices, EV block validated numeric (F5). After `submit`, the contract is immutable — amendments mean a new thesis superseding the old (event-linked).

### 10.2 Grading engine

`tk grade sweep` (scheduled + on-demand) evaluates active theses: fetch bars at each predicate's timeframe from thesis activation → now; evaluate touch/close predicates in bar order; first triggered predicate wins (stop and target in the same bar resolves *conservatively* — assume stop first; recorded as `ambiguous_bar=true`). Output `Grade` carries every predicate's measured value — a grade is an auditable computation, not a verdict from vibes.

### 10.3 P&L attribution

Realized P&L computed from Fill events net of fees (Decimal end-to-end); attributed to thesis_id and strategy_tag → feeds `pnl_daily`, series accounting, and the self-funding KPI report (D5 — *reported*, never a gate).

### 10.4 VOID anti-gaming (TD-9)

VOID is the classic escape hatch: an agent that voids its losers has a perfect win rate. Guards: (1) `MeasurableInvalidation` auto-evaluates — no discretion; (2) `StructuralInvalidation` needs an attestation event **plus** reviewer-model sign-off (`review.verify_claim`); (3) R-015 caps trailing void-rate at 20%, breach blocks new submissions pending process review; (4) voids are always visible in attempt statistics (D7).

---

## 11. Memory & experiment registry (`tradekit.memory`, TD-20)

- **Registry (D15):** session bootstrap writes `RunStarted` with the full `RunManifest` (model, framework, system/seed prompt verbatim + sha256, config version). Every event carries `run_id` — so "does prompt variant B out-trade variant A" is a ledger query, and agent configurations are first-class experiments.
- **Brief:** `tk brief` emits a token-budgeted (~1.5k tokens) markdown brief: promotion state + attempt stats (D7), open positions, active theses, last 10 grades, breaker/halt status, top-salience lessons, recent config changes. This is the standard session-opening call for any agent.
- **Search:** `tk search "<query>"` → FTS5 over events + wiki notes, recency-and-salience ranked. Embeddings/RAG is a designed upgrade (same verb, swapped internals) — *not* built until FTS demonstrably misses (D15: deterministic first).
- **Wiki:** distilled knowledge in `docs/wiki/` with front-matter (`status: candidate|simulating|rejected|adopted`, `salience`, `provenance`). The research loop (D14) writes here; `record_lesson` ledgers a pointer event so lessons are replayable too.

---

## 12. Adversarial review & verification (`tradekit.review`, TD-21)

### 12.1 Mechanics

`run_review(thesis_id)`: assemble thesis + snapshot + MAE context → **attack** prompt to a non-Anthropic reviewer (Codex CLI default, Gemini alt — subprocess adapters behind `LLMReviewerPort`) → structured JSON attack list → proposer defends per attack → reviewer scores each exchange against the rubric (`prompts/rubric-thesis-v1.md`) → **deterministic Python** tallies: any unresolved attack ≥ severity threshold blocks approval. The LLM argues; the code decides. `ReviewArtifact` (full transcript, scores, model+version) is ledgered with the thesis.

Auto-fail rules (F5): missing/non-numeric EV block, rationale that states no falsifiable catalyst, sizing not from `size_position`. These short-circuit before spending reviewer tokens.

### 12.2 Verification (D4)

`verify_claim`: for the MVP done-gate, packages ledger extract + broker records + `verify_chain()` proof for a second non-Anthropic model to confirm (trades executed, settled, reconciled; P&L snapshot correct). Same port, different prompt kit.

### 12.3 Reporting (`tradekit.report`)

Thin templating over read models. `daily_memo` renders exactly the SME §3 practitioner memo (hypothesis, context, strategy, size, risk incl. correlated positions, numeric EV, success/failure criteria, gate status) to `docs/reports/`. `readiness_report` = the promotion one-pager (SCOPE §5). `pnl_snapshot` = the verified-snapshot artifact for D4.

---

## 13. Cross-cutting conventions

- **Time (TD-17):** UTC everywhere; ISO-8601 strings at boundaries; injected `Clock` port (replay tests and the backtester share the same time source abstraction).
- **Money (TD-3, TD-23):** `Decimal` in contracts, ledger, broker, grading. `float` only inside `mae._indicators`/`_metrics` numerics. Every float→Decimal conversion at the MAE boundary goes through `contracts.quantize(value, asset.tick_size)` — tick-size-aware rounding ($0.01 equities, per-pair crypto) so float noise like `10.049999999999999` can never flip a `gte` grading predicate (G2). `AssetRef` carries `tick_size`; predicates are quantized at thesis submit, measured values at grading — same utility both sides.
- **Config:** pydantic-settings; secrets in `.env` (TD-19); tunable dials in `config.toml`. Every dial change → `ConfigChanged` event; policy stamps its rules-version hash into every Verdict — verdicts are reproducible historically.
- **Errors:** typed exception hierarchy (`GateDenied`, `ProviderUnavailable`, `ReconcileMismatch`, `AdvisoryOnly`); CLI maps them to stable exit codes; provider failures degrade with explicit staleness flags, never silent substitution.
- **Logging:** structured JSON lines to `data/logs/`; the ledger is *not* a log — logs are diagnostics, events are facts.

---

## 14. Performance, scale & bottlenecks

Honest sizing: this is a low-frequency system (SME §5 — at our size, viable trades are multi-day swings). Design for correctness; note the ceilings:

| Concern | Reality at MVP | Ceiling / scaling path |
|---|---|---|
| Event volume | tens/day | SQLite handles millions of rows; if multi-user ever happens → Postgres, same event schema |
| Scan latency | 50 symbols × 3 TFs, warm cache: seconds; cold: ~2–3 min (Kraken ~1 req/s polite rate) | acceptable at agent cadence (minutes); parallel fetch within per-provider limits if it ever hurts |
| API rate limits | CoinGecko 100/min, Alpaca 200/min, Kraken decay model — all fine with cache-aside | rate-limiter is per-provider config, not code |
| HMM fit | ms–s per symbol; weekly refit schedule | persisted artifacts (TD-13) keep the hot path read-only |
| LLM review | the *actual* bottleneck: ~1–3 min + token cost per thesis review | fine — thesis throughput is deliberately low; auto-fail short-circuits (§12.1) save spend |
| SQLite contention | WAL + `busy_timeout`; every `ledger.append` is one short transaction wrapped in bounded retry-with-jitter. Multi-agent storms (G4): research scouts write wiki *files*, not ledger events, so concurrent event writers stay few | becomes a single-writer daemon (Phase-2, TD-19) before it becomes Postgres — an in-process write queue was considered and rejected: it can't serialize across our multi-process CLI topology |
| yfinance fragility | daily batch + cache + stale-flags | swap-out is one provider module behind the port |

Brittle-scaling watchlist (things that are fine now and will *not* be fine if scope grows): PaperBroker liquidity optimism (§8.3), single-asset backtester (portfolio effects invisible), FTS5 keyword recall on a large wiki, prompt-size growth of `tk brief`.

---

## 15. Threat model & security (TD-19)

**Posture:** single-user, local, cooperative-but-uncalibrated agent. "Non-bypassable" means: *no verb reaches money without policy; out-of-band paths are denied by key custody and detected by reconciliation.* In-process Python cannot stop a hostile shell-wielding agent — we say so plainly and layer accordingly.

| Vector | Mitigation |
|---|---|
| Agent bypasses gates in-process | Structural: verbs are the only surface; broker adapters take a Verdict token; keys live in `.env` readable by the `tk` process, never provided to agent sandboxes. Phase-2: local key-holding daemon, agent gets only verb-scoped tokens |
| Out-of-band trades (stolen keys, manual UI) | `tk account reconcile` — broker fills with no ledger trail → mismatch event + auto-halt (§8.2) |
| VOID abuse | §10.4 (measurable-first, sign-off, R-015 cap, visible stats) |
| Micro-trade series gaming | R-008 min notional + series minimum trade counts (TD-10) |
| Window cherry-picking | fixed calendar series (TD-10) |
| Revenge-sizing after losses | TD-11/R-012 sizing purity; R-009 drawdown lockout (advisory included, F7) |
| Prompt injection via fetched market/news text | MAE returns *numbers and enums*, not scraped prose, to the trading agent; research-loop wiki content carries provenance front-matter and is never an input to policy — gates are deterministic regardless of what the wiki says |
| Tampered history | hash chain + `verify_chain()`; proves absence of silent edits (not operator honesty — that's what broker-side records in D4 verification are for) |
| Rules drift | policy version hash in every Verdict; RULES.md generated, never hand-edited; rules changes are git commits Mike reviews |
| Key hygiene | `.env` gitignored; live keys created only at promotion time (SCOPE §8); Kraken key is read-only by construction (D16) |

---

## 16. Test strategy (TD-18)

TDD throughout (tests written to fail first). Three rings, all offline in CI:

1. **Pure unit + golden vectors.** Indicators, metrics, DSR, Kelly/ATR sizing, predicate evaluation, hash chain: fixed input → exact expected output, cross-checked against reference implementations once, then frozen in `tests/golden/`. Property tests where they bite (e.g., grading determinism: shuffled event replay ⇒ identical grades; sizing monotonicity in ATR).
2. **Contract tests.** Each port (BrokerPort, MarketDataPort, DerivativesPort, LLMReviewerPort) has a shared conformance suite run against every adapter; external HTTP recorded as fixtures (respx). The PaperBroker and AlpacaBroker pass the *same* suite — venue swap can't change semantics silently.
3. **Replay E2E.** Scenario = a scripted event/verb sequence over canned market data → assert final read models, grades, promotion state, and chain validity. The promotion ladder, circuit breakers, and VOID guards each get adversarial scenarios (the *agent-gaming* vectors of §15 are test cases, not just prose).

High-signal bar: a failing test must localize the break (module + rule/formula) from its name and message alone. Coverage of `policy`, `thesis`, `ledger`, `contracts` gated at ~100% branch; no theater tests on plumbing.

---

## 17. Build phasing (ROADMAP seed — full ROADMAP.md after design review)

Order chosen so every phase ends with something *provable*, and the money path arrives only after the audit path exists:

1. **P0 Skeleton:** repo scaffolding, contracts + schema export, ledger (append/query/rebuild/verify), CLI shell, CI. *Provable: hash-chained events replay.*
2. **P1 MAE core:** data layer (Kraken/Alpaca/CoinGecko/yfinance + cache), indicators, metrics (+DSR/walk-forward, G1 small-sample regime), sizing, regime (incl. EWMA override, G3); Composio connector spike (D17). *Provable: golden-vector suite green; `tk scan` returns real setups.*
3. **P2 Thesis + policy:** contracts DSL, lifecycle, grading engine, rules catalog, promotion state machine. *Provable: adversarial replay scenarios green.*
4. **P3 Paper:** PaperBroker + cost model + two-phase pipeline; seed the $5k/$5k paper distribution (SCOPE Pass C); review module (Codex/Gemini adapter) + daily memo; research-loop lead/scout prompts (D14 — deferred from Pass B, see §4.2); derivatives provider (Kraken Futures primary per G6 — deprioritized below stocks/crypto per Mike). *Provable: end-to-end paper thesis → graded, reviewed, reported.*
5. **P4 Live proof:** Alpaca dress rehearsal → Mike funds $50–100 → promotion flow → 3-trade live sequence → reconcile → verified snapshot (D4 done-gate).
6. **P5+ deferred (designed above, built later):** MCP server, CDP wallet, on-chain oracle (D13), embeddings memory, research-loop scheduling, red-team tournaments, **options asset class** (Mike: "maybe" — Alpaca supports options; `AssetRef.asset_class` enum is extensible, sizing/greeks work is the real cost).

---

## 18. Open questions

**For Mike (decisions):** ✅ all three approved 2026-07-12 (promotion tightening TD-10; R-005 $25 live cap; R-014 advisory cooling-off).

**D17 explore-list dispositions (closing the SCOPE §8 checklist item):**
- **Composio** — Phase-1 spike, scoped to *connectors/integrations only* (Mike has credit); never a dependency for core market data (D17's own constraint).
- **Pionex** — pass. A bot-exchange adds nothing over Alpaca + Kraken at our size and adds venue risk.
- **binance.us** — no futures API, so it does not solve the derivatives geo-block; folded into Q1 below.

**SME questions:** Q1 (US-accessible derivatives data), Q2 (paper-fill realism), and Q3 (DSR at small n) were all **resolved by the Gemini adversarial review, 2026-07-12** — dispositions G6, G5, G1 respectively (see [gemini-adversarial-review.md](research/gemini-adversarial-review.md)). No SME questions currently open; queue new ones here as they arise during implementation.

---

*Maintenance rule: this doc and the TD register move together — any TD change updates the table AND the citing sections in the same commit. Contradiction found = bug, fix at the register first.*
