# TASKS-sizing-cap (from SPEC-sizing-cap.md, 2026-09-10)

Branch `feature/sizing-cap` in worktree `.worktrees/sizing-cap`. Money-path
flag: T2 touches `policy/_dials.py` (a derived property, no rule change) —
the review round is mandatory before the green commit regardless.

### T1: `mae.size_position` gains `price` and `max_position_usd`
satisfies: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6a, AC-6b
files: src/tradekit/mae/__init__.py, tests/unit/mae/test_size_position_cap.py
done: AC-1..6 tests green via tk-gate; existing test_size_position_verb.py untouched and green

### T2: `PolicyDials.paper_max_position_usd` property
satisfies: AC-7, AC-8
files: src/tradekit/policy/_dials.py, tests/unit/policy/test_dials.py
done: AC-7/AC-8 green via tk-gate (policy/ touch -> review round before green commit)

### T3: hud sizing seam sizes at the ticket price with the paper cap
satisfies: AC-9, AC-10, AC-11
files: src/tradekit/hud/_build.py, tests/unit/hud/test_build_state_sizing_basis.py
done: AC-9..11 green via tk-gate; AC-9 recorded as failing on the parent commit

### T4: `thesis.submit` sizes at the contract's reference price with the paper cap
satisfies: AC-12, AC-13, AC-14
files: src/tradekit/thesis/_submit.py, tests/unit/thesis/test_submit_sizing_basis.py
done: AC-12..14 green via tk-gate

### T5: cadence — reference price on the market entry, dial sizing basis, loud dead-account skip
satisfies: AC-15, AC-16, AC-17, AC-18, AC-19
files: src/tradekit/cadence/__init__.py, tests/unit/cadence/test_run_once_sizing.py
done: AC-15..19 green via tk-gate; AC-15 and AC-16 recorded as failing on the parent commit

### T6: law + docs
satisfies: AC-2, AC-13 (the "nothing else moved" pins are the law's boundary)
files: tests/ASSUMPTIONS.md, docs/ROADMAP.md, cc-dev-log.md, docs/reviews/agent-metrics.md
done: ASSUMPTIONS 182 appended (one sizing basis; U1 forward pin; U5 paper-only cap); ROADMAP boxes flipped on green; review round graded

## Batches
- RED-A: T1 + T2 tests (one test-writer). RED-B: T3 + T4 + T5 tests (one
  test-writer). Disjoint files -> parallel.
- GREEN: T1..T5 in one implementer pass (T1/T2 are the interface producers;
  T3..T5 consume them — same diff, ordered inside the pass).
- GATE -> REVIEW (tk-reviewer, top model; policy/ touch) -> FIX -> T6.
