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
      "severity": int,               # 1 (minor) .. 5 (fatal)
      "defense": str,                # proposer's structured rebuttal
      "resolved": bool,              # reviewer's OWN verdict on the rebuttal
    }
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
    (`test_rubric.py`'s determinism pin, 3 runs)."""
    rubric_scores: dict[str, Any] = {
        category: {"count": 0, "max_severity": 0} for category in RUBRIC_CATEGORIES
    }
    unresolved_attack_count = 0
    for exchange in exchanges:
        category = exchange["category"]
        severity = exchange["severity"]
        if category in rubric_scores:
            entry = rubric_scores[category]
            entry["count"] += 1
            entry["max_severity"] = max(entry["max_severity"], severity)
        if exchange["resolved"] is False:
            unresolved_attack_count += 1
    return {
        "rubric_scores": rubric_scores,
        "unresolved_attack_count": unresolved_attack_count,
    }


__all__ = ["RUBRIC_CATEGORIES", "score_exchanges"]
