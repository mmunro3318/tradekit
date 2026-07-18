"""`memory._search.search` — `tk search "<query>"` (DESIGN §11; ASSUMPTIONS
round-21 PIN: multi-word = implicit AND, quoted = phrase; SPRINT P3 batch
E). Unconditional `NotImplementedError` stub; every test below describes
REAL target behavior and is red for that reason alone (never wrapped in
`pytest.raises(NotImplementedError)`, same discipline as every other
red-phase file this sprint).
"""

from __future__ import annotations

from tradekit.memory import _search


def _lesson(ledger, make_event, note: str) -> None:
    ledger.append(make_event(type="LessonRecorded", payload={"note": note, "salience": 3}))


def test_multi_word_query_is_implicit_and_of_terms(ledger, make_event) -> None:
    _lesson(ledger, make_event, "promotion halted for review")
    _lesson(ledger, make_event, "promotion granted to T2")
    _lesson(ledger, make_event, "unrelated halt of a different kind")

    results = _search.search(ledger, "docs/wiki", "promotion halted", k=10)

    notes = [r.get("note") or r.get("text") for r in results]
    assert any("promotion halted for review" in (n or "") for n in notes), (
        "a document containing BOTH terms must match"
    )
    assert not any("promotion granted to T2" in (n or "") for n in notes), (
        "implicit AND: a document containing only ONE of the two terms must NOT match"
    )


def test_quoted_query_is_a_literal_adjacent_phrase(ledger, make_event) -> None:
    _lesson(ledger, make_event, "the halt was set for reconcile mismatch")
    _lesson(ledger, make_event, "reconcile found a mismatch, so halt followed")

    results = _search.search(ledger, "docs/wiki", '"halt was set"', k=10)

    notes = [r.get("note") or r.get("text") for r in results]
    assert any("halt was set for reconcile mismatch" in (n or "") for n in notes)
    assert not any("reconcile found a mismatch, so halt followed" in (n or "") for n in notes), (
        "a quoted phrase requires the words ADJACENT in that order — reordered terms must not match"
    )


def test_k_caps_total_results_across_both_sources(ledger, make_event) -> None:
    for i in range(5):
        _lesson(ledger, make_event, f"repeated marker term {i}")

    results = _search.search(ledger, "docs/wiki", "marker", k=2)

    assert len(results) <= 2, "k caps the TOTAL result count, not k-per-source"
