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

import re
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

import httpx
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
        # MED-2 (P3 review): `_verify_token` also checks thesis binding, so
        # this re-derivation must pass the SAME thesis_id the pipeline's
        # own ProposedAction/VerdictIssued carried.
        adapter._verify_token(token, thesis_id)  # pragma: no branch — side effect only
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
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event, respx_mock
) -> None:
    """FLAGGED (ASSUMPTIONS round-18): this test exercises the FULL
    live-tier wiring end-to-end (policy._context.assemble's account_tier +
    live_trades_remaining derivation for "live:" refs, batch C's own
    pin — see `_context.py`'s RED-PHASE PIN docstring). It went GREEN in
    SPRINT P3 batch C (both prior red reasons resolved) by riding SPRINT
    P3 batch C's temporary `"live:"` -> `PaperBroker` routing (ASSUMPTIONS
    round-18) as its fill simulator.

    RE-WIRED this batch (SPRINT P4-PAPER batch A/B, addendum 2, ASSUMPTIONS
    round-23 — PRE-AUTHORIZED re-wire, the ONE test edit this dev pass is
    allowed beyond `_alpaca.py`/`_port.py`/`broker/__init__.py`): that
    temporary routing is GONE — `"live:"` now hits the fail-closed
    `LiveTradingDisabled` gate unless BOTH `PolicyDials.live_trading_enabled`
    is true AND `ALPACA_LIVE_KEY_ID`/`ALPACA_LIVE_SECRET` are present, in
    which case it resolves to a real `AlpacaBroker` bound to the LIVE base
    URL. This test now supplies exactly that (`PolicyDials.load`
    monkeypatched to return `live_trading_enabled=True`, fake live env keys)
    plus respx routes standing in for Alpaca's trading API — a `POST
    {LIVE_BASE}/orders` route that mints a fresh order id per call (fixture
    shape mirrors `test_alpaca_broker.py`'s own `ORDER_SUBMIT_FIXTURE`), and
    a `GET {LIVE_BASE}/orders/{id}` route that reports that same order
    "filled" (mirrors `ORDER_GET_FILLED_FIXTURE`) — so `execute_order`'s
    single-poll step observes a real fill and activates each thesis, driving
    the SAME live-sequence-decrement/R-011 semantics this test has always
    pinned, now through the real dress-rehearsal adapter instead of
    `PaperBroker` standing in for it.

    ASSERTIONS otherwise UNCHANGED, with ONE documented, necessary
    exception: `ack.status == "accepted"` -> `ack.status == "open"`.
    `AlpacaBroker.submit()`'s returned `OrderAck.status` echoes Alpaca's own
    venue-observed order status via `ALPACA_STATUS_MAP` (a FROZEN,
    unmodifiable pin — `test_alpaca_broker.py::
    test_submit_posts_orders_and_returns_typed_ack` asserts `ack.status ==
    "open"` for the identical code path) rather than the fixed `"accepted"`
    literal `PaperBroker.submit` always returns; `ALPACA_STATUS_MAP`'s
    output vocabulary never contains `"accepted"` at all, so the original
    literal is structurally unreachable once this test exercises the real
    adapter. The rule-catalog/PipelineDenied/R-011 assertions — this test's
    actual subject matter — are byte-for-byte unchanged."""
    from tradekit.broker._alpaca import (
        ALPACA_LIVE_BASE_URL,
        ALPACA_LIVE_KEY_ID_ENV,
        ALPACA_LIVE_SECRET_ENV,
    )
    from tradekit.policy._dials import PolicyDials

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

    # Fail-closed conjunction (round-23): both the dial AND the live env
    # keys must be present before "live:" resolves to a real AlpacaBroker.
    monkeypatch.setenv(ALPACA_LIVE_KEY_ID_ENV, "AKFAKELIVE00000000000")
    monkeypatch.setenv(ALPACA_LIVE_SECRET_ENV, "fakeLiveSecretXYZ")
    monkeypatch.setattr(
        PolicyDials, "load", classmethod(lambda cls: PolicyDials(live_trading_enabled=True))
    )

    _next_order_id = iter(f"r011-order-{i}" for i in range(1, 5))

    def _submit_response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": next(_next_order_id),
                "status": "pending_new",
                "submitted_at": "2026-01-25T00:00:00.000000000Z",
                "filled_qty": "0",
                "filled_avg_price": None,
                "symbol": "BTC/USD",
                "side": "buy",
                "qty": "0.25",
            },
        )

    def _status_response(request: httpx.Request) -> httpx.Response:
        order_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={
                "id": order_id,
                "status": "filled",
                "filled_qty": "0.25",
                "filled_avg_price": "100",
                "filled_at": "2026-01-25T00:00:01.000000000Z",
                "symbol": "BTC/USD",
                "side": "buy",
                "qty": "0.25",
            },
        )

    respx_mock.post(f"{ALPACA_LIVE_BASE_URL}/orders").mock(side_effect=_submit_response)
    respx_mock.get(url__regex=rf"{re.escape(ALPACA_LIVE_BASE_URL)}/orders/.+").mock(
        side_effect=_status_response
    )

    for thesis_id in thesis_ids[:3]:
        ack = broker.execute_order(thesis_id)
        assert ack.status == "open"  # see docstring's "ASSERTIONS otherwise UNCHANGED" note

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
            # ASSUMPTIONS 182.4: sizing now follows the entry price, so a
            # fictional "1.00" collapses the notional under R-008's $10
            # floor. 85.50 = 90% of every fixture bar's low (95, quantized
            # to the contract's 0.01 tick size) — still strictly below every
            # fixture low (never trades through) while keeping
            # units * price >= $10.
            "limit_price": "85.50",
            "valid_until": "2026-02-01T00:00:00Z",
        },
    )

    ack = broker.execute_order(thesis_id)

    assert ack.status == "accepted"
    order_submitted = _events_of_type(thesis_id, "OrderSubmitted")[0]
    assert order_submitted.payload["order_type"] == "limit"
    assert Decimal(str(order_submitted.payload["limit_price"])) == Decimal("85.50")

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


