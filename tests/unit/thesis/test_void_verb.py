"""`thesis.void` — the discretionary structural-invalidation path (DESIGN
§10.4, SPRINT P2 batch B, CTO addendum story-2 pins). This is the #1
gaming vector the sprint doc names explicitly: an agent that can talk its
way to VOID on a loser is farming the win-rate stats. Every test below
pins the REFUSAL path as hard as the success path.

Status: `thesis.void` is still an unconditional `NotImplementedError` stub
this batch — every test is RED for that reason (batch dispatch: "Failing
tests + stubs only").

Typed-exception pin, WITHOUT importing a symbol that doesn't exist yet
(ASSUMPTIONS, this batch — see the module docstring note below): rather than
`with pytest.raises(thesis.VoidRefused)` (which would raise AttributeError
at collection time today, since `VoidRefused` doesn't exist in
`tradekit.thesis` until the dev pass adds it alongside void()'s real body),
every refusal test catches broad `Exception` and asserts
`type(exc.value).__name__ == "VoidRefused"` — collectible today (falls
through to the stub's `NotImplementedError`, whose class name is NOT
"VoidRefused", so the assertion fails cleanly and informatively), and
correctly discriminating once the dev pass adds the real typed exception.

Reviewer-signoff carrier event (CTO adjudication, ASSUMPTIONS 73): the
sign-off is a `ReviewCompleted` event with `kind="void_signoff"` (the
`ReviewCompletedPayload.kind` field is additive+defaulted, landed this
batch). The collision this file's first draft dodged — batch A's
`_machine.derive_state` maps ANY `ReviewCompleted` event to state
`"reviewed"` unguarded, which would clobber an active thesis's derived
state — was adjudicated as a LATENT BATCH-A DEFECT, not a reason to switch
carrier events: the batch-B dev pass must make state derivation a GUARDED
(state, event) -> state table (a `kind="void_signoff"` ReviewCompleted is a
sign-off ARTIFACT, never a lifecycle edge; a `kind="thesis_review"` one only
transitions submitted -> reviewed). That pin has its own red test in
`test_lifecycle.py::
test_review_completed_events_do_not_clobber_state_guarded_transitions`.
Consequence for THIS file: the void success-path tests below (which append a
void_signoff on an active thesis, then expect void() to see `active`) are
red today for two stacked reasons — void() is a stub AND derive_state is
unguarded — and both must be fixed for them to go green.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter, ReviewCompletedPayload
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))

_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20


def _flat_atr2_price100_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_SUBMIT_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_submit_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _flat_atr2_price100_bars()


def _fake_submit_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)


ACTIVATION_TS = datetime(2026, 3, 1, tzinfo=UTC)
GRADE_HORIZON = ACTIVATION_TS + timedelta(days=10)

_STRUCTURAL_INVALIDATION = {
    "kind": "structural",
    "description": "Catalyst thesis structurally broken: primary exchange delisted the pair.",
}
_MEASURABLE_INVALIDATION = {
    "kind": "measurable",
    "predicate": {
        "kind": "price_close",
        "cmp": "lte",
        "value": "40000.00",
        "timeframe": "1d",
        "by": GRADE_HORIZON,
    },
}


def _void_thesis_kwargs(thesis_kwargs: dict, *, invalidation: dict) -> dict:
    kw = dict(thesis_kwargs)
    kw["horizon_end"] = GRADE_HORIZON
    kw["target_price"] = Decimal("66000.00")
    kw["stop_price"] = Decimal("57000.00")
    kw["success_criteria"] = [
        {
            "kind": "price_touch",
            "cmp": "gte",
            "value": "66000.00",
            "timeframe": "1d",
            "by": GRADE_HORIZON,
        }
    ]
    kw["failure_criteria"] = [
        {
            "kind": "price_touch",
            "cmp": "lte",
            "value": "57000.00",
            "timeframe": "1d",
            "by": GRADE_HORIZON,
        }
    ]
    kw["invalidation"] = invalidation
    return kw


def _events(event_type: str):
    return default_ledger().query(EventFilter(types=[event_type]))


def _thesis_events(event_type: str, thesis_id: str):
    return [e for e in _events(event_type) if e.payload.get("thesis_id") == thesis_id]


def _build_to_state(
    thesis_kwargs,
    monkeypatch,
    make_event,
    state: str,
    *,
    invalidation: dict = _STRUCTURAL_INVALIDATION,
) -> str:
    """Reach `state` ∈ {draft, submitted, reviewed, approved} — same
    harness-action pattern as `test_lifecycle.py`/`test_grade_verb.py`."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _void_thesis_kwargs(thesis_kwargs, invalidation=invalidation)
    thesis_id = thesis.draft(kw)
    if state == "draft":
        return thesis_id
    thesis.submit(thesis_id)
    if state == "submitted":
        return thesis_id
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    if state == "reviewed":
        return thesis_id
    thesis.approve(thesis_id)
    if state == "approved":
        return thesis_id
    raise ValueError(f"unhandled state {state!r}")


