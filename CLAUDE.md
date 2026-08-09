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
- Vocabulary: consult docs/GLOSSARY.md before naming anything that crosses a module boundary — it is the source of truth for cross-module terms, enum values, and naming forms.
- src layout: `src/tradekit/<module>/_impl.py` private modules behind `__init__` verbs.
- Tests: `tests/unit|contract|replay|golden`; taxonomy + rubric in
  `~/.claude/tk-stack/references/tdd-examples.md`; conformance fixtures own their
  environment setup (no-creds-is-loud).
- Determinism seams: `mae._runtime.get_closed_bars` / `_clock` monkeypatches only —
  never mock tradekit internals.
- Subagent dispatch: 4-stage batch cycle (pin→red→green→gate→review→fix), bespoke
  prompts, `(red)` commit convention.

## Current focus
**DATA-VACUUM EXPANSION 2026-08-08/09 — seed: `docs/handoff/HANDOFF-2026-08-09-data-vacuum-expansion.md`
(READ IT FIRST; it carries the pipeline architecture, verified venue-access facts, and the
mistake log).** Greenlist 11 -> 87 pairs; 3 -> 8 live collector streams (Kraken ticks, Coinbase
books+trades, OKX books+trades+liquidations, Hyperliquid perps, Alpaca SIP equities); shared
`scripts/collector_core.py` (VenueSpec + append-only part-file sink); 3 backfillers; archive
in asset-class-partitioned layout (`PARTITION_BY_CLASS = True`). Binance.US retired for OKX.
Tree committed 2026-08-09 (was a full session of uncommitted work).

**PARTITION KEY IS THE ROW'S OWN TIMESTAMP** — seed:
`docs/handoff/HANDOFF-2026-08-09-event-time-partitioning.md`. Fixed 2026-08-09 on branch
`fix/event-time-partitioning`: every sink used to name its file from FLUSH time, so 0.74-18.4%
of rows in every stream sat in the wrong hour (100% of Alpaca's weekend tape in the wrong day).
`PartitionedParquetSink.flush()` takes no `ts` — do not add one back. The three private
per-venue ParquetSinks are retired; they also did read-modify-write, which already corrupted
one hourly file. `scripts/repartition_archive.py` repairs history (dry-run default). Law in
ASSUMPTIONS 179; the how-it-broke story is in docs/FRICTION.md 2026-08-09.

NEXT: (1) merge `fix/event-time-partitioning`; (2) Binance archive backfill
(`scripts/backfill_binance_archive.py`, 0% used, history to 2017); (3) Coinbase book history
before 2026-07-26 does not exist — collection started then, so the "53h July gap" is not a gap;
real repairable loss is ~19h of shared tick+book outage, via `scripts/backfill_books_chd.py`
(its recent-side lag boundary moves daily); (4) enable Alpaca NBBO for IBIT+GLD only;
(5) retention vs. disk — re-measure burn AFTER the repartition settles; the seed's 2.55 GB/day
was taken mid-compaction-backlog and is too high.
Ops gotcha: the watchdog scheduled task was silently failing on `pwsh` (ERROR_FILE_NOT_FOUND) —
always check `LastTaskResult` is 0, a "Ready" state means nothing.

PAPER SPRINT MACHINERY COMPLETE 2026-08-03: batches A-G2 ALL SHIPPED (fee physics, wound-scale,
scan_confluence, registry, S2, S4, hud walk — MTF-SCAN complete; ASSUMPTIONS
170-176, review rounds 14-20). NEXT: (1) MIKE registers the cadence scheduled task (command in
scripts/run_cadence.py header — his hands, two-man pattern); (2) watch
daily digests (docs/digest/) — series progress toward 30, S4
prefilter-kill counts; (3) chips: vocab-validator extraction, regime
pass-through, T-AUDIT-3. ASSUMPTIONS 170-178 = the sprint's law. THREE-THREAD FORK (2026-07-27, Mike) still
stands for the other threads:
docs/handoff/HANDOFF-2026-07-27-paper-sprint.md (superseded by the above), -indicator-lab.md (Mike co-piloted experiments, experiments/ only), -stratchpad.md (charting SPA, starts at tk-brainstorm, read-only vs markets). Background: LIVE PATH VERIFIED (2026-07-26, Mike-run $5 ETH round-trip, flat, net -$0.02) — P4 "done" ratified as Option A: build ~30-trade paper record w/ positive edge → T2 grant → Mike confirms → 3 probationary live trades through the GATED pipeline (live_sequence_remaining=3). Ladder unweakened. PINNED FINDING: Alpaca deducts crypto fees IN-KIND (ETH, not USD) — CostModel/reconcile fix needed before probation (see dev-log 07-26b). Next: (a) paper-record sprint: make funnel emit gradeable trades at pace; (b) in-kind fee batch; (c) MTF-SCAN T-MTF-2..4; (d) wound-scale migration; (e) multi-venue book harvesters (free public APIs). Money-path discipline binding.

