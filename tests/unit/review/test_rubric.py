"""`review._rubric.score_exchanges` (DESIGN §12.1, SPRINT P3 batch D) --
deterministic Python tally over an already-parsed attack/defense exchange
list. STUB this batch (`NotImplementedError`); every test describes the
REAL target behavior (same red-phase discipline as `test_run_review.py`).
"""

from __future__ import annotations

from tradekit.review._rubric import RUBRIC_CATEGORIES, score_exchanges

_EXCHANGES = [
    {
        "attack": "p_win unjustified.",
        "category": "ev_arithmetic",
        "severity": 2,
        "defense": "cited base rate",
        "resolved": True,
    },
    {
        "attack": "invalidation is just the stop restated.",
        "category": "invalidation_distinctness",
        "severity": 5,
        "defense": "references delisting risk",
        "resolved": False,
    },
    {
        "attack": "sizing looks bumped.",
        "category": "sizing_discipline",
        "severity": 3,
        "defense": "matches SizingComputed exactly",
        "resolved": True,
    },
]


def test_score_exchanges_is_deterministic_across_three_runs() -> None:
    results = [score_exchanges(_EXCHANGES) for _ in range(3)]
    assert results[0] == results[1] == results[2], (
        "score_exchanges must be a pure function -- the SAME exchange list scored "
        "3 times must produce byte-identical output every time (§12.1 determinism pin)"
    )


def test_score_exchanges_counts_unresolved_regardless_of_category() -> None:
    scores = score_exchanges(_EXCHANGES)
    assert scores["unresolved_attack_count"] == 1, (
        "exactly one of the three exchanges has resolved=False -- the count must be "
        "category-agnostic (threshold comparison itself is NOT this function's job)"
    )


def test_score_exchanges_reports_every_rubric_category_even_with_zero_exchanges() -> None:
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
