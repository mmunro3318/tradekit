"""Deterministic rubric scoring (DESIGN §12.1, TD-21, SPRINT P3 batch D):
"reviewer scores each exchange against the rubric... **deterministic
Python** tallies: any unresolved attack >= severity threshold blocks
approval. The LLM argues; the code decides."

`score_exchanges` is a PURE function -- no I/O, no clock, no randomness --
over the already-parsed JSON exchange list an adapter's `review()` call
produced (parsing/schema validation happens in `review.__init__`'s
pipeline BEFORE this is called; by the time an exchange list reaches here
it is trusted, typed data, not raw subprocess stdout). Determinism pin
(`tests/unit/review/test_rubric.py`): the SAME exchange list scored 3 times
produces byte-identical output every time -- no `dict` iteration-order
dependence, no wall-clock, no set-based dedup that could reorder ties.

Exchange shape (DRAFT, pins `prompts/rubric-thesis-v1.md`'s JSON schema --
Mike has not signed off on the category list/wording yet, only the shape
below): one dict per attack/defense round --
    {
      "attack": str,               # the reviewer's structured criticism
      "category": str,              # one of RUBRIC_CATEGORIES below
      "severity": "minor" | "major" | "fatal",  # closed enum, WOUND_SCALE
      "defense": str,                # proposer's structured rebuttal
      "resolved": bool,              # reviewer's OWN verdict on the rebuttal
    }

WOUND-SCALE MIGRATION (docs/specs/SPEC-wound-scale.md, ratified
prompts/rubric-thesis-v1.md Adjudication §2, 2026-07-25): severity was int
1..5, now the closed enum above. `WOUND_SCALE` pins the rank order (never
lexicographic); `wound_from_legacy` is the ONE int->enum mapping site, used
at the parse boundary (`review/__init__.py::_call_reviewer_and_score`) --
by the time an exchange list reaches `score_exchanges` it is guaranteed to
carry enum strings only.
"""

from __future__ import annotations

from typing import Any

# Rubric categories (DRAFT, mirrors prompts/rubric-thesis-v1.md -- NOT yet
# Mike-ratified, sprint doc's own deferred-flag: "rubric-thesis-v1.md shape
# (draft for his edit)"). Order is significant for `rubric_scores`'
# per-category breakdown determinism (insertion order, never re-sorted).
RUBRIC_CATEGORIES: tuple[str, ...] = (
    "catalyst_falsifiability",
    "ev_arithmetic",
    "invalidation_distinctness",
    "sizing_discipline",
    "correlation_awareness",
)

# Wound-scale rank order (SPEC-wound-scale.md): minor < major < fatal.
# `max_severity` is computed by rank via this tuple's index, never by
# str.__lt__ -- "fatal" < "minor" lexicographically but must outrank it.
WOUND_SCALE: tuple[str, ...] = ("minor", "major", "fatal")


def wound_from_legacy(severity: int) -> str:
    """The ONE legacy int->enum mapping site (ratified table,
    prompts/rubric-thesis-v1.md Adjudication §2): 1|2->"minor", 3->"major",
    4|5->"fatal". Any other value raises ValueError naming it -- never a
    clamp (AC-4)."""
    if severity in (1, 2):
        return "minor"
    if severity == 3:
        return "major"
    if severity in (4, 5):
        return "fatal"
    raise ValueError(f"legacy severity out of range 1..5: {severity}")


def score_exchanges(exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    """Pinned target algorithm (dev pass lands this; STUB this batch):
    tally per-category exchange counts/max-severity into a `rubric_scores`
    dict keyed by `RUBRIC_CATEGORIES` (categories with zero exchanges still
    appear, count=0 -- never silently omitted, so a caller can distinguish
    "no attack raised in this category" from "category doesn't exist yet"),
    and count `unresolved_attack_count` = the number of exchanges where
    `resolved is False`, regardless of category (the threshold COMPARISON
    against `PolicyDials.unresolved_attack_threshold` happens in
    `review.__init__.run_review`, not here -- this function reports the
    raw count only, staying threshold-agnostic so a dial change never
    requires touching the scorer).

    MUST be a pure function of `exchanges` alone: no `datetime.now()`, no
    `random`, no set/dict ordering that isn't insertion-stable -- three
    calls with the identical input list must return byte-identical dicts
    (`test_rubric.py`'s determinism pin, 3 runs).

    `exchanges` is assumed to already carry enum-string severities only --
    the parse boundary (`review/__init__.py`) guarantees this. A stray
    non-enum value fails loudly (ValueError from the WOUND_SCALE rank
    lookup, checked on EVERY exchange -- including a category's first, so
    a single-exchange category can never tally a non-enum silently)."""
    rubric_scores: dict[str, Any] = {
        category: {"count": 0, "max_severity": None} for category in RUBRIC_CATEGORIES
    }
    unresolved_attack_count = 0
    for exchange in exchanges:
        category = exchange["category"]
        severity = exchange["severity"]
        if category in rubric_scores:
            entry = rubric_scores[category]
            entry["count"] += 1
            current = entry["max_severity"]
            # .index() on every exchange (not just rank comparisons) so a
            # category's FIRST stray non-enum value dies loudly too --
            # never assigned into the tally unvalidated.
            rank = WOUND_SCALE.index(severity)
            if current is None or rank > WOUND_SCALE.index(current):
                entry["max_severity"] = severity
        if exchange["resolved"] is False:
            unresolved_attack_count += 1
    return {
        "rubric_scores": rubric_scores,
        "unresolved_attack_count": unresolved_attack_count,
    }


__all__ = ["RUBRIC_CATEGORIES", "WOUND_SCALE", "score_exchanges", "wound_from_legacy"]
