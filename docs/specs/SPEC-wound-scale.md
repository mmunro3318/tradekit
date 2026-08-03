# SPEC — wound-scale severity migration (minor/major/fatal)

> Branch: `feature/wound-scale`. Ratified: prompts/rubric-thesis-v1.md
> Adjudication §2 (2026-07-25, Mike) — not relitigated here.
> Touches review/ (not money-path) but grading-adjacent → review round
> anyway (sprint discipline: grading volume arrives soon).

## Scope

Migrate review-exchange severity from int 1..5 to the closed enum
`"minor" | "major" | "fatal"` in the exchange schema, the
`score_exchanges` tally, and the parse boundary. Historical mapping
(ratified): 1-2→minor, 3→major, 4-5→fatal.

**Code-reality note (2026-08-03 CTO probe, binding):** blocking today is
`unresolved_attack_count` vs `PolicyDials.unresolved_attack_threshold`
(a COUNT, `_dials.py:133`); severity feeds ONLY the per-category
`max_severity` reporting tally (`_rubric.py:71`). The adjudication's
"fatal replaces the old severity>=4 blocking class everywhere the tally
logic reads severity" therefore has exactly one live site: the tally.
No blocking predicate changes; the dial is untouched (threshold→2 ABORT
stands).

## Out of scope

- Any blocking-predicate change; `unresolved_attack_threshold` semantics
  and default (1) unchanged.
- Rubric categories (still DRAFT pending Mike), per-category thresholds,
  resolve-pass (PARKED 2026-07-25).
- Rewriting historical ledger events (append-only; readers map).
- prompts/rubric-thesis-v1.md prompt-text update instructing reviewers to
  emit the enum — doc edit, done in this batch's close-out, not code.

## Interface pins

```python
# review/_rubric.py:
WOUND_SCALE: tuple[str, ...] = ("minor", "major", "fatal")  # rank order

# Exchange schema (docstring + validation boundary):
"severity": "minor" | "major" | "fatal"     # was: int 1..5

# Legacy mapping — ONE function, the only int→enum site:
def wound_from_legacy(severity: int) -> str:
    # 1|2 -> "minor"; 3 -> "major"; 4|5 -> "fatal"
    # any other value -> ValueError("legacy severity out of range 1..5: {v}")

# score_exchanges tally shape (per category):
{"count": int, "max_severity": "minor" | "major" | "fatal" | None}
# None iff count == 0 (was: 0). "max" = highest WOUND_SCALE rank seen.
# Determinism pin unchanged: pure function, 3 identical calls →
# byte-identical output.

# Parse boundary (review adapters / __init__ pipeline, wherever exchange
# JSON is validated today): severity accepts EITHER the enum string OR a
# legacy int 1..5 (mapped via wound_from_legacy at parse time, so
# score_exchanges only ever sees enum strings). Any other value → the
# pipeline's existing loud schema-rejection path (never a silent clamp).
```

## Acceptance criteria

```
AC-1: GIVEN an exchange list with severities ["minor","fatal","major"]
       in one category
      WHEN score_exchanges runs
      THEN that category tallies count=3, max_severity="fatal"; a category
           with zero exchanges tallies count=0, max_severity=None

AC-2: GIVEN exchanges with severity "major" vs "minor" only
      WHEN score_exchanges runs
      THEN max_severity=="major" (rank order minor<major<fatal, not
           lexicographic — "major" > "minor" lexicographically too, so
           ALSO assert a ["fatal","minor"] case where lexicographic order
           would pick "minor")

AC-3: GIVEN wound_from_legacy inputs 1,2,3,4,5
      WHEN called
      THEN returns minor,minor,major,fatal,fatal respectively

AC-4: GIVEN wound_from_legacy(0), (6), (-1)
      WHEN called
      THEN ValueError naming the offending value — never a clamp

AC-5: GIVEN reviewer-output exchange JSON with legacy int severity 4
       entering the parse boundary
      WHEN the review pipeline validates it
      THEN the exchange reaches score_exchanges with severity "fatal"
           (mapped at parse, tally sees enum only)

AC-6: GIVEN exchange JSON with severity "catastrophic" (or 3.5, or None)
      WHEN the pipeline validates it
      THEN the existing loud schema-rejection path fires (same error
           taxonomy as other malformed-exchange rejections today)

AC-7: determinism regression — same enum exchange list scored 3 times →
      byte-identical dicts (existing pin re-asserted over enum values)

AC-8: existing review-flow tests re-pinned 1:1 per the ratified mapping
      (severity 2→"minor", 3→"major", 4→"fatal", 5→"fatal"), including
      tests/replay/test_p3_end_to_end.py (2→"minor"); zero behavioral
      change to unresolved_attack_count anywhere

AC-9: docs — GLOSSARY wound-scale entry; ASSUMPTIONS numbered append
      (schema change, mapping, None-for-empty, blocking-unchanged note);
      prompts/rubric-thesis-v1.md JSON schema block updated to the enum
```

## Test plan sketch

| AC | Kind | Home |
|---|---|---|
| AC-1,2,7 | BEHAVIOR | tests/unit/review/test_rubric.py |
| AC-3,4 | BEHAVIOR | tests/unit/review/test_rubric.py |
| AC-5,6 | BEHAVIOR | tests/unit/review/test_adapters.py / test_run_review.py (wherever parse-boundary tests live today — test writer probes first) |
| AC-8 | regression re-pin | existing review + replay tests |
| AC-9 | doc inventory (review round) | — |

## Unknowns register

- U1 — exact parse-boundary location (adapters vs __init__ pipeline):
  test writer probes and reports; the pin is the BEHAVIOR (AC-5/6), not
  the file.
- U2 — does anything render rubric_scores (hud/CLI)? If a renderer
  assumes int max_severity, it breaks on None/str — implementer greps
  `max_severity` consumers and flags. Not expected (probe found only
  _rubric.py + contracts passthrough).
