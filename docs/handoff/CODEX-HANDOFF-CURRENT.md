# Codex handoff — CURRENT (supersedes CODEX-HANDOFF-2026-07-17.md)

> Standing off-hours shift doc for GPT 5.6 Sol (High) as lead developer.
> Refresh date: 2026-07-18. The 2026-07-17 doc's tiers are DONE — do not
> execute them. All hard rules from that doc remain binding (anchor
> discipline, verbatim gate output, never edit tests, stop-and-flag into
> docs/handoff/CODEX-QUESTIONS.md, checkpoint commits, no force-push).

## Anchor & state

- **Anchor: the newest commit on main when your shift starts** — record it
  as the FIRST line of your report. Suite at refresh time: 781 green
  (`uv run pytest` + `uv run ruff check .` + `uv run mypy` all clean).
- Read order: docs/handoff/HANDOFF-PRIMER.md §1 → SPRINT-P3-P4 doc BOTH
  addenda → tests/ASSUMPTIONS.md rounds 16-23 + every ratification block →
  newest cc-dev-log.md entry (it names the in-flight batch).

## Shift instructions

1. FIRST: `git log --oneline -5` + full gate. If the suite is RED, your
   entire shift is: diagnose, report, fix ONLY if the cause is unambiguous
   (a red TDD batch awaiting its dev pass is NOT broken — check the newest
   commit message; "(red)" commits are deliberate).
2. If a red TDD batch is awaiting its dev pass (commit subject says
   "failing tests"), YOUR TIER 1 is that dev pass: implement to green
   against the frozen tests exactly per the stub docstrings + the sprint
   addendum, one commit, full gate pasted verbatim.
3. TIER 2: the next batch listed in the sprint addendum that has pins but
   no tests — write ONLY the failing tests + stubs per the four-stage
   pattern (study two prior red commits for the house style first), commit
   as "(red)".
4. TIER 3 (>1h remaining): `uv run pytest --cov=src/tradekit
   --cov-report=term` pasted in the report; read-only review of your own
   diff listing anything you'd flag if you were the reviewer.
5. NEVER: touch golden JSONs/frozen fixtures, add dependencies, widen a
   module's verb surface, run live-network anything except
   scripts/smoke_*.py (and only if a tier explicitly says so), or resolve
   an ASSUMPTIONS ambiguity yourself — flag it.

## Report

docs/handoff/CODEX-REPORT-<date>.md: anchor commit, per-tier outcomes,
per-commit hashes + verbatim gate output, STOP-flags, files touched,
observations not acted on. The CTO reviews the full diff against the
anchor before building on it.
