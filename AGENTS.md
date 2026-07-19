# TradeKit — Agent Instructions (Codex / Gemini / other agents)

Event-sourced trading toolkit (Python/uv): thesis-driven paper/live trading with a
policy gate (R-rules) between every agent action and money. P4-paper complete; live
is structurally locked behind four independent locks.

## The gate — run before claiming anything is green
```
uv run pytest -q && uv run ruff check . && uv run mypy
```
Paste its output verbatim in reports. Commit only when green; failing-test commits
must say `(red)` in the message.

## Red lines
- Never execute live trades or enable `live_trading_enabled`.
- Never regenerate golden vectors / frozen fixtures (they require an independent
  re-derivation gate you cannot run alone — flag instead).
- Never edit tests to make implementation pass; never weaken an R-rule test.
- Money-path code (`broker/`, `policy/`) requires review before commit — flag, don't merge.

## On spec ambiguity: flag, never improvise
Add a note in your report; the CTO ratifies into tests/ASSUMPTIONS.md (numbered).

## Docs are part of done
| Doc | Update when |
|---|---|
| docs/ROADMAP.md | task completes (green gate only) |
| cc-dev-log.md | every working session (newest-first, terse) |
| tests/ASSUMPTIONS.md | ratified ambiguity (append-only) |
| docs/FRICTION.md | tool/env/API friction encountered |

## Conventions
- src layout: `src/tradekit/<module>/_impl.py` private modules behind `__init__` verbs.
- Tests protect behavior, not implementation: they must fail when behavior breaks and
  survive behavior-preserving refactors. Determinism seams are
  `mae._runtime.get_closed_bars` / `_clock` monkeypatches only — never mock tradekit internals.
- Deep modules: narrow interface, deep functionality; forwarding wrappers rejected.

## Handoff protocol (Codex)
Work from docs/handoff/CODEX-HANDOFF-CURRENT.md tiers; record the anchor commit;
write a report doc with per-commit gate output. The CTO re-gates your diff before
building on it.