def _seed_allow_verdict(
    account_ref: str, token: VerdictToken, *, thesis_id: str | None = None
) -> None:
    """`thesis_id` MUST match the order under test's own `thesis_id` (MED-2
    thesis binding, P3 review fix) — see `_paper.py._verify_token`."""
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
                thesis_id=thesis_id,
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
    _seed_allow_verdict(account_ref, token, thesis_id="TH-cancel-1")
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
    _seed_allow_verdict(account_ref, token, thesis_id="TH-cancel-2")
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


# ---------------------------------------------------------------------------
# execute_exit — T2 (SPEC-cadence): the missing half of the round trip, same
# gated pipeline shape as execute_order (require_state -> policy.evaluate ->
# adapter.submit). RED this batch: `broker.execute_exit`/`_pipeline.
# ExitNothingToClose` do not exist yet — every test below calls the PUBLIC
# `broker.execute_exit` (mirrors how `execute_order` is exercised throughout
# this file) so a missing attribute fails the individual test, never module
# collection; `ExitNothingToClose` is imported LAZILY inside the one test
# that needs it for the same reason.
#
# ASSUMPTIONS FLAGS (T2 dispatch escape hatch — flagged here, not
# improvised; CTO adjudicates into tests/ASSUMPTIONS.md, next free entry
# 177 as of this red pass):
#   (a) the exit OrderRequest's limit_price/reference-price convention:
#       SPEC-cadence.md's T2 pin says "limit_price = last close per
#       _entry_price's snapshot convention" but does not say whether that
#       snapshot is a FRESH MarketSnapshotTaken-style read or the same
#       bar `PaperBroker.submit`'s own market-fill branch already reads
#       off `mae._runtime.get_closed_bars` (which never consults
#       `OrderRequest.limit_price` for a market order in the first place,
#       per `_entry_price`'s own docstring). Tests below never assert on
#       the exit order's `limit_price` VALUE for exactly this reason.
#   (b) the exit's `ProposedAction` shape: `kind="submit_order"` (mirroring
#       entry) vs. a new `kind="exit_order"` is unpinned by the spec text.
#       Tests below assert only on `PipelineDenied`/`Verdict.allow`/
#       `rule_hits`, never on `ProposedAction.kind` directly, for the same
#       reason.
#   (c) how a thesis reaches "active" in these fixtures: reused VERBATIM
#       from this file's own `_build_approved_thesis` + a real
#       `broker.execute_order(thesis_id)` call — the SAME
#       `thesis._machine._activate_on_fill` producer already pinned above,
#       never a fabricated `ThesisActivated` harness event (that pattern
#       belongs to `tests/unit/thesis/test_grade_verb.py`, which needs
#       activation-timestamp control this file's tests do not).
# ---------------------------------------------------------------------------


