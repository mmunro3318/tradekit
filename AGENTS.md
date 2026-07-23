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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **tradekit** (5507 symbols, 9617 relationships, 191 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/tradekit/context` | Codebase overview, check index freshness |
| `gitnexus://repo/tradekit/clusters` | All functional areas |
| `gitnexus://repo/tradekit/processes` | All execution flows |
| `gitnexus://repo/tradekit/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
