# TradeKit — Claude Instructions

## What this is
Event-sourced trading toolkit (Python/uv): thesis-driven paper/live trading with a
policy gate (R-rules) between every agent action and money. Phase P4-paper complete;
live remains structurally locked behind four independent locks.

gate: uv run pytest -q && uv run ruff check . && uv run mypy

## Red lines
- Never execute live trades or enable `live_trading_enabled`; live locks come off by
  Mike's explicit, per-step instruction only.
- Never regenerate golden vectors or frozen fixtures without the full golden-freeze
  gate (independent re-derivation + external cross-check).
- Never edit tests to make implementation pass; never weaken an R-rule test.
- Money-path code (`broker/`, `policy/`) changes require a review round before commit.

## Doc inventory — update these or the change isn't done
| Doc | Update when |
|---|---|
| docs/ROADMAP.md | task completes (green gate only) |
| cc-dev-log.md | every working session (newest-first, terse) |
| docs/reviews/agent-metrics.md | every review round (table + grades) |
| tests/ASSUMPTIONS.md | any ratified ambiguity (numbered, append-only) |
| docs/FRICTION.md | any tool/env/API friction (tk-friction script) |
| docs/handoff/ | session seams (seed for next session) |

## Conventions
- src layout: `src/tradekit/<module>/_impl.py` private modules behind `__init__` verbs.
- Tests: `tests/unit|contract|replay|golden`; taxonomy + rubric in
  `~/.claude/tk-stack/references/tdd-examples.md`; conformance fixtures own their
  environment setup (no-creds-is-loud).
- Determinism seams: `mae._runtime.get_closed_bars` / `_clock` monkeypatches only —
  never mock tradekit internals.
- Subagent dispatch: 4-stage batch cycle (pin→red→green→gate→review→fix), bespoke
  prompts, `(red)` commit convention.

## Current focus
P4-paper closed. Next: test-audit backlog (docs/reviews/test-audit-2026-07-18.md),
then GitHub remote push (Mike's hands), then P5 planning.