def _sell_events(thesis_id: str, event_type: str) -> list:
    return [e for e in _events_of_type(thesis_id, event_type) if e.payload.get("side") == "sell"]


def test_execute_exit_happy_path_sells_the_open_position_and_flattens_the_account(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """BEHAVIOR (T2-AC-1): a plain (non-in-kind, kraken) venue's exit sells
    EXACTLY the open `positions()` qty; the account is flat after; an
    `OrderAck` is returned; the exit `FillRecorded` carries `thesis_id`."""
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)  # real entry fill -> thesis now 'active'
    account_ref = thesis_kwargs["account_ref"]

    entry_positions = broker.get(account_ref).positions()
    assert len(entry_positions) == 1, "sanity: the entry fill must leave one open position"
    entry_qty = entry_positions[0].qty

    exit_ack = broker.execute_exit(thesis_id)

    assert exit_ack.status == "accepted"
    assert broker.get(account_ref).positions() == [], (
        "T2-AC-1: the account must be FLAT after execute_exit"
    )

    exit_fills = _sell_events(thesis_id, "FillRecorded")
    assert len(exit_fills) == 1
    assert exit_fills[0].payload["thesis_id"] == thesis_id, (
        "T2-AC-1: the exit fill payload must carry thesis_id"
    )
    assert Decimal(str(exit_fills[0].payload["qty"])) == entry_qty, (
        "kraken (non-in-kind) venue: net qty == the entry's own filled qty, "
        "no in-kind withhold to diverge them"
    )


