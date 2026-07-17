# Codex handoff — 2026-07-17 (GPT 5.6 Sol High, lead developer shift)

> Written by the CTO session (Fable). You are the lead developer executing
> against frozen tests and binding pins. Architecture and design decisions are
> NOT yours to make — when a pin is ambiguous or a test looks wrong, STOP that
> work item, write the question into `docs/handoff/CODEX-QUESTIONS.md`, and
> move to the next tier. (House record: 7 consecutive "wrong-looking" tests
> were right; the tests win until the CTO says otherwise.)

## Anchor & rollback

- **Anchor commit: `101288d`** (P2 batch D red: 33 failed / 544 passed —
  expected). If your work goes sideways, the CTO will reset/cherry-pick
  against this anchor. NEVER rebase, amend, or force-push. Small commits,
  honest messages, suffix each: `Co-Authored-By: Codex GPT-5.6 Sol <noreply@openai.com>`.
- Gate before EVERY commit: `uv run pytest` + `uv run ruff check .` +
  `uv run mypy` — paste the VERBATIM last lines into the commit body or your
  report. Never summarize test results in your own words; paste them.

## Hard rules (non-negotiable)

1. NEVER edit a test, golden JSON, or fixture to make it pass. The frozen
   tests define done. Exception: a test whose own comments say it gets
   re-pointed after implementation (planned-obsolescence pins) — the comment
   is the authorization; quote it in the commit message.
2. Read BEFORE writing, in this order: `docs/handoff/HANDOFF-PRIMER.md` §1,
   `docs/handoff/SPRINT-P2-thesis-policy.md` (incl. the CTO addendum at the
   bottom), `tests/ASSUMPTIONS.md` entries 58-92 INCLUDING every CTO
   ratification block. The pins there override your instincts.
3. Scope discipline: implement ONLY what the tier below names. No
   refactors of green code, no dependency additions, no new public surface
   (module `__init__` verb lists are frozen), no "while I'm here" fixes —
   log observations in CODEX-QUESTIONS.md instead.
4. Determinism: no `datetime.now` outside the existing clock seams
   (`mae._runtime.clock`, `policy._context.clock`); Decimal for money;
   tests write only under tmp-pathed seams (TK_DATA_DIR autouse fixture
   exists — do not weaken it).
5. Strict mypy applies to thesis/ and policy/. `except Exception` only where
   an ASSUMPTIONS entry pins a never-raise contract.
6. Checkpoint after each work item: run the full gate, commit, then start
   the next item. Never batch multiple items into one commit.

## Tier 1 — FIRST: finish P2 batch D dev (red 101288d → green, target 577 passed)

The full spec is the dispatch the CTO wrote for this exact task — reproduced
in the stub docstrings + tests. Implement:
1. `src/tradekit/policy/_series.py` — series_index/window_for/series_stats
   per its own docstrings (pure UTC arithmetic; expectancy over non-None pnl
   only, None ⇒ NOT clean; MDD vs equity entering the window).
2. `policy.promotion_status()` / `confirm_promotion()` — T1→T2 machine per
   ASSUMPTIONS 82-92 + ratifications (read-verb-that-writes is ratified;
   edge_verdict=="positive" only; PromotionRefused typed exception).
3. R-016 rewire in `_context.assemble`: real `mae.compute_strategy_metrics`
   (public verb, module-attribute call — tests monkeypatch dotted paths);
   remove batch C's `{"passes_gates": bool}` stand-in entirely.
4. `_projections.py`: real series/promotion_state/pnl_daily materialization
   (grade-time pnl attribution per ASSUMPTIONS; rebuild idempotent).
   TradeRecord derivation for R-016: build the trade log from ThesisGraded +
   thesis contract events; if a required TradeRecord field is genuinely
   underivable from P2 events, STOP and log the question — do not fabricate.
   Frozen tests: tests/unit/policy/test_series.py, test_promotion.py,
   extended test_rebuild.py. Done when: `uv run pytest` → **577 passed, 0
   failed**, ruff+mypy clean. Commit: "P2 batch D: implement series accounting
   + promotion machine to green (577 tests)".

## Tier 2 — then: P2 batch E prep (do NOT write the adversarial scenarios)

Story 5's adversarial replay suite is CTO/Opus-authored — NOT yours. Your
part is the plumbing it needs:
1. `tk grade sweep` auto-discovery: add a minimal read accessor
   `ledger.models.active_theses()` (this is PRE-AUTHORIZED surface — §4.2
   pins `ledger.models` as public; implement only `active_theses() ->
   list[thesis_id]` reading the theses projection) and wire `tk grade sweep`
   (no --thesis args → sweep all active). TDD: write the failing test first
   (tests/unit/cli/), then implement. One commit pair (red, green).
2. Run `uv run python scripts/smoke_scan.py` and paste output into your
   report (live sanity check — network allowed for this one script).
3. Regenerate rules/RULES.md via the generator and confirm zero drift vs the
   committed file (report only).

## Tier 3 — if all green and >1h remains

- `uv run pytest --cov=src/tradekit --cov-report=term` — paste the table in
  your report; list the 5 least-covered non-CLI modules (report only, no
  new tests).
- Read docs/DESIGN.md §8 (broker) + SPRINT-P3-P4 doc and write (to
  CODEX-QUESTIONS.md) any interface questions you'd want answered before a
  P3 shift — questions only, no code.

## Report format (end of shift → docs/handoff/CODEX-REPORT-2026-07-17.md)

Per tier: what's done / what's not, per-commit hashes + verbatim gate
output, every STOP-and-flag question, files touched, anything you noticed
but did NOT act on. The CTO reviews the full diff against the anchor before
building on it — completeness of this report is graded like the code.
