"""`review._rubric.score_exchanges` (DESIGN §12.1, SPRINT P3 batch D) --
deterministic Python tally over an already-parsed attack/defense exchange
list. STUB this batch (`NotImplementedError`); every test describes the
REAL target behavior (same red-phase discipline as `test_run_review.py`).

WOUND-SCALE MIGRATION (docs/specs/SPEC-wound-scale.md, ratified
prompts/rubric-thesis-v1.md Adjudication §2, 2026-07-25): severity is now
the closed enum "minor"|"major"|"fatal" (was int 1..5). `WOUND_SCALE` pins
the rank order; `wound_from_legacy` is the one int->enum mapping site;
`score_exchanges`'s per-category tally now reports `max_severity` as an
enum string or `None` (was: int, 0 for empty) -- rank-based max, not
lexicographic (AC-2's whole point: "fatal" < "minor" lexicographically but
must outrank it)."""

from __future__ import annotations

import pytest

from tradekit.review._rubric import (
    RUBRIC_CATEGORIES,
    WOUND_SCALE,
    score_exchanges,
    wound_from_legacy,
)

_EXCHANGES = [
    {
        "attack": "p_win unjustified.",
        "category": "ev_arithmetic",
        "severity": "minor",  # AC-8 (SPEC-wound-scale): was 2
        "defense": "cited base rate",
        "resolved": True,
    },
    {
        "attack": "invalidation is just the stop restated.",
        "category": "invalidation_distinctness",
        "severity": "fatal",  # AC-8 (SPEC-wound-scale): was 5
        "defense": "references delisting risk",
        "resolved": False,
    },
    {
        "attack": "sizing looks bumped.",
        "category": "sizing_discipline",
        "severity": "major",  # AC-8 (SPEC-wound-scale): was 3
        "defense": "matches SizingComputed exactly",
        "resolved": True,
    },
]


def test_score_exchanges_is_deterministic_across_three_runs() -> None:
    """BEHAVIOR (AC-7): determinism pin re-asserted over enum severity
    values -- same input scored 3 times must be byte-identical."""
    results = [score_exchanges(_EXCHANGES) for _ in range(3)]
    assert results[0] == results[1] == results[2], (
        "score_exchanges must be a pure function -- the SAME exchange list scored "
        "3 times must produce byte-identical output every time (§12.1 determinism pin)"
    )


def test_score_exchanges_counts_unresolved_regardless_of_category() -> None:
    """BEHAVIOR: unresolved-count tally is untouched by the enum migration
    (spec's binding code-reality note -- zero change to this count)."""
    scores = score_exchanges(_EXCHANGES)
    assert scores["unresolved_attack_count"] == 1, (
        "exactly one of the three exchanges has resolved=False -- the count must be "
        "category-agnostic (threshold comparison itself is NOT this function's job)"
    )


def test_score_exchanges_reports_every_rubric_category_even_with_zero_exchanges() -> None:
    """BEHAVIOR: category presence discipline is untouched by the enum
    migration."""
    scores = score_exchanges([])
    for category in RUBRIC_CATEGORIES:
        assert category in scores["rubric_scores"], (
            f"category {category!r} must appear even with zero exchanges in it -- "
            "never silently omitted (distinguishes 'no attack raised' from 'category "
            "doesn't exist')"
        )
    assert scores["unresolved_attack_count"] == 0


def test_score_exchanges_empty_exchange_list_is_deterministic_too() -> None:
    assert score_exchanges([]) == score_exchanges([])


def test_wound_scale_rank_order() -> None:
    """CONTRACT (interface pin): WOUND_SCALE is the closed rank-ordered
    enum tuple -- minor < major < fatal, in that exact order."""
    assert WOUND_SCALE == ("minor", "major", "fatal")


def test_score_exchanges_zero_count_category_has_max_severity_none() -> None:
    """BEHAVIOR (AC-1): a category with zero exchanges tallies count=0,
    max_severity=None -- was 0 under the int scheme; None distinguishes
    'no severity observed' from a real minimum-rank value."""
    scores = score_exchanges([])
    for category in RUBRIC_CATEGORIES:
        entry = scores["rubric_scores"][category]
        assert entry["count"] == 0
        assert entry["max_severity"] is None, (
            f"category {category!r} has zero exchanges -- max_severity must be None, "
            "not 0 (the enum has no zero value) and not omitted"
        )


