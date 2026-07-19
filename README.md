# tradekit

An agentic trading framework: **deterministic core, thin LLM shell.** LLM agents (Claude, Codex, Gemini, …) get whitelisted verbs to research markets, register falsifiable "thesis contracts," paper-trade them, and — only after earning it through a promotion ladder — execute small live trades. All enforcement, math, and money-touching happens in boring, testable Python the model cannot bypass.

> **Status (2026-07-19):** P4-paper complete. The full audit-to-decision spine works: hash-chained event ledger, typed contracts, market data (Kraken/Alpaca), indicators, regime detection, strategy-edge scanner, sizing, policy gate (R-rules), paper/manual brokers, and the **advisory HUD** (`tk hud`) that walks the whole funnel and renders ready-to-transcribe order tickets. Live execution stays structurally locked behind four independent locks — nothing here places a real order. Kraken Prop has no execution API, so the near-term venue (a Kraken Prop eval account) is traded **manually**: the HUD tells you what to do, you do it, and you report the fill back.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and git. Python 3.12 is fetched automatically.

```powershell
git clone <remote>/tradekit && cd tradekit
uv sync                # creates .venv, installs pinned deps
uv run pytest -q       # ~900 tests, fully offline — must be green before any work
uv run ruff check .
uv run mypy
```

No API keys are required for anything above — Kraken's OHLC and public WebSocket
endpoints are keyless. Two **optional** dependency groups add real integrations:

```powershell
uv sync --group collector   # websockets + pyarrow, for scripts/collect_ticks.py
uv sync --group bridge      # pywinauto (Windows only), for `tk bridge` UIA read verbs
```

Alpaca market data (a secondary provider) needs API keys in a gitignored `.env` —
see `docs/DESIGN.md` §13/§15 (keys never enter agent context). Everything else —
Kraken data, the scanner, sizing, the policy gate, the HUD — works keyless out of
the box.

## Using it today

Everything goes through the `tk` CLI (`uv run tk …`). Run commands from the repo
root so `uv` can find `pyproject.toml`.

```powershell
uv run tk --help                       # full command tree
uv run tk version
uv run tk schema export                # JSON Schemas for every contract → docs/schemas/
uv run tk ledger verify [--json]       # recompute the hash chain; exit 1 on tampering
uv run tk ledger query --type ThesisDrafted --json
uv run tk ledger rebuild               # re-derive read models from the event log
```

### The advisory HUD (`tk hud`)

The current headline verb. It walks the real strategy funnel — closed bars →
setup scan (momentum + volume, regime-gated) → min-ATR/quarter-Kelly sizing →
policy verdict — for a list of symbols, and writes a **static HTML file**: a
tabbed "order book" of ready-to-transcribe bracket order tickets (styled to
mirror Kraken's own order form) plus a scan report showing every indicator,
every gate, and the rationale behind each buy/sell/hold/wait grade.

```powershell
uv run tk hud --equity 5000
```

- `--equity` is **required** — your account's *current* equity in USD, not the
  account's nominal size. The tool never guesses this; pass the live number.
- `tk hud` has **no interactive output and never opens a window** — it's a
  file-generator. A silent, quick return with exit code 0 is success. Open the
  result yourself: `docs/hud/hud.html` (default `--out` path) in a browser.
- `--symbols` overrides the default 11-pair greenlist (comma-separated, e.g.
  `--symbols ETH/USD,SOL/USD`).
- The HUD is **advisory only**. Nothing it does touches any exchange, broker,
  or UI automation. Every ticket it renders still has to be manually entered
  by a human, and every fill has to be reported back via `tk fill` /
  `broker.record_manual_fill` so the ledger stays the source of truth.

Other subcommands (`tk thesis`, `tk grade`, `tk policy`, `tk promote`,
`tk account`, `tk order`, `tk fill`, `tk report`, `tk wiki`, `tk bridge`) cover
the rest of the lifecycle — see `tk <command> --help` for each, and
[docs/ROADMAP.md](docs/ROADMAP.md) for what each one is for.

State lives in `data/ledger.db` (created on first use; env `TK_DATA_DIR`
overrides). Set `TK_RUN_ID` to stamp every event with an experiment-registry
run id. `data/` is gitignored — tick/book data and the ledger never get
committed.

From Python, the deep-module surfaces (`tradekit.contracts`, `tradekit.ledger`,
`tradekit.mae`, `tradekit.policy`, `tradekit.broker`, `tradekit.hud`, …) are
importable directly:

```python
from tradekit.mae import compute_strategy_metrics
m = compute_strategy_metrics(trade_log, n_trials=3, base_equity_usd=Decimal("5000"))
print(m.edge_verdict, m.dsr, m.warnings)   # DESIGN §9.4 gates, G1 small-sample regime
```

### Tick/book collector (optional, long-running)

`scripts/collect_ticks.py` connects to Kraken's public WebSocket (trade +
10-level order book) for a fixed symbol greenlist and writes hourly Parquet
files under `data/ticks/`. Requires `uv sync --group collector`.

```powershell
uv run python scripts/collect_ticks.py            # runs until stopped
uv run python scripts/collect_ticks.py --smoke     # short liveness check
```

On this machine it's registered to auto-start at login (Startup-folder
launcher) — do not also start it manually, or you'll get duplicate writers.

## What works right now

| Capability | Where |
|---|---|
| Frozen, typed contracts for every cross-module payload (thesis, orders, prop dials, HUD tickets, events…) + JSON Schema export | `tradekit.contracts` |
| Append-only, hash-chained event ledger — tamper with *any* column and `verify_chain` names the row; FTS5 search; rebuildable projections; run-id stamping | `tradekit.ledger` |
| Market data (Kraken keyless, Alpaca keyed), indicators, 3-state HMM regime detection, evidence-weighted scanner, min-ATR/quarter-Kelly sizing | `tradekit.mae` |
| Policy gate (R-rules) issuing ledgered allow/refuse verdicts before any order proposal | `tradekit.policy` |
| Paper broker, manual/advisory broker (`record_manual_fill`), Alpaca adapter | `tradekit.broker` |
| Prop-account evaluation simulator (scripted + Monte Carlo barrier sim) | `tradekit.prop` |
| Advisory order-book HUD — funnel walk → tabbed ticket book + gated scan report | `tradekit.hud`, `tk hud` |
| UIA read-only reconcile aid (Kraken Desktop has no accessibility tree for write automation — read verbs only) | `tradekit.bridge`, `tk bridge` |
| Live tick/book collector (Kraken WS v2 → Parquet) | `scripts/collect_ticks.py` |
| Strategy-edge math: expectancy/PF/Sharpe/Sortino/Calmar/drawdown + Deflated Sharpe with trials penalty and the small-sample provisional regime | `tradekit.mae.compute_strategy_metrics` |
| Tick-grid `quantize` (float noise can never flip a grading predicate) | `tradekit.contracts.quantize` |
| CLI audit + operator surface | `tradekit.cli` (`tk`) |

Not yet built / structurally locked: **live order execution** (four independent
locks; nothing here can place a real trade), backtest engine batch B (DSR-
dispersion fix, `docs/handoff/`), multi-page bar fetch beyond Kraken's 720-bar
cap (`docs/ROADMAP.md` backlog T-PAGE-1), multi-account HUD support.

## Reading order for a new contributor (human or model)

1. [docs/handoff/](docs/handoff/) — **start here**; the newest file is the current session seed
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
