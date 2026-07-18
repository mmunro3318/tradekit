"""`review.verify_claim(claim) -> dict` (DESIGN §4.2/§12.2/§10.4, SPRINT
P3 batch D) -- rides `LLMReviewerPort`, `kind="void_signoff"` claims are
the P3 debt-closure this batch targets (`thesis.void()`'s reviewer-signoff
guard, P2, was only reachable via a harness-appended `ReviewCompleted`
until now). `tradekit.review.verify_claim` is an unconditional
`NotImplementedError` stub this batch -- every test below is red for that
reason, describing REAL target behavior (same discipline as
`test_run_review.py`).

The EXACT pinned sign-off shape (`tests/unit/thesis/test_void_verb.py`,
module docstring + `_append_void_signoff`): a `ReviewCompleted` event whose
payload is `ReviewCompletedPayload(kind="void_signoff")`, referencing the
thesis by `thesis_id` and the sign-off artifact by `review_artifact_id`,
`passed=True` on success. This file's harness mirrors
`test_void_verb.py::_build_active_thesis` (same house pattern, duplicated
rather than cross-imported -- test modules don't import each other in this
codebase, see e.g. `test_cli_order.py::_build_approved_thesis` doing the
same local-duplication thing)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import review, thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20
GRADE_HORIZON = datetime(2026, 3, 11, tzinfo=UTC)
ACTIVATION_TS = datetime(2026, 3, 1, tzinfo=UTC)

_STRUCTURAL_INVALIDATION = {
    "kind": "structural",
    "description": "exchange delisted the pair -- catalyst structurally dead.",
}

_ALL_RESOLVED_EXCHANGE = [
    {
        "attack": "is this a real structural break, or just a price move the stop covers?",
        "category": "invalidation_distinctness",
        "severity": 4,
        "defense": "the primary listing venue delisted the pair -- no price level fixes that.",
        "resolved": True,
    }
]

_UNRESOLVED_EXCHANGE = [
    {
        "attack": "this reads like the stop restated in prose, not a structural break.",
        "category": "invalidation_distinctness",
        "severity": 4,
        "defense": "it's about delisting.",
        "resolved": False,
    }
]


def _bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_SUBMIT_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _bars()


def _fake_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)


def _build_active_thesis(thesis_kwargs, monkeypatch, make_event) -> str:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_clock)
    kw = dict(thesis_kwargs)
    kw["horizon_end"] = GRADE_HORIZON
    kw["target_price"] = Decimal("66000.00")
    kw["stop_price"] = Decimal("57000.00")
    kw["invalidation"] = _STRUCTURAL_INVALIDATION
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
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    default_ledger().append(
        make_event(
            type="ThesisActivated",
            payload={
                "thesis_id": thesis_id,
                "order_id": "ord-1",
                "ts_utc": ACTIVATION_TS.isoformat(),
            },
            ts=ACTIVATION_TS,
        )
    )
    return thesis_id


class _FakeAdapter:
    def __init__(self, response: str) -> None:
        self._response = response
        self.calls = 0

    def review(self, prompt: str, *, timeout_s: int, max_output_bytes: int) -> str:
        self.calls += 1
        return self._response


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, adapter: _FakeAdapter) -> None:
    monkeypatch.setattr(
        "tradekit.review._adapters.SubprocessReviewerAdapter.from_dials",
        classmethod(lambda cls, dials=None: adapter),
    )


def _attestation_pending_void(thesis_kwargs, monkeypatch, make_event) -> str:
    """Build an active thesis and attempt `thesis.void()` once -- guard 1
    (attestation) passes, guard 2 (reviewer sign-off) refuses -- leaving
    the `InvalidationAttested` audit trail `verify_claim`'s prompt kit
    needs (§10.4 guard 2)."""
    thesis_id = _build_active_thesis(thesis_kwargs, monkeypatch, make_event)
    with pytest.raises(Exception) as exc_info:
        thesis.void(thesis_id, "exchange delisted BTC/USD, catalyst structurally dead")
    assert type(exc_info.value).__name__ == "VoidRefused"
    return thesis_id


def test_verify_claim_void_signoff_pass_emits_the_pinned_reviewcompleted_shape(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _attestation_pending_void(thesis_kwargs, monkeypatch, make_event)
    adapter = _FakeAdapter(json.dumps(_ALL_RESOLVED_EXCHANGE))
    _patch_adapter(monkeypatch, adapter)

    verification = review.verify_claim({"kind": "void_signoff", "thesis_id": thesis_id})

    assert verification["claim_kind"] == "void_signoff"
    assert verification["passed"] is True
    assert verification["review_artifact_id"] is not None

    signoffs = [
        e
        for e in default_ledger().query(EventFilter(types=["ReviewCompleted"]))
        if e.payload.get("thesis_id") == thesis_id and e.payload.get("kind") == "void_signoff"
    ]
    assert len(signoffs) == 1, "verify_claim's pass must emit EXACTLY one signoff event"
    assert signoffs[0].payload["review_artifact_id"] == verification["review_artifact_id"]
    assert signoffs[0].payload["passed"] is True


def test_verify_claim_void_signoff_fail_leaves_thesis_void_still_refused(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    thesis_id = _attestation_pending_void(thesis_kwargs, monkeypatch, make_event)
    adapter = _FakeAdapter(json.dumps(_UNRESOLVED_EXCHANGE))
    _patch_adapter(monkeypatch, adapter)

    verification = review.verify_claim({"kind": "void_signoff", "thesis_id": thesis_id})
    assert verification["passed"] is False

    with pytest.raises(Exception) as exc_info:
        thesis.void(thesis_id, "exchange delisted BTC/USD, catalyst structurally dead")
    assert type(exc_info.value).__name__ == "VoidRefused", (
        "a failed sign-off must leave thesis.void() refused -- verify_claim never "
        "manufactures a passing signoff for a rubric-failed exchange"
    )


def test_end_to_end_structural_void_via_real_verify_claim_succeeds(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    """The debt-closure test (sprint doc): structural-invalidation thesis +
    attestation + a REAL `verify_claim` pass -> `thesis.void()` succeeds --
    P3 closes the P2 void-verb gap end-to-end (no harness-appended
    `ReviewCompleted`, a real `review.verify_claim` call produces it)."""
    thesis_id = _attestation_pending_void(thesis_kwargs, monkeypatch, make_event)
    adapter = _FakeAdapter(json.dumps(_ALL_RESOLVED_EXCHANGE))
    _patch_adapter(monkeypatch, adapter)

    verification = review.verify_claim({"kind": "void_signoff", "thesis_id": thesis_id})
    assert verification["passed"] is True

    thesis.void(thesis_id, "exchange delisted BTC/USD, catalyst structurally dead")

    graded = [
        e
        for e in default_ledger().query(EventFilter(types=["ThesisGraded"]))
        if e.payload.get("thesis_id") == thesis_id
    ]
    assert len(graded) == 1
    assert graded[0].payload["outcome"] == "VOID"
