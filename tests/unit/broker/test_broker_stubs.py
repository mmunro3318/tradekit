"""`tradekit.broker`'s four §4.2-pinned verb stubs (SPRINT P3 batch A) —
each raises `NotImplementedError` naming the batch that lands its real
body; `create_paper_account` (TD-24's additive fifth verb) is REAL this
batch and tested separately in `test_create_paper_account.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradekit import broker
from tradekit.contracts import VerdictToken


def test_get_is_not_yet_implemented_and_names_its_batch() -> None:
    with pytest.raises(NotImplementedError, match="batch B"):
        broker.get("paper:alpha")


def test_execute_order_is_not_yet_implemented_and_names_its_batch() -> None:
    with pytest.raises(NotImplementedError, match="batch C"):
        broker.execute_order("TH-1")


def test_reconcile_is_not_yet_implemented_and_names_its_batch() -> None:
    with pytest.raises(NotImplementedError, match="batch C"):
        broker.reconcile("paper:alpha")


def test_record_manual_fill_is_not_yet_implemented_and_names_its_batch() -> None:
    with pytest.raises(NotImplementedError, match="batch D"):
        broker.record_manual_fill(
            "TH-1", Decimal("10.00"), Decimal("1"), Decimal("0.05")
        )


def test_port_protocol_declares_exactly_five_methods() -> None:
    """DESIGN §8.1: "Five methods". A stray sixth method on `BrokerPort`
    would be a design-smell drift the depth test (§4.2) exists to catch."""
    from tradekit.broker._port import BrokerPort

    protocol_methods = {
        name
        for name in vars(BrokerPort)
        if not name.startswith("_") and callable(getattr(BrokerPort, name, None))
    }
    assert protocol_methods == {"account", "positions", "submit", "order_status", "fills"}


def test_verdict_token_shape_is_unchanged_by_broker_port() -> None:
    # `submit` takes the VerdictToken by value (§8.1) — a smoke check that
    # importing broker._port doesn't require reshaping the existing contract.
    token = VerdictToken(verdict_id="v-1", policy_version_hash="0" * 64)
    assert token.verdict_id == "v-1"