def _build_active_thesis(
    thesis_kwargs,
    monkeypatch,
    make_event,
    *,
    invalidation: dict = _STRUCTURAL_INVALIDATION,
    activation_ts: datetime = ACTIVATION_TS,
) -> str:
    thesis_id = _build_to_state(
        thesis_kwargs, monkeypatch, make_event, "approved", invalidation=invalidation
    )
    default_ledger().append(
        make_event(
            type="ThesisActivated",
            payload={
                "thesis_id": thesis_id,
                "order_id": "ord-1",
                "ts_utc": activation_ts.isoformat(),
            },
            ts=activation_ts,
        )
    )
    return thesis_id


def _append_void_signoff(make_event, thesis_id: str, artifact_id: str = "voidrev-1") -> None:
    """The reviewer sign-off artifact `void()` requires before it will
    actually VOID a structural attestation (§10.4 guard 2) — EXACTLY the
    shape P3's `review.verify_claim` will emit for real (CTO adjudication,
    ASSUMPTIONS 73): a `ReviewCompleted` event whose payload is
    `ReviewCompletedPayload(kind="void_signoff")`, referencing the thesis by
    `thesis_id` and the sign-off artifact by `review_artifact_id`. Validated
    through the typed model here (ASSUMPTIONS 10 producer pattern) so the
    harness cannot drift from the contract P3 must satisfy."""
    payload = ReviewCompletedPayload(
        thesis_id=thesis_id,
        review_artifact_id=artifact_id,
        passed=True,
        kind="void_signoff",
    )
    default_ledger().append(
        make_event(type="ReviewCompleted", payload=payload.model_dump(mode="json"))
    )


def _assert_raises_named(exc_type_name: str):
    """Context manager: catches broad Exception, then asserts the raised
    exception's CLASS NAME — see module docstring for why this indirection
    is used instead of `pytest.raises(thesis.VoidRefused)` directly."""

    class _Ctx:
        def __enter__(self):
            self._raises = pytest.raises(Exception)
            self.exc_info = self._raises.__enter__()
            return self.exc_info

        def __exit__(self, *exc_args):
            result = self._raises.__exit__(*exc_args)
            assert type(self.exc_info.value).__name__ == exc_type_name, (
                f"expected a {exc_type_name!r}-named exception, got "
                f"{type(self.exc_info.value).__name__!r}: {self.exc_info.value!r}"
            )
            return result

    return _Ctx()


# ---------------------------------------------------------------------------
# 11. Structural invalidation, no reviewer sign-off -> REFUSED (audit trail kept)
# ---------------------------------------------------------------------------


def test_void_structural_without_signoff_refuses_but_keeps_the_attestation_audit_trail(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)

    with _assert_raises_named("VoidRefused"):
        thesis.void(thesis_id, "exchange delisted BTC/USD, catalyst is structurally dead")

    attested = _thesis_events("InvalidationAttested", thesis_id)
    assert len(attested) == 1, (
        "void() must append InvalidationAttested BEFORE checking for the reviewer "
        "sign-off (CTO addendum sequence) — a REFUSED void still leaves an audit trail "
        "of the attestation attempt (§10.4: 'attestation event may exist without void — "
        "that is the audit trail of a REFUSED void')"
    )
    assert attested[0].payload["kind"] == "structural"
    assert attested[0].payload["attestation"] == (
        "exchange delisted BTC/USD, catalyst is structurally dead"
    )

    assert len(_thesis_events("ThesisGraded", thesis_id)) == 0, (
        "a refused void must append NOTHING beyond InvalidationAttested — no ThesisGraded"
    )


def test_void_structural_without_signoff_leaves_thesis_state_unchanged(
    thesis_kwargs, monkeypatch, make_event, raw_sql
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)

    with _assert_raises_named("VoidRefused"):
        thesis.void(thesis_id, "structural break, unreviewed")

    default_ledger().rebuild()
    rows = raw_sql("SELECT state FROM theses WHERE thesis_id = ?", thesis_id)
    assert len(rows) == 1
    assert rows[0][0] == "active", (
        "a REFUSED void must leave the thesis's state UNCHANGED (still active) — "
        "InvalidationAttested is not one of the events the `theses` projection maps to a "
        "state transition (`_projections.py`'s `_THESIS_STATE_BY_EVENT_TYPE`), so this is "
        "true by construction as long as void() appends nothing beyond that one event"
    )


