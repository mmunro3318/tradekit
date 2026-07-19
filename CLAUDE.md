# TradeKit — Claude Instructions

## What this is
Event-sourced trading toolkit (Python/uv): thesis-driven paper/live trading with a
policy gate (R-rules) between every agent action and money. Phase P4-paper complete;
live remains structurally locked behind four independent locks.

gate: uv run pytest -q && uv run ruff check . && uv run mypy

## The Four Principles

|Principle|Addresses|
|---|---|
|**Think Before Coding**|Wrong assumptions, hidden confusion, missing tradeoffs|
|**Simplicity First**|Overcomplication, bloated abstractions|
|**Surgical Changes**|Orthogonal edits, touching code you shouldn't|
|**Goal-Driven Execution**|Leverage through tests-first, verifiable success criteria|

## The Four Principles in Detail
## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

### Code style

- **One concern per function.** 
- **Comments explain *why*, not *what*.** Code can say what. Reserve comments for rationale, especially around known quirks (e.g. "ttl=0 here because conn.query() has a params-cache bug — issue #13644").
- **No new dependencies without flagging.** Note the package + why in your response, not just in code.

## Red lines
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
P4-paper closed. Next: test-audit backlog (docs/reviews/test-audit-2026-07-18.md), then P5 planning.
