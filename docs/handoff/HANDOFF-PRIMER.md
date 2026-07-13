# HANDOFF PRIMER — read this first, every session

> Written 2026-07-12 by the departing CTO-agent (Fable 5) for its successors (Opus, Sonnet, Haiku) and for Mike. This document is the standing brief: what exists, how to work, and where the traps are. If this doc and reality disagree, reality wins — then fix this doc in the same commit.

## 1. The ten commandments (non-negotiable working rules)

1. **The docs are law, in this order:** `tests/ASSUMPTIONS.md` (interface facts) → `docs/DESIGN.md` TD-register §2 (architecture decisions) → `docs/ROADMAP.md` (sequencing). Changing any of them requires updating the doc AND its dependents in the same commit. Never "temporarily" deviate.
2. **TDD always.** Write failing tests → commit red → implement → commit green → review → commit fixes. If you're writing implementation and no red test exists, stop.
3. **Never widen a public interface.** Each deep module's surface is its `__init__` (≤ ~6 verbs). If your task seems to need a new public function, you have misread the task — re-read the sprint doc's interface pins. Genuinely new surface = a TD-register change = Mike's sign-off.
4. **Never edit a test to make it pass.** If a test looks wrong, say so to Mike with your reasoning and STOP. (History: every "wrong-looking" test so far was right.)
5. **Deterministic core.** No `datetime.now()` outside injected clocks, no randomness without pinned seeds, no network in tests, Decimal for money, aware-UTC datetimes everywhere.
6. **Verify before claiming.** `uv run pytest && uv run ruff check . && uv run mypy` — paste the output. "Should work" is banned vocabulary.
7. **Small commits with honest messages.** red / green / refactor / fix are separate commits. Every commit leaves the suite green (except designated `(red)` commits).
8. **When blocked or 3× failed on the same test: escalate to Mike, don't thrash.** Write down what you tried. Mike can relay questions to the Perplexity SME (give him a paste-ready script — see DESIGN §18 for the format).
9. **Log everything.** Session end = update `cc-dev-log.md` (newest first, terse) + check ROADMAP boxes ONLY for work that is tested, reviewed, and green.
10. **Review each round.** After a green milestone, run a review pass against the sprint doc's checklist (Opus if available). Log defects in `docs/reviews/agent-metrics.md`. Verdict FIX-FIRST means fix before proceeding. Reviews so far found HIGH defects both rounds — do not skip this because "it's probably fine."

## 2. Model role assignment (who does what)

| Model | Role |
|---|---|
| **Opus** | Anything touching DESIGN.md decisions, interface pins, review passes, the P2 policy/promotion logic, debugging escalations. If a sprint doc says "CTO decision," it means Opus + Mike. |
| **Sonnet** | Default implementer. Executes sprint docs task-by-task: writes the red tests exactly from the "Tests to write" section, implements to green, refactors. Also fine for research synthesis. |
| **Haiku** | Scouts only: find-a-thing-in-the-repo, summarize-a-doc, fetch-and-extract. Never let Haiku write src/ code or tests. |

One sprint doc = one or more sessions. Do NOT parallelize two sprint docs that touch the same module.

## 3. State of the world (2026-07-12)

**Done and green (83 tests):**
- P0 complete: `contracts` (all models + predicate DSL + quantize + schema export), `ledger` (hash chain, FTS, projections, rebuild), `tk` CLI (schema/ledger verbs), CI config, replay done-gate.
- M1.3 pulled forward: `mae.compute_strategy_metrics` FULLY implemented (expectancy/PF/Sharpe/Sortino/Calmar/MDD/DSR/penalized-Sharpe, G1 regime). **The math conventions are documented in `src/tradekit/mae/_metrics.py`'s docstring — they are binding; the golden vectors in `tests/unit/mae/` were hand-derived from them.**

**Scaffolded (pinned signature, `NotImplementedError` body):**
- `mae`: `scan_markets`, `get_regime`, `get_derivatives_context`, `size_position`, `get_correlation_matrix` — each stub names its sprint doc.

**Not started:** everything else — see sprint docs below.

**Mike's hands (blockers, in order of need):**
1. GitHub repo `tradekit` + push → first CI run (needed NOW — no offsite backup exists).
2. CoinGecko demo API key (needed for SPRINT-P1A).
3. Kraken **read-only** API key (needed for P3 advisory tracking).
4. Alpaca live keys + $50–100 funding (P4 only — do not create early).

## 4. Sprint sequence (execute in order)

| Doc | Scope | Prereqs |
|---|---|---|
| `SPRINT-P1A-data-layer.md` | MarketDataPort, Kraken/Alpaca/CoinGecko/yfinance providers, cache.db, `tradekit.costs` | none (Kraken is keyless) |
| `SPRINT-P1B-indicators.md` | indicator library + golden vectors | P1A (for the frame type only) |
| `SPRINT-P1C-regime-scanner-sizing.md` | HMM+EWMA regime, scanner, sizing verb, correlation | P1A, P1B |
| `SPRINT-P2-thesis-policy.md` | thesis lifecycle, grading engine, rules R-001–R-016, promotion machine | P1 complete |
| `SPRINT-P3-P4-paper-to-live.md` | PaperBroker, execute_order pipeline, review, reporting, memory, live proof | P2 complete |

## 5. Known traps (each one has already bitten or nearly bitten)

- **The canonical MAE doc's example NUMBERS are illustrative, not golden.** Its Kelly example (`W=.574, R=1.572 → f*=.2102`) does not satisfy its own formula (`f* = W−(1−W)/R = .303`). Trust formulas + our own hand-derived vectors, never the doc's arithmetic.
- **Binance futures API is US-geo-blocked (HTTP 451).** Derivatives = Kraken Futures public first, Coinalyze second (G6). Don't burn a session discovering this again.
- **Alpaca gives exactly ONE paper account.** Multi-account paper trading is OUR PaperBroker (TD-7). Don't try to create more Alpaca paper accounts.
- **`quantize` snaps to the tick GRID, not decimal places** (reviewer D1). Any new price-comparison code must route through it.
- **Naive datetimes are validation errors** at every contract boundary — deliberate (reviewer D2). Don't "fix" by adding tzinfo defaults.
- **The hash preimage covers ALL columns, length-prefixed** (reviewers G-fix + D3). Any events-table schema change must update `_hash.py`, `verify_chain`, AND the tamper tests together.
- **VOID is the #1 gaming vector** (§10.4). When implementing grading: measurable invalidations auto-evaluate; structural ones need attestation + reviewer sign-off; R-015 caps the rate. Do not soften any of the three.
- **Sizing takes NO P&L-history inputs** (TD-11/F6). If a task seems to need account history inside `size_position`, the task is wrong.
- **hmmlearn is NOT installed yet.** P1C adds numpy/pandas/hmmlearn — keep them out of `contracts`/`ledger` (stdlib-only there, by design).
- **Windows dev box.** Watch path separators, CRLF (`.gitattributes` handles it), and never use bare `sqlite3` timestamps without the fixed-width ISO helper in `ledger/_db.py`.

## 6. Session bootstrap checklist (paste into every new session)

```
1. Read docs/handoff/HANDOFF-PRIMER.md (this file)
2. Read the ACTIVE sprint doc in docs/handoff/
3. git log --oneline -10  +  read newest cc-dev-log.md entry
4. uv run pytest  — must be green BEFORE you change anything
5. Do the next unchecked story in the sprint doc, TDD, one story at a time
6. Session end: pytest/ruff/mypy green → commit → dev-log entry → ROADMAP boxes
```