# ---------------------------------------------------------------------------
# 12. Structural invalidation + reviewer sign-off -> VOID
# ---------------------------------------------------------------------------


def test_void_structural_with_reviewer_signoff_emits_thesis_graded_void(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    _append_void_signoff(make_event, thesis_id)

    # The exact sign-off shape void() must gate on — and the exact contract
    # P3's review.verify_claim must emit (CTO adjudication, ASSUMPTIONS 73):
    # a ReviewCompleted event, kind="void_signoff", referencing this thesis.
    signoffs = [
        e
        for e in _thesis_events("ReviewCompleted", thesis_id)
        if e.payload.get("kind") == "void_signoff"
    ]
    assert len(signoffs) == 1
    assert signoffs[0].payload["review_artifact_id"] == "voidrev-1"
    assert signoffs[0].payload["passed"] is True

    thesis.void(thesis_id, "exchange delisted BTC/USD, catalyst is structurally dead")

    attested = _thesis_events("InvalidationAttested", thesis_id)
    assert len(attested) == 1

    graded = _thesis_events("ThesisGraded", thesis_id)
    assert len(graded) == 1
    assert graded[0].payload["outcome"] == "VOID"


def test_void_structural_with_reviewer_signoff_state_becomes_terminal(
    thesis_kwargs, monkeypatch, make_event, raw_sql
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    _append_void_signoff(make_event, thesis_id)

    thesis.void(thesis_id, "structural break, reviewed")

    default_ledger().rebuild()
    rows = raw_sql("SELECT state, graded_outcome FROM theses WHERE thesis_id = ?", thesis_id)
    assert len(rows) == 1
    assert rows[0][0] == "VOID"
    assert rows[0][1] == "VOID"


# ---------------------------------------------------------------------------
# 13. Measurable invalidation -> void() refuses immediately (no discretion allowed)
# ---------------------------------------------------------------------------


def test_void_on_measurable_invalidation_thesis_raises_immediately_no_events_appended(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(
        thesis_kwargs, monkeypatch, make_event, invalidation=_MEASURABLE_INVALIDATION
    )
    before = len(default_ledger().query(EventFilter()))

    # Exception TYPE deliberately unpinned here (unlike the structural-refusal
    # path's VoidRefused): the sprint doc only requires void() to REJECT a
    # measurable-kind thesis, not a specific exception class for this branch.
    with pytest.raises(Exception):  # noqa: B017
        thesis.void(thesis_id, "attempted discretionary void on a measurable invalidation")

    after = len(default_ledger().query(EventFilter()))
    assert after == before, (
        "measurable invalidations auto-VOID inside grade() with zero discretion (§10.4 "
        "guard 1) — void() must reject a measurable-kind thesis BEFORE appending "
        "ANYTHING, not even InvalidationAttested (unlike the structural-refusal path, "
        "which DOES leave an attestation audit trail)"
    )


# ---------------------------------------------------------------------------
# 14. State gate: only approved/active are voidable
# ---------------------------------------------------------------------------


def test_void_on_draft_raises_illegal_transition(thesis_kwargs, monkeypatch, make_event) -> None:
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "draft")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.void(thesis_id, "premature void")
    assert exc.value.current_state == "draft"
    assert exc.value.verb == "void"


def test_void_on_submitted_raises_illegal_transition(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "submitted")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.void(thesis_id, "premature void")
    assert exc.value.current_state == "submitted"


def test_void_on_reviewed_raises_illegal_transition(thesis_kwargs, monkeypatch, make_event) -> None:
    thesis_id = _build_to_state(thesis_kwargs, monkeypatch, make_event, "reviewed")
    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.void(thesis_id, "premature void")
    assert exc.value.current_state == "reviewed"


# ---------------------------------------------------------------------------
# 15. Terminal: void after a successful void is illegal
# ---------------------------------------------------------------------------


def test_void_repeat_after_successful_void_raises_illegal_transition(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    _append_void_signoff(make_event, thesis_id)
    thesis.void(thesis_id, "structural break, reviewed")

    with pytest.raises(thesis.IllegalTransition) as exc:
        thesis.void(thesis_id, "trying again")
    assert exc.value.current_state == "VOID", (
        "a voided thesis is TERMINAL — derive_state reads the outcome off the ThesisGraded "
        "event, same as a graded PASS/FAIL (test_grade_verb.py's already-graded test)"
    )
