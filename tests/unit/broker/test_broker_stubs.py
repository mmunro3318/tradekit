"""`tradekit.broker`'s four §4.2-pinned verb stubs (SPRINT P3 batch A) —
each raises `NotImplementedError` naming the batch that lands its real
body; `create_paper_account` (TD-24's additive fifth verb) is REAL this
batch and tested separately in `test_create_paper_account.py`.

`get()` (SPRINT P3 batch B dev pass, superseding this file's own batch-A
placeholder): real for the `"paper:"` prefix now — see
`test_get_resolves_a_paper_prefixed_account_ref_to_a_paper_broker` below,
which replaces the batch-A `NotImplementedError`-naming-its-batch pin this
one function used to encode (that pin is definitionally obsolete once the
verb it describes ships; every other stub below is untouched, still real
`NotImplementedError`s naming their own batch).

`get()`/`execute_order`/`reconcile` (SPRINT P3 batch C dev pass,
superseding this file's own batch-A/B placeholders again — the SAME
obsolescence-update pattern `test_cli_policy.py`'s own docstring documents
for its batch-C/D verbs): `execute_order`/`reconcile` are REAL now (see
`test_pipeline.py`/`test_reconcile.py` for their exhaustive real-behavior
coverage — this file no longer pins them as stubs), and `get()` also
resolves a `"live:"` account_ref to a `PaperBroker` (ASSUMPTIONS round-18
— no real venue adapter lands before batch D, so a confirmed-T2 live
account routes through the same paper simulator until then). Only
`"advisory:"` and `record_manual_fill` remain real `NotImplementedError`
stubs naming batch D.

SPRINT P3 batch D dev pass (obsolescence update, same pattern again):
`get("advisory:*")` now resolves to a real `ManualBroker` instance too
(see the two functions below, renamed from their old
"...is_not_yet_implemented..." names). `record_manual_fill` stays a real
`NotImplementedError` stub, SIGNATURE expanded (`side`/`symbol`/
`account_ref`)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradekit import broker
from tradekit.contracts import VerdictToken


def test_get_resolves_a_paper_prefixed_account_ref_to_a_paper_broker() -> None:
    from tradekit.broker._paper import PaperBroker

    adapter = broker.get("paper:alpha")
    assert isinstance(adapter, PaperBroker)
    assert adapter.account_ref == "paper:alpha"


def test_get_resolves_a_live_prefixed_account_ref_to_a_paper_broker() -> None:
    """SPRINT P3 batch C (ASSUMPTIONS round-18): no real venue adapter
    lands before batch D — a `"live:"` account_ref routes through the SAME
    `PaperBroker` simulator `"paper:"` uses, so a confirmed-T2 live account
    (`policy.confirm_promotion`'s own `PromotionConfirmed`) is a real,
    executable `execute_order` target this batch."""
    from tradekit.broker._paper import PaperBroker

    adapter = broker.get("live:alpaca")
    assert isinstance(adapter, PaperBroker)
    assert adapter.account_ref == "live:alpaca"


def test_get_resolves_an_advisory_prefixed_account_ref_to_a_manual_broker() -> None:
    """SPRINT P3 batch D dev pass, superseding this file's own batch-A/B/C
    placeholder again -- the SAME obsolescence-update pattern this file's
    module docstring already documents twice: `get()` now resolves EVERY
    prefix it recognizes to a real adapter instance, `ManualBroker` for
    `"advisory:*"` (`_manual.py`) -- `ManualBroker`'s individual METHODS
    are still real `NotImplementedError` stubs (`tests/unit/broker/
    test_manual.py` covers those)."""
    from tradekit.broker._manual import ManualBroker

    adapter = broker.get("advisory:kraken")
    assert isinstance(adapter, ManualBroker)
    assert adapter.account_ref == "advisory:kraken"


def test_record_manual_fill_is_not_yet_implemented_and_names_its_batch() -> None:
    """SIGNATURE changed this batch (`side`/`symbol`/`account_ref` added,
    the sprint doc's own pinned shape) -- still a real `NotImplementedError`
    stub naming batch D (`_manual.record_manual_fill`'s dev pass)."""
    with pytest.raises(NotImplementedError, match="batch D"):
        broker.record_manual_fill(
            "TH-1",
            Decimal("10.00"),
            Decimal("1"),
            Decimal("0.05"),
            "buy",
            "BTC/USD",
            "advisory:kraken",
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
