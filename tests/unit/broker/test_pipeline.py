"""`broker.execute_order` — the two-phase money pipeline (DESIGN §8.2;
SPRINT P3 batch C, pre-registered Opus review focus: TOKEN GATE + HALT
PATH).

Status: RED this batch (`broker._pipeline.execute_order`/`reconcile`/
`cancel_order` are unconditional `NotImplementedError` stubs — CTO's
red/green split call, same discipline as `tests/unit/policy/
test_evaluate.py` in P2 batch C). Every assertion below describes the REAL
behavior the dev pass implements next; nothing here is wrapped in
`pytest.raises(NotImplementedError)`.

Harness pattern (reused verbatim from `tests/unit/thesis/test_grade_verb.py`
's `_build_to_state`): reach `approved` via the REAL `thesis.draft`/
`submit`/`approve` verbs + a harness-appended `ReviewCompleted` (P2 ships no
review verb), with bars/clock faked by monkeypatching
`"tradekit.mae._runtime.get_closed_bars"`/`"..._clock"` by dotted string
path (`thesis.submit()`'s own sanctioned seam). `policy.evaluate()` and
`PaperBroker` are BOTH real this batch — only the pipeline that wires them
together is a stub — so the happy path exercises the REAL rule catalog, the
REAL `_verify_token` ledger check (no monkeypatching of either), never a
canned Verdict.

No hand-derived arithmetic in this file (FIXTURE-FREEZE): order-economics
assertions read the ledger's own `SizingComputed`/`MarketSnapshotTaken`
records back (the SAME values the real `thesis.submit()`/`mae.size_position`
pipeline already computed) and assert a PROPERTY of the pipeline's output
against them, rather than transcribing a hand-computed ATR/Kelly number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from ulid import ULID

from tradekit import broker, thesis
from tradekit.broker._pipeline import OrderNotCancelable, PipelineDenied
from tradekit.broker._port import BrokerTokenRequired
from tradekit.contracts import (
    AssetRef,
    Bar,
    BarSeries,
    Event,
    EventFilter,
    OrderRequest,
    VerdictIssuedPayload,
    VerdictToken,
)
from tradekit.ledger import default_ledger
from tradekit.thesis._machine import IllegalTransition

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_SUBMIT_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20
_PAPER_EQUITY = Decimal("500")


def _flat_atr10_price100_bars(n: int = _N_SUBMIT_BARS) -> BarSeries:
    """Flat open=close=100, high=105/low=95 -> constant True Range 10 ->
    Wilder ATR(14) = 10 (mirrors `tests/replay/test_p2_adversarial.py`'s
    own proven-safe fixture, same rationale documented there): `mae.
    size_position(equity=500)` records recommended_size_usd = risk(1% *
    500 = 5) / stop_pct(2*ATR/price = 20/100 = 0.20) = 25.00 — inside
    R-005's paper cap (10% * 500 = 50) and R-006's cap (20% * 500 = 100),
    and above R-008's $10 floor, so the REAL rule catalog's money-path
    rules clear for an honest order at this notional (a tighter ATR, e.g.
    2, produces a 25%-of-equity position that trips R-005/R-006 by
    design — those caps existing to catch exactly that)."""
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


def _fake_submit_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _flat_atr10_price100_bars()


def _fake_submit_clock() -> datetime:
    return _SUBMIT_BAR_START + timedelta(days=_N_SUBMIT_BARS + 5)  # 2026-01-25


def _market_entry_kwargs(thesis_kwargs: dict, **overrides: object) -> dict:
    """`thesis_kwargs`'s default entry is a LIMIT order (60000.00) — the
    pipeline's own MARKET-entry price rule (entry_price = the last
    MarketSnapshotTaken.last_close) is simpler to pin deterministically
    than the limit-entry rule (entry.limit_price verbatim), so the happy
    path below trades a market entry."""
    kw = dict(thesis_kwargs)
    kw["entry"] = {"order_type": "market", "valid_until": "2026-02-01T00:00:00Z"}
    kw.update(overrides)
    return kw


def _build_approved_thesis(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event, **kwargs_overrides: object
) -> str:
    """Reach `approved` via the REAL draft/submit/approve verbs (mirrors
    `tests/unit/thesis/test_grade_verb.py::_build_to_state`), stopping
    short of `ThesisActivated` — `execute_order` is what appends that
    (via the private `thesis._machine._activate_on_fill` seam, pinned in
    `_pipeline.py`'s module docstring)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _market_entry_kwargs(thesis_kwargs, **kwargs_overrides)
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
        )
    )
    thesis.approve(thesis_id)
    return thesis_id


