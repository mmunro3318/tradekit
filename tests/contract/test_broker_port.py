"""tests/contract/test_broker_port.py — SPRINT P3 story 3.1: `BrokerPort`
conformance suite (TD-18 ring 2, DESIGN §8.1).

Same shape as `test_marketdata_port.py`'s established conformance-suite
pattern: ONE parametrized suite every current `BrokerPort` adapter must
pass, each case built by its own factory function and registered once in
`CASE_BUILDERS` — adding a future adapter is exactly one new factory +
one new registry entry (TD-18's "one factory entry" property).

SKELETON this batch (SPRINT P3 addendum, batch A pin: "write the
assertions now so batch B's PaperBroker drops in"): `CASE_BUILDERS` holds
only a placeholder marker, `pytest.skip`'d with a reason naming batch B
(PaperBroker, the first real adapter) — every assertion body below is
written against the Protocol's real shape so batch B's dev pass only has
to add ONE `CASE_BUILDERS` entry, nothing else in this file changes.

Pins per adapter (§8.1, §15, ASSUMPTIONS round-16):
  - `account()` returns an `AccountState` with every money field `Decimal`
  - `submit()` REFUSES (a typed exception, `BrokerTokenRequired`) when the
    `VerdictToken` is missing/invalid — adapters must not silently submit
    without a real allow-verdict behind them (§8.2, §15's "structurally
    impossible" ordering guarantee)
  - `fills(since)` returns `Fill`s ASCENDING by `ts_utc`
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from tradekit.broker._port import BrokerPort


class BrokerTokenRequired(Exception):
    """Pinned exception NAME (batch A) for an adapter's `submit()` refusal
    when the `VerdictToken` argument is missing/invalid (§8.2, §15) — batch
    B's `PaperBroker.submit` (and every later adapter) raises THIS type, not
    an ad hoc `ValueError`, so callers can catch one thing across every
    venue."""


@dataclass(frozen=True)
class Case:
    """One BrokerPort-conformant adapter's fixture for this suite. `factory`
    builds a fresh adapter instance (a broker adapter is stateful — each
    test gets its own, same discipline as a fresh `tmp_path` ledger)."""

    id: str
    factory: Callable[[], BrokerPort]


def _not_yet_landed_case() -> BrokerPort:  # pragma: no cover — never invoked, see skip below
    raise NotImplementedError("placeholder marker only — see CASE_BUILDERS' skip reason")


# One entry per BrokerPort adapter this suite conforms — the ONLY place a
# future adapter needs to be added (TD-18 "one factory entry" property).
# Batch B adds `"paper": lambda: PaperBroker(account_ref="paper:conformance-suite")`
# (or equivalent) here; nothing else in this file changes.
CASE_BUILDERS: dict[str, Callable[[], BrokerPort]] = {
    "placeholder": _not_yet_landed_case,
}

_SKIP_REASON = (
    "no BrokerPort adapter has landed yet — batch B (PaperBroker, SPRINT P3 addendum "
    "batch plan) adds the first real CASE_BUILDERS entry; this suite's assertions are "
    "written now so PaperBroker drops straight in (story 3.1 pin)"
)


@pytest.fixture(params=list(CASE_BUILDERS), ids=list(CASE_BUILDERS))
def case(request: pytest.FixtureRequest) -> Case:
    if request.param == "placeholder":
        pytest.skip(_SKIP_REASON)
    return Case(id=request.param, factory=CASE_BUILDERS[request.param])


def test_account_returns_account_state_with_decimal_fields(case: Case) -> None:
    broker = case.factory()
    state = broker.account()
    for field in ("equity_usd", "settled_cash_usd", "buying_power_usd"):
        value = getattr(state, field)
        assert isinstance(value, Decimal), (
            f"[{case.id}] AccountState.{field} must be Decimal, got {type(value).__name__} "
            "— money is Decimal end-to-end (TD-3)"
        )


def test_positions_returns_a_list(case: Case) -> None:
    broker = case.factory()
    positions = broker.positions()
    assert isinstance(positions, list), f"[{case.id}] positions() must return a list"


def test_submit_refuses_without_a_valid_verdict_token(case: Case) -> None:
    """§8.2/§15: an adapter must REFUSE `submit` when the `VerdictToken` is
    missing/invalid — the ordering guarantee ("an order without a preceding
    allow-verdict is structurally impossible") is only real if every
    adapter enforces it, not just the pipeline that happens to call it
    correctly."""
    from tradekit.contracts import AssetRef, OrderRequest, VerdictToken

    broker = case.factory()
    order = OrderRequest(
        thesis_id="TH-conformance",
        account_ref="paper:conformance-suite",
        asset=AssetRef(
            symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
        ),
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    bogus_verdict = VerdictToken(verdict_id="not-a-real-verdict", policy_version_hash="0" * 64)
    with pytest.raises(BrokerTokenRequired):
        broker.submit(order, bogus_verdict)


def test_fills_returns_ascending_by_ts_utc(case: Case) -> None:
    broker = case.factory()
    since = datetime(2026, 1, 1, tzinfo=UTC)
    fills = broker.fills(since)
    timestamps = [f.ts_utc for f in fills]
    assert timestamps == sorted(timestamps), (
        f"[{case.id}] fills(since) must return Fills ascending by ts_utc"
    )


def test_order_status_returns_a_typed_order_status(case: Case) -> None:
    from tradekit.contracts import OrderStatus

    broker = case.factory()
    status: Any = broker.order_status("order-does-not-exist")
    assert isinstance(status, OrderStatus), (
        f"[{case.id}] order_status() must return a typed OrderStatus, got "
        f"{type(status).__name__}"
    )
