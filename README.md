# tradekit

An agentic trading framework: **deterministic core, thin LLM shell.** LLM agents (Claude, Codex, Gemini, …) get whitelisted verbs to research markets, register falsifiable "thesis contracts," paper-trade them, and — only after earning it through a promotion ladder — execute small live trades. All enforcement, math, and money-touching happens in boring, testable Python the model cannot bypass.

> **Status (2026-07-12):** P0 complete + metrics core (M1.3). The audit spine works end-to-end: hash-chained event ledger, typed contracts, strategy-edge evaluation, CLI. No market data, no trading yet — that's P1–P4, mapped in [docs/ROADMAP.md](docs/ROADMAP.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and git. Python 3.12 is fetched automatically.

```powershell
git clone <remote>/tradekit && cd tradekit
uv sync            # creates .venv, installs pinned deps
uv run pytest      # 83 tests, ~2s, fully offline — must be green before any work
```

No API keys are needed for anything that currently exists. Later phases add a `.env` (gitignored; see `docs/DESIGN.md` §13/§15 — keys never enter agent context).

## Using it today

Everything goes through the `tk` CLI (`uv run tk …`):

```powershell
uv run tk version
uv run tk schema export                # JSON Schemas for every contract → docs/schemas/
uv run tk ledger verify [--json]       # recompute the hash chain; exit 1 on tampering
uv run tk ledger query --type ThesisDrafted --json
uv run tk ledger rebuild               # re-derive read models from the event log
```

State lives in `data/ledger.db` (created on first use; env `TK_DATA_DIR` overrides). Set `TK_RUN_ID` to stamp every event with an experiment-registry run id.

From Python, the deep-module surfaces (`tradekit.contracts`, `tradekit.ledger`, `tradekit.mae`) are importable directly. The one fully-live analysis verb:

```python
from tradekit.mae import compute_strategy_metrics
m = compute_strategy_metrics(trade_log, n_trials=3, base_equity_usd=Decimal("5000"))
print(m.edge_verdict, m.dsr, m.warnings)   # DESIGN §9.4 gates, G1 small-sample regime
```

## What works right now


| Capability                                                                                                                                                  | Where                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Frozen, typed contracts for every cross-module payload (thesis contract, predicate DSL, events, orders, grades…) + JSON Schema export                      | `tradekit.contracts`                    |
| Append-only, hash-chained event ledger — tamper with *any* column and `verify_chain` names the row; FTS5 search; rebuildable projections; run-id stamping | `tradekit.ledger`                       |
| Strategy-edge math: expectancy/PF/Sharpe/Sortino/Calmar/drawdown + Deflated Sharpe with trials penalty and the small-sample provisional regime              | `tradekit.mae.compute_strategy_metrics` |
| Tick-grid`quantize` (float noise can never flip a grading predicate)                                                                                        | `tradekit.contracts.quantize`           |
| CLI audit surface                                                                                                                                           | `tradekit.cli` (`tk`)                   |

Not yet built: market data, indicators, regime/scanner, policy gates, thesis lifecycle, brokers, review, reporting. Each has a pinned interface and an execution plan in `docs/handoff/`.

## Reading order for a new contributor (human or model)

1. [docs/handoff/HANDOFF-PRIMER.md](docs/handoff/HANDOFF-PRIMER.md) — **start here**; working rules + current state
2. [docs/DESIGN.md](docs/DESIGN.md) — architecture; the TD-register (§2) is binding
3. [docs/ROADMAP.md](docs/ROADMAP.md) — what's next, with done-gates
4. [tests/ASSUMPTIONS.md](tests/ASSUMPTIONS.md) — ratified interface decisions (also binding)
5. [cc-dev-log.md](cc-dev-log.md) — session-by-session history

## Development rules (enforced, not aspirational)

- **TDD, red→green→refactor.** Failing tests are committed before implementation.
- **Deep modules:** a subsystem's public surface is its package `__init__` (≤ ~6 verbs). Underscore internals are lint-banned across module boundaries (TID251 — probe it, it fires).
- **Decimal for money, float for ratios; UTC-aware datetimes only** — all validated at the contract boundary.
- CI (`.github/workflows/ci.yml`): ruff + mypy + pytest on Windows and Ubuntu; tests never touch the network.

Not financial advice. The eventual live bankroll is tuition money, sized to lose (SCOPE §9).