def _thesis_events(thesis_id: str) -> list:
    return [
        e
        for e in default_ledger().query(EventFilter())
        if e.payload.get("thesis_id") == thesis_id
    ]


def _events_of_type(thesis_id: str, event_type: str) -> list:
    return [e for e in _thesis_events(thesis_id) if e.type == event_type]


# ---------------------------------------------------------------------------
# Happy path — full pipeline, ordering guarantee, thesis activation, token
# ---------------------------------------------------------------------------


def test_execute_order_happy_path_fills_and_activates_the_thesis(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)

    ack = broker.execute_order(thesis_id)

    assert ack.status == "accepted"
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "active", (
        "the first fill must activate the thesis via the private "
        "thesis._machine._activate_on_fill seam, not a public verb"
    )

    fills = _events_of_type(thesis_id, "FillRecorded")
    assert len(fills) == 1
    activated = _events_of_type(thesis_id, "ThesisActivated")
    assert len(activated) == 1
    assert activated[0].payload["order_id"] == fills[0].payload["order_id"]


def test_execute_order_events_appear_in_the_pinned_section_8_2_order(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """DESIGN §8.2's ordering guarantee — ActionProposed < VerdictIssued <
    OrderSubmitted < OrderAck < FillRecorded < ThesisActivated, by ledger
    seq (append order), for THIS thesis's own events."""
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)

    money_path_types = [
        "ActionProposed",
        "VerdictIssued",
        "OrderSubmitted",
        "OrderAck",
        "FillRecorded",
        "ThesisActivated",
    ]
    observed = [e.type for e in _thesis_events(thesis_id) if e.type in money_path_types]
    assert observed == money_path_types, (
        f"observed order {observed} does not match the §8.2 pinned sequence"
    )


def test_execute_order_mints_a_token_that_passes_the_real_verify_token_check(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """No monkeypatch of `PaperBroker._verify_token` anywhere in this test —
    the pipeline's minted `VerdictToken` (verdict_id + policy_version_hash
    off the REAL allow Verdict) must pass the REAL ledger-side check batch
    B built (`_paper.py::_verify_token`)."""
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)

    verdict_issued = _events_of_type(thesis_id, "VerdictIssued")[0]
    assert verdict_issued.payload["allow"] is True

    token = VerdictToken(
        verdict_id=verdict_issued.payload["verdict_id"],
        policy_version_hash=verdict_issued.payload["policy_version_hash"],
    )
    # Re-deriving `PaperBroker._verify_token` success independently: a
    # SECOND submit with the SAME (now-registered) token must not raise
    # BrokerTokenRequired (it may fail for other reasons — e.g. this
    # thesis is already `active` — but never for the token itself).
    account_ref = thesis_kwargs["account_ref"]
    adapter = broker.get(account_ref)
    try:
        adapter._verify_token(token)  # pragma: no branch — exercised for its side effect only
    except BrokerTokenRequired as exc:  # pragma: no cover - defensive
        pytest.fail(f"a token minted from a real allow Verdict must verify: {exc}")


# ---------------------------------------------------------------------------
# Deny path — real R-002/R-003 fail-closed denial for an unconfirmed live
# account_ref; zero Order* events; the Verdict rides PipelineDenied.
# ---------------------------------------------------------------------------


