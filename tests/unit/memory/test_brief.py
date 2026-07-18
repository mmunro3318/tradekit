"""`memory._brief` — `tk brief`'s token-budgeted markdown renderer (DESIGN
§11; sprint-doc addendum, SPRINT P3 batch E). `estimate_tokens` is REAL
(pure arithmetic) — the tests for it are GREEN controls. `render` is an
unconditional `NotImplementedError` stub; every render-behavior test below
describes REAL target behavior and is red for that reason alone (never
wrapped in `pytest.raises(NotImplementedError)`, same discipline as every
other red-phase file this sprint).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tradekit.memory import _brief
from tradekit.policy._dials import PolicyDials

NOW = datetime(2026, 3, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# estimate_tokens — GREEN, pure arithmetic (the addendum's pinned heuristic)
# ---------------------------------------------------------------------------


def test_estimate_tokens_empty_string_is_zero() -> None:
    assert _brief.estimate_tokens("") == 0


def test_estimate_tokens_ceiling_divides_by_four() -> None:
    assert _brief.estimate_tokens("ab") == 1, "len=2 -> ceil(2/4) = 1, never 0 for real content"
    assert _brief.estimate_tokens("abcd") == 1, "len=4 -> exactly 1 token"
    assert _brief.estimate_tokens("abcde") == 2, "len=5 -> ceil(5/4) = 2"
    assert _brief.estimate_tokens("x" * 1500) == 375


# ---------------------------------------------------------------------------
# render — RED (NotImplementedError stub), pins the cap + truncation-order
# ---------------------------------------------------------------------------


def _seed_lessons(ledger, make_event) -> None:
    """Five lessons at every salience level 1..5, each with a long enough
    note that a single dropped LOW-salience lesson materially shrinks the
    render — the section this batch's addendum says gets trimmed FIRST."""
    for salience in range(1, 6):
        ledger.append(
            make_event(
                type="LessonRecorded",
                payload={
                    "note": f"lesson at salience {salience}: " + ("padding " * 40),
                    "salience": salience,
                },
            )
        )


def test_render_never_exceeds_the_hard_token_cap(ledger, make_event) -> None:
    _seed_lessons(ledger, make_event)
    dials = PolicyDials(brief_max_tokens=200)  # deliberately tiny -> forces truncation

    text = _brief.render(ledger, dials, NOW)

    assert _brief.estimate_tokens(text) <= dials.brief_max_tokens, (
        "the hard cap must NEVER be exceeded, even by one section — "
        "sprint-doc: 'never silently overflow'"
    )


def test_render_over_cap_drops_lessons_section_first_lowest_salience(ledger, make_event) -> None:
    _seed_lessons(ledger, make_event)
    dials = PolicyDials(brief_max_tokens=120)

    text = _brief.render(ledger, dials, NOW)

    assert "lesson at salience 1" not in text, (
        "over the cap, the lowest-salience lesson is dropped before any higher-salience one"
    )
    assert _brief.TRUNCATION_MARKER in text, (
        "a truncated brief must carry the pinned '…[truncated]' marker, never a silent drop"
    )


def test_render_never_garbles_mid_sentence(ledger, make_event) -> None:
    """A trimmed section is either FULLY present or FULLY replaced by the
    marker — never a mid-word cut. Every line in the rendered output must
    either be a complete seeded lesson note or the marker line itself."""
    _seed_lessons(ledger, make_event)
    dials = PolicyDials(brief_max_tokens=150)

    text = _brief.render(ledger, dials, NOW)

    for salience in range(1, 6):
        note_fragment = f"lesson at salience {salience}: "
        if note_fragment in text:
            assert ("padding " * 40).strip() in text, (
                f"salience-{salience} lesson, if present at all, must be present IN FULL "
                "(no mid-sentence truncation of an individual entry)"
            )


def test_render_under_cap_includes_every_section_no_marker(ledger, make_event) -> None:
    dials = PolicyDials(brief_max_tokens=1500)  # default cap, tiny history -> well under it
    ledger.append(
        make_event(type="LessonRecorded", payload={"note": "a single short lesson", "salience": 3})
    )

    text = _brief.render(ledger, dials, NOW)

    assert _brief.TRUNCATION_MARKER not in text, "nothing to truncate -> no marker at all"
    assert "a single short lesson" in text