def test_score_exchanges_tallies_count_and_max_severity_for_three_severities_one_category() -> None:
    """BEHAVIOR (AC-1): three exchanges in ONE category with severities
    minor/fatal/major tally count=3, max_severity='fatal' (the highest
    rank present)."""
    exchanges = [
        {
            "attack": "a1",
            "category": "ev_arithmetic",
            "severity": "minor",
            "defense": "d1",
            "resolved": True,
        },
        {
            "attack": "a2",
            "category": "ev_arithmetic",
            "severity": "fatal",
            "defense": "d2",
            "resolved": True,
        },
        {
            "attack": "a3",
            "category": "ev_arithmetic",
            "severity": "major",
            "defense": "d3",
            "resolved": True,
        },
    ]
    scores = score_exchanges(exchanges)
    entry = scores["rubric_scores"]["ev_arithmetic"]
    assert entry["count"] == 3
    assert entry["max_severity"] == "fatal"


def test_score_exchanges_major_vs_minor_picks_major() -> None:
    """BEHAVIOR (AC-2): straightforward rank comparison -- "major" outranks
    "minor"."""
    exchanges = [
        {
            "attack": "a1",
            "category": "sizing_discipline",
            "severity": "major",
            "defense": "d1",
            "resolved": True,
        },
        {
            "attack": "a2",
            "category": "sizing_discipline",
            "severity": "minor",
            "defense": "d2",
            "resolved": True,
        },
    ]
    scores = score_exchanges(exchanges)
    assert scores["rubric_scores"]["sizing_discipline"]["max_severity"] == "major"


def test_score_exchanges_max_severity_uses_rank_not_lexicographic_order() -> None:
    """BEHAVIOR (AC-2, the case the spec calls out explicitly): "fatal" <
    "minor" lexicographically ('f' < 'm'), so a naive `max()` over the raw
    strings would pick "minor". The correct answer, by WOUND_SCALE rank, is
    "fatal". This is the test that would pass under a buggy lexicographic
    implementation and must NOT."""
    exchanges = [
        {
            "attack": "a1",
            "category": "correlation_awareness",
            "severity": "fatal",
            "defense": "d1",
            "resolved": True,
        },
        {
            "attack": "a2",
            "category": "correlation_awareness",
            "severity": "minor",
            "defense": "d2",
            "resolved": True,
        },
    ]
    scores = score_exchanges(exchanges)
    assert scores["rubric_scores"]["correlation_awareness"]["max_severity"] == "fatal", (
        "lexicographic string comparison would wrongly pick 'minor' here ('f' < 'm') -- "
        "max_severity must be computed by WOUND_SCALE rank, never str.__lt__"
    )


@pytest.mark.parametrize(
    "legacy_severity, expected_enum",
    [
        (1, "minor"),
        (2, "minor"),
        (3, "major"),
        (4, "fatal"),
        (5, "fatal"),
    ],
)
def test_wound_from_legacy_maps_ints_per_ratified_table(
    legacy_severity: int, expected_enum: str
) -> None:
    """GOLDEN (AC-3): the ratified mapping (prompts/rubric-thesis-v1.md
    Adjudication §2) is 1-2->minor, 3->major, 4-5->fatal. Expected values
    hand-derived directly from that table, not from any code under test."""
    assert wound_from_legacy(legacy_severity) == expected_enum


@pytest.mark.parametrize("bad_value", [0, 6, -1])
def test_wound_from_legacy_rejects_out_of_range_values_with_a_named_error(bad_value: int) -> None:
    """BEHAVIOR (AC-4): out-of-range legacy ints raise ValueError naming
    the offending value -- never a clamp to the nearest valid bound."""
    with pytest.raises(ValueError, match=str(bad_value)):
        wound_from_legacy(bad_value)
