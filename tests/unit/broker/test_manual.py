"""`ManualBroker` + `broker.record_manual_fill` (DESIGN §8.4, D16, SPRINT
P3 batch D). `broker.get("advisory:*")` resolution is REAL this batch
(declarative routing, `_manual.py`'s module docstring) -- every METHOD on
`ManualBroker` plus `record_manual_fill` itself is a `NotImplementedError`
stub; tests below describe REAL target behavior and are red for that
reason (same discipline as every other red-phase file this sprint).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tradekit import broker
from tradekit.broker._manual import ManualBroker
from tradekit.broker._port import AdvisoryOnly
from tradekit.contracts import AssetRef, EventFilter, OrderRequest, VerdictToken
from tradekit.ledger import default_ledger


def test_broker_get_advisory_account_ref_resolves_to_a_real_manual_broker() -> None:
    adapter = broker.get("advisory:kraken")
    assert isinstance(adapter, ManualBroker)
    assert adapter.account_ref == "advisory:kraken"


def test_manual_broker_submit_raises_advisory_only() -> None:
    adapter = broker.get("advisory:kraken")
    order = OrderRequest(
        thesis_id="TH-1",
        account_ref="advisory:kraken",
        asset=AssetRef(
            symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
        ),
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    token = VerdictToken(verdict_id="V-1", policy_version_hash="hash-1")

    with pytest.raises(AdvisoryOnly):
        adapter.submit(order, token)


def test_record_manual_fill_appends_a_fill_recorded_event_with_actor_mike() -> None:
    broker.record_manual_fill(
        thesis_id="TH-1",
        price=Decimal("60000.00"),
        qty=Decimal("0.001"),
        fees_usd=Decimal("0.50"),
        side="buy",
        symbol="BTC/USD",
        account_ref="advisory:kraken",
    )

    fills = [
        e
        for e in default_ledger().query(EventFilter(types=["FillRecorded"]))
        if e.payload.get("thesis_id") == "TH-1"
    ]
    assert len(fills) == 1
    assert fills[0].actor == "mike", (
        '§8.4: "Mike executes on Kraken/Cash App -> tk fill record ... writes a FillRecorded '
        'event with actor=mike" -- the ONE human actor in a money-path ledger append'
    )
    assert fills[0].payload["account_ref"] == "advisory:kraken"
    assert fills[0].payload["side"] == "buy"
    assert Decimal(str(fills[0].payload["price"])) == Decimal("60000.00")


def test_record_manual_fill_returns_a_fill_read_model() -> None:
    fill = broker.record_manual_fill(
        thesis_id="TH-2",
        price=Decimal("100.00"),
        qty=Decimal("1"),
        fees_usd=Decimal("0.10"),
        side="sell",
        symbol="AAPL",
        account_ref="advisory:cashapp",
    )
    assert fill.thesis_id == "TH-2"
    assert fill.price == Decimal("100.00")
    assert fill.qty == Decimal("1")
    assert fill.fees_usd == Decimal("0.10")


def test_advisory_account_state_reflects_recorded_fills() -> None:
    broker.record_manual_fill(
        thesis_id="TH-3",
        price=Decimal("50000.00"),
        qty=Decimal("0.01"),
        fees_usd=Decimal("1.25"),
        side="buy",
        symbol="BTC/USD",
        account_ref="advisory:kraken",
    )

    adapter = broker.get("advisory:kraken")
    fills = adapter.fills(since=datetime(2020, 1, 1, tzinfo=UTC))
    assert len(fills) == 1
    assert fills[0].thesis_id == "TH-3"


def test_manual_broker_order_status_reports_rejected_for_any_order_id() -> None:
    # An advisory account never produces an OrderSubmitted event (no submit
    # path exists) -- order_status must behave like PaperBroker's own
    # "no submitted event on record" branch, unconditionally.
    adapter = broker.get("advisory:kraken")
    status = adapter.order_status("O-never-existed")
    assert status.status == "rejected"