def test_execute_order_deny_path_raises_pipeline_denied_with_zero_order_events(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    # An unconfirmed "live:" account_ref real-denies via R-002 (account_tier
    # None, fail-closed — no PromotionConfirmed on record for this account)
    # without needing to fabricate a canned Verdict.
    thesis_id = _build_approved_thesis(
        thesis_kwargs, monkeypatch, make_event, account_ref="live:unconfirmed-demo"
    )

    with pytest.raises(PipelineDenied) as excinfo:
        broker.execute_order(thesis_id)

    assert excinfo.value.verdict.allow is False
    assert any(hit.rule_id == "R-002" for hit in excinfo.value.verdict.rule_hits)

    for event_type in ("OrderSubmitted", "OrderAck", "FillRecorded"):
        assert _events_of_type(thesis_id, event_type) == [], (
            f"a deny verdict must never produce {event_type} — the money path is "
            "structurally unreachable past step 3"
        )
    assert _events_of_type(thesis_id, "ActionProposed"), "intent must still be recorded"
    assert _events_of_type(thesis_id, "VerdictIssued"), "the deny verdict must still be recorded"
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "approved", (
        "a denied order must never activate the thesis"
    )


# ---------------------------------------------------------------------------
# Broker-raises path — intent + verdict survive a broker-side failure.
# ---------------------------------------------------------------------------


def test_execute_order_when_broker_submit_raises_action_proposed_and_verdict_issued_survive(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)

    class _ExplodingAdapter:
        def submit(self, order, verdict):
            raise RuntimeError("simulated venue outage")

    monkeypatch.setattr("tradekit.broker.get", lambda account_ref: _ExplodingAdapter())

    with pytest.raises(RuntimeError, match="simulated venue outage"):
        broker.execute_order(thesis_id)

    assert _events_of_type(thesis_id, "ActionProposed"), (
        "intent must be recorded before the broker call, and survive its failure"
    )
    assert _events_of_type(thesis_id, "VerdictIssued"), (
        "the verdict must be recorded before the broker call, and survive its failure"
    )
    assert _events_of_type(thesis_id, "OrderSubmitted") == []
    assert _events_of_type(thesis_id, "ThesisActivated") == []


# ---------------------------------------------------------------------------
# Thesis-state guard — only an `approved` thesis may enter execute_order.
# ---------------------------------------------------------------------------


def test_execute_order_refuses_a_thesis_not_in_approved_state(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_submit_clock)
    kw = _market_entry_kwargs(thesis_kwargs)
    thesis_id = thesis.draft(kw)  # still 'draft', never submitted/approved

    with pytest.raises(IllegalTransition) as excinfo:
        broker.execute_order(thesis_id)
    assert excinfo.value.current_state == "draft"


# ---------------------------------------------------------------------------
# R-011 live-sequence decrement boundary — 3 live fills consume the whole
# budget; a 4th is denied. Exercised end-to-end through execute_order for a
# CONFIRMED T2 account (policy.confirm_promotion's own PromotionConfirmed
# grants live_sequence_remaining=3, §7.3/R-011).
# ---------------------------------------------------------------------------


def test_execute_order_r011_denies_the_fourth_live_trade_after_three_confirmed_fills(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """FLAGGED (ASSUMPTIONS round-18): this test exercises the FULL
    live-tier wiring end-to-end (policy._context.assemble's account_tier +
    live_trades_remaining derivation for "live:" refs, batch C's own
    pin — see `_context.py`'s RED-PHASE PIN docstring) — it is RED for
    TWO independent reasons this batch (execute_order itself is a stub,
    AND the live-tier context wiring it depends on is still the P2
    fail-closed carve-out), not just the pipeline stub. The dev pass must
    land BOTH before this test goes green."""
    account_ref = "live:r011-boundary"
    default_ledger().append(
        make_event(
            type="PromotionConfirmed",
            payload={
                "account_ref": account_ref,
                "to_tier": "T2",
                "granted_event_id": "grant-1",
                "live_sequence_remaining": 3,
                "confirmed_by": "mike",
            },
        )
    )

    thesis_ids = [
        _build_approved_thesis(
            thesis_kwargs,
            monkeypatch,
            make_event,
            account_ref=account_ref,
            thesis_id=str(ULID()),
            market_snapshot_id=str(ULID()),
        )
        for _ in range(4)
    ]

    for thesis_id in thesis_ids[:3]:
        ack = broker.execute_order(thesis_id)
        assert ack.status == "accepted"

    with pytest.raises(PipelineDenied) as excinfo:
        broker.execute_order(thesis_ids[3])
    assert any(hit.rule_id == "R-011" for hit in excinfo.value.verdict.rule_hits)


# ---------------------------------------------------------------------------
# Order economics — the qty derivation is a property of the recorded
# SizingComputed value and the market entry price, never hand-derived here.
# ---------------------------------------------------------------------------


def test_execute_order_submitted_qty_matches_the_recorded_sizing_notional(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    sizing_event = _events_of_type(thesis_id, "SizingComputed")[0]
    recommended_size_usd = Decimal(str(sizing_event.payload["sizing"]["recommended_size_usd"]))

    broker.execute_order(thesis_id)

    order_submitted = _events_of_type(thesis_id, "OrderSubmitted")[0]
    qty = Decimal(str(order_submitted.payload["qty"]))
    fill = _events_of_type(thesis_id, "FillRecorded")[0]
    fill_price = Decimal(str(fill.payload["price"]))
    # R-012 sizing purity: the SUBMITTED notional (qty * entry price, priced
    # at the order's own quoted price, not the post-friction fill price)
    # must equal the recorded sizing — this assertion targets that
    # invariant via the market snapshot's own last_close, not the
    # friction-adjusted fill price (which is expected to differ slightly).
    snapshot = _events_of_type(thesis_id, "MarketSnapshotTaken")[0]
    entry_price = Decimal(str(snapshot.payload["last_close"]))
    assert qty * entry_price == recommended_size_usd
    assert fill_price > 0  # the fill happened at a real, friction-adjusted price


# ---------------------------------------------------------------------------
# Limit-entry qty derivation — ADDITIVE coverage closure (CTO-mandated,
# tests/ASSUMPTIONS.md round-18 entry 124 + ratification: "the dev pass MUST
# add one limit-entry pipeline test"). A limit order priced far below every
# fixture bar's low never trades through (G5) -> the single-poll MVP
# observes a still-resting order, cleanly, with zero fill/activation events.
# ---------------------------------------------------------------------------


def test_execute_order_for_a_limit_entry_thesis_rests_with_no_fill(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    thesis_id = _build_approved_thesis(
        thesis_kwargs,
        monkeypatch,
        make_event,
        entry={
            "order_type": "limit",
            # Far below every fixture bar's low (95) — never trades through.
            "limit_price": "1.00",
            "valid_until": "2026-02-01T00:00:00Z",
        },
    )

    ack = broker.execute_order(thesis_id)

    assert ack.status == "accepted"
    order_submitted = _events_of_type(thesis_id, "OrderSubmitted")[0]
    assert order_submitted.payload["order_type"] == "limit"
    assert Decimal(str(order_submitted.payload["limit_price"])) == Decimal("1.00")

    status = broker.get(thesis_kwargs["account_ref"]).order_status(ack.order_id)
    assert status.status == "open", "a resting limit order's single poll must report open"

    assert _events_of_type(thesis_id, "FillRecorded") == [], (
        "a resting limit order has not moved money — zero FillRecorded events"
    )
    assert _events_of_type(thesis_id, "ThesisActivated") == [], (
        "a resting limit order must not activate the thesis (no fill observed yet)"
    )
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "approved"


# ---------------------------------------------------------------------------
# cancel_order — MVP resting/refuse-filled semantics.
# ---------------------------------------------------------------------------


def _seed_allow_verdict(account_ref: str, token: VerdictToken) -> None:
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=_SUBMIT_BAR_START,
            type="VerdictIssued",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=VerdictIssuedPayload(
                verdict_id=token.verdict_id,
                kind="submit_order",
                account_ref=account_ref,
                thesis_id=None,
                allow=True,
                policy_version_hash=token.policy_version_hash,
            ).model_dump(mode="json"),
        )
    )


def _limit_order(account_ref: str, *, limit_price: str = "1.00") -> OrderRequest:
    return OrderRequest(
        thesis_id="TH-cancel-1",
        account_ref=account_ref,
        asset=_ASSET,
        side="buy",
        order_type="limit",
        qty=Decimal("0.001"),
        # far below any fixture bar's low — never trades through, stays resting.
        limit_price=Decimal(limit_price),
    )


def _market_order(account_ref: str) -> OrderRequest:
    return OrderRequest(
        thesis_id="TH-cancel-2",
        account_ref=account_ref,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )


def test_cancel_order_on_a_resting_limit_order_appends_order_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "paper:cancel-resting"
    token = VerdictToken(verdict_id="v-cancel-resting", policy_version_hash="0" * 64)
    _seed_allow_verdict(account_ref, token)
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _SUBMIT_BAR_START)

    adapter = broker.get(account_ref)
    ack = adapter.submit(_limit_order(account_ref), token)
    assert adapter.order_status(ack.order_id).status == "open"

    broker.cancel_order(account_ref, ack.order_id)

    cancelled = [
        e
        for e in default_ledger().query(EventFilter(types=["OrderCancelled"]))
        if e.payload.get("order_id") == ack.order_id
    ]
    assert len(cancelled) == 1
    assert cancelled[0].payload["account_ref"] == account_ref


def test_cancel_order_on_a_filled_order_refuses_and_appends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_ref = "paper:cancel-filled"
    token = VerdictToken(verdict_id="v-cancel-filled", policy_version_hash="0" * 64)
    _seed_allow_verdict(account_ref, token)
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_submit_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _SUBMIT_BAR_START)

    adapter = broker.get(account_ref)
    ack = adapter.submit(_market_order(account_ref), token)  # market orders fill synchronously
    assert adapter.order_status(ack.order_id).status == "filled"

    with pytest.raises(OrderNotCancelable) as excinfo:
        broker.cancel_order(account_ref, ack.order_id)
    assert excinfo.value.order_id == ack.order_id

    cancelled = [
        e
        for e in default_ledger().query(EventFilter(types=["OrderCancelled"]))
        if e.payload.get("order_id") == ack.order_id
    ]
    assert cancelled == []