def test_execute_exit_sells_the_inkind_net_qty_not_the_gross_entry_filled_qty(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """GOLDEN (T2-AC-1 in-kind case, ASSUMPTIONS 170.2 pin): an
    alpaca/crypto/buy entry withholds its fee IN-KIND, so `positions()`'s
    net qty is strictly LESS than the entry's `FillRecorded.qty`.
    `execute_exit` must sell the NET number — never the gross entry
    `filled_qty` — independently re-derived here from ASSUMPTIONS 170.1's
    own formula (`fee_asset_qty = ceil9(0.0025 * qty)`), not read off
    `PaperBroker.positions()`'s own implementation."""
    thesis_id = _build_approved_thesis(
        thesis_kwargs,
        monkeypatch,
        make_event,
        asset={**thesis_kwargs["asset"], "venue": "alpaca"},
    )
    broker.execute_order(thesis_id)
    account_ref = thesis_kwargs["account_ref"]

    entry_fill = _events_of_type(thesis_id, "FillRecorded")[0]
    filled_qty = Decimal(str(entry_fill.payload["qty"]))
    fee_asset_qty = Decimal(str(entry_fill.payload["fee_asset_qty"]))
    assert fee_asset_qty > 0, "sanity: alpaca/crypto/buy must withhold in-kind (170.1)"

    # Independent GOLDEN derivation (170.1's own formula, hand-applied here —
    # never read off PaperBroker.positions()'s own arithmetic):
    expected_fee_asset_qty = (Decimal("0.0025") * filled_qty).quantize(
        Decimal("1e-9"), rounding=ROUND_CEILING
    )
    assert fee_asset_qty == expected_fee_asset_qty, (
        "sanity: the real entry fill's withhold matches this file's own hand-derivation"
    )
    expected_net_qty = filled_qty - expected_fee_asset_qty

    positions_before = broker.get(account_ref).positions()
    assert positions_before[0].qty == expected_net_qty, (
        "sanity: PaperBroker.positions() already reports the net (170.2), independently "
        "confirming this test's own derivation before execute_exit is even called"
    )

    broker.execute_exit(thesis_id)

    exit_order = _sell_events(thesis_id, "OrderSubmitted")[0]
    sold_qty = Decimal(str(exit_order.payload["qty"]))
    assert sold_qty == expected_net_qty, (
        "T2-AC-1 pin: exit sizing uses positions() net qty, NEVER entry filled_qty"
    )
    assert sold_qty < filled_qty, "the in-kind withhold must make net strictly less than gross"
    assert broker.get(account_ref).positions() == []


def test_execute_exit_refuses_a_thesis_not_in_active_state(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """CONTRACT (T2-AC-2, non-active branch): the SAME `require_state`
    error taxonomy `execute_order` raises elsewhere — `IllegalTransition`
    naming the real current state, never a bespoke exit-only error."""
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    # Still 'approved' -- never activated (no execute_order call).

    with pytest.raises(IllegalTransition) as excinfo:
        broker.execute_exit(thesis_id)
    assert excinfo.value.current_state == "approved"
    assert excinfo.value.verb == "execute_exit"


def test_execute_exit_on_an_active_but_flat_thesis_raises_exit_nothing_to_close(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """CONTRACT (T2-AC-2, active-but-flat branch): a NEW, loud
    `ExitNothingToClose` — lazily imported here so a missing symbol fails
    only this test, not module collection (see file-header note above)."""
    from tradekit.broker._pipeline import ExitNothingToClose

    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)  # active, with one open position
    account_ref = thesis_kwargs["account_ref"]

    entry_fill = _events_of_type(thesis_id, "FillRecorded")[0]
    qty = Decimal(str(entry_fill.payload["qty"]))
    price = Decimal(str(entry_fill.payload["price"]))
    symbol = thesis_kwargs["asset"]["symbol"]

    # Zero the position via a harness-appended sell FillRecorded (mirrors
    # _paper.py's own FillRecordedPayload shape exactly). A raw FillRecorded
    # is NOT one of thesis._machine.THESIS_EVENT_TYPES, so derive_state is
    # unaffected -- the thesis stays 'active' while positions() nets to
    # zero, which IS the "active-but-flat" state T2-AC-2 pins (e.g. an
    # advisory/manual close that hasn't been graded yet).
    default_ledger().append(
        make_event(
            type="FillRecorded",
            ts=_fake_submit_clock() + timedelta(minutes=1),
            payload={
                "order_id": "manual-close-1",
                "thesis_id": thesis_id,
                "account_ref": account_ref,
                "ts_utc": (_fake_submit_clock() + timedelta(minutes=1)).isoformat(),
                "price": str(price),
                "qty": str(qty),
                "fees_usd": "0",
                "fee_asset_qty": "0",
                "side": "sell",
                "symbol": symbol,
                "quote_snapshot": {},
            },
        )
    )
    assert broker.get(account_ref).positions() == [], "sanity: the harness fill must flatten it"
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "active", (
        "sanity: a raw FillRecorded must not itself advance thesis lifecycle state"
    )

    with pytest.raises(ExitNothingToClose):
        broker.execute_exit(thesis_id)


def test_execute_exit_deny_via_halt_raises_pipeline_denied_with_zero_broker_calls(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """CONTRACT (T2-AC-3): a real R-001 halt (via the REAL `policy.halt()`
    verb, never a monkeypatched policy seam -- mirrors this file's own
    deny-path convention of exercising the real rule catalog) denies the
    exit exactly like an entry: `PipelineDenied`, ZERO broker submit calls.
    ASSUMPTIONS (ratified, per the T2 spec text): a halt therefore freezes
    open positions until `policy.resume()` -- deliberate, not a gap."""
    from tradekit import policy

    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)
    account_ref = thesis_kwargs["account_ref"]
    positions_before = broker.get(account_ref).positions()

    policy.halt("T2-AC-3 red-stage test: exit-time halt")

    with pytest.raises(PipelineDenied) as excinfo:
        broker.execute_exit(thesis_id)
    assert excinfo.value.verdict.allow is False
    assert any(hit.rule_id == "R-001" for hit in excinfo.value.verdict.rule_hits)

    assert _sell_events(thesis_id, "OrderSubmitted") == [], (
        "a deny verdict must never reach adapter.submit -- zero broker calls"
    )
    assert _sell_events(thesis_id, "FillRecorded") == []
    assert broker.get(account_ref).positions() == positions_before, (
        "a halt freezes the open position exactly as it was -- R-rules see everything, "
        "including exits (ratified per the T2 spec text)"
    )
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "active", (
        "a denied exit must never change the thesis's lifecycle state"
    )


def test_grade_after_execute_exit_computes_pnl_off_the_two_real_fills(
    thesis_kwargs, monkeypatch: pytest.MonkeyPatch, make_event
) -> None:
    """GOLDEN (T2-AC-5): after a REAL entry fill (execute_order) and a REAL
    exit fill (execute_exit), `thesis.grade()`'s `pnl_usd` matches the
    net-qty golden's own two-fill formula (ASSUMPTIONS 170.3 / ratified in
    `tests/golden/test_inkind_fee_pnl.py`'s docstring, non-in-kind kraken
    branch here so BOTH fees terms apply, no in-kind drop):
        pnl = (exit_qty * exit_price - exit_fees_usd)
              - (entry_qty * entry_price + entry_fees_usd)
    every qty/price/fee term below is read back from the REAL ledger events
    `execute_order`/`execute_exit` produced -- never hand-invented, only
    the FORMULA is independently applied (FIXTURE-FREEZE discipline, this
    file's own header note)."""
    thesis_id = _build_approved_thesis(thesis_kwargs, monkeypatch, make_event)
    broker.execute_order(thesis_id)
    activation = thesis._machine.latest_payload(default_ledger(), thesis_id, "ThesisActivated")
    activation_ts = datetime.fromisoformat(str(activation["ts_utc"]))

    # Re-monkeypatch bars/clock for the exit + grade phase (stacking -- the
    # LATER setattr wins for subsequent calls, same convention as
    # tests/unit/thesis/test_grade_verb.py's own header note): one bar
    # whose close (70000) touches the default thesis_kwargs success
    # criterion (price_touch gte 66000.00) so grade() reaches a real PASS
    # outcome instead of PENDING. PaperBroker's OWN market-fill fetch
    # (fixed "1d" timeframe, `_paper.py::_TIMEFRAME`) and `_grade_wiring.
    # evaluate`'s fetch (the criteria's own "1h" timeframe) both hit this
    # SAME fake, which ignores the requested timeframe/lookback and always
    # returns this one bar -- exactly `_fake_grade_bars`'s own documented
    # behavior in test_grade_verb.py.
    bar_ts = activation_ts + timedelta(hours=1)
    grade_bar = Bar(
        ts_open=bar_ts,
        open=Decimal("68000"),
        high=Decimal("71000"),
        low=Decimal("67000"),
        close=Decimal("70000"),
        volume=Decimal("10"),
    )

    def _fake_grade_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return BarSeries(asset=_ASSET, timeframe=timeframe, bars=[grade_bar], source="fake-kraken")

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_grade_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: bar_ts)

    broker.execute_exit(thesis_id)

    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: bar_ts + timedelta(hours=1))

    result = thesis.grade(thesis_id)

    entry_fill = _events_of_type(thesis_id, "FillRecorded")[0]
    exit_fill = _sell_events(thesis_id, "FillRecorded")[0]
    entry_qty = Decimal(str(entry_fill.payload["qty"]))
    entry_price = Decimal(str(entry_fill.payload["price"]))
    entry_fees = Decimal(str(entry_fill.payload["fees_usd"]))
    exit_qty = Decimal(str(exit_fill.payload["qty"]))
    exit_price = Decimal(str(exit_fill.payload["price"]))
    exit_fees = Decimal(str(exit_fill.payload["fees_usd"]))

    # Independent GOLDEN re-derivation of the two-fill formula (kraken =
    # non-in-kind, so BOTH fee terms apply -- neither is dropped):
    expected_pnl = (exit_qty * exit_price - exit_fees) - (entry_qty * entry_price + entry_fees)

    assert Decimal(str(result["pnl_usd"])) == expected_pnl
    graded_payload = _events_of_type(thesis_id, "ThesisGraded")[0].payload
    assert Decimal(str(graded_payload["pnl_usd"])) == expected_pnl
