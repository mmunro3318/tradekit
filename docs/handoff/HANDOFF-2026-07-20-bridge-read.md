# HANDOFF 2026-07-20 — bridge-read (BRIDGE-UIA feature 1+2)

## TL;DR
BRIDGE-UIA pipeline ran design->spec->tasks->implement. Branch
`feature/bridge-read`: T1-T6 GREEN (841 tests, gate green @6a08c16).
A full-feature review round (tk-reviewer, focus: element-resolution
correctness + read-only discipline) was dispatched and may still be
running/unprocessed — READ ITS REPORT FIRST next session (re-dispatch
if lost; scope fec24cc..6a08c16). T7 (live probe) NOT run.

## Commit ladder (feature branch off main@4ad7d85)
fec24cc SPEC-bridge-read; 042d13e TASKS+ROADMAP; e60cf02 batch1 (red);
258a029 ASSUMPTIONS 154; ac8b70f batch1 green; 4804980 roadmap;
45ddb0b batch2 (red); 2fc30c9 ASSUMPTIONS 155 + friction; 6a08c16
batch2 green (CTO-gate fixes: captured_at kwarg per 155c — driver
never wall-clocks; import-guard teardown fixed properly, implementer's
production-side workaround removed).

## Next session, in order
1. tk-bootstrap; process review-round report; apply fixes (fix commit).
2. T7: implement real pywinauto attach in bridge/_pywinauto.py
   (`uv sync --group bridge` first; real_session() is a stub-after-
   guard), then `uv run python scripts/probe_uia_kraken.py --out
   docs/research/uia-probe-kraken-2026-07.json` with Kraken Desktop
   OPEN (Mike has it open; confirm before running). Grade A/B ->
   author real element map + swap synthetic fixtures via golden-freeze
   gate (ASSUMPTIONS 155a placeholder grammar). Grade C -> STOP,
   design U4 fallback (vision executor), do NOT build write path.
3. Then tk-docs + merge decision (tk-ship) for bridge-read; then
   feature 3 (write path, MONEY-PATH review mandatory) only after
   probe grade + Mike's go.

## Gotchas
- commit-gate hook blocks red commits unless message contains literal
  "(red)" — including docs commits made mid-red-phase.
- test_import_guard.py reload dance previously corrupted the
  tradekit.bridge attribute chain (fixed 6a08c16); watch orderings.
- pywinauto is in optional dep group `bridge` (Windows-only); package
  import must stay green without it (AC-10 pins this).
- P5-PROP batch B (backtest engine) is the OTHER open thread; sprint
  doc docs/handoff/SPRINT-P5-PROP.md. Open from batch A: R-017/R-018
  prop:* PolicyContext wiring, EmpiricalTradeModel, fee-kernel->
  CostModel lift.
- Mike's uncommitted edits (CLAUDE.md, perplexity-SME.md) + untracked
  .claude/, docs/research/deep-research-reports/ — leave alone.
- git push still pending (main is 9+ ahead; feature branch unpushed).
