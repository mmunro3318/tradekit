"""tests/contract/test_broker_port.py — SPRINT P3 story 3.1: `BrokerPort`
conformance suite (TD-18 ring 2, DESIGN §8.1).

Same shape as `test_marketdata_port.py`'s established conformance-suite
pattern: ONE parametrized suite every current `BrokerPort` adapter must
pass, each case built by its own factory function and registered once in
`CASE_BUILDERS` — adding a future adapter is exactly one new factory +
one new registry entry (TD-18's "one factory entry" property).

SPRINT P3 batch B (PaperBroker, the first real adapter) lands the first real
`CASE_BUILDERS` entry (`"paper"`) below — the placeholder marker from batch A
is gone, so this suite now runs FOR REAL (no longer skipped) for the "paper"
case. `BrokerTokenRequired` is imported from its canonical home
(`tradekit.broker._port`, SPRINT P3 batch B) rather than defined locally —
batch A's local class could never have matched a real adapter's raised
exception by identity (`pytest.raises` matches by class, not by name); moving
it fixes that latent gap rather than carrying it forward (ASSUMPTIONS,
this batch).

Pins per adapter (§8.1, §15, ASSUMPTIONS round-16):
  - `account()` returns an `AccountState` with every money field `Decimal`
  - `submit()` REFUSES (a typed exception, `BrokerTokenRequired`) when the
    `VerdictToken` is missing/invalid — adapters must not silently submit
    without a real allow-verdict behind them (§8.2, §15's "structurally
    impossible" ordering guarantee)
  - `fills(since)` returns `Fill`s ASCENDING by `ts_utc`

Batch B status: `PaperBroker`'s methods are `NotImplementedError` stubs
(fill-model dev pass lands after this red-phase session) — every case for
"paper" below is therefore expected RED this batch, not skipped; the
`BrokerTokenRequired` assertion specifically stays red because batch B's
`submit()` doesn't reach even a shape-only token check yet (see
`tests/unit/broker/test_paper_fills.py` for the token-required pin that
prescribes the dev pass's real behavior).

SPRINT P4-PAPER batch A adds the "alpaca-paper" case (`_build_alpaca_
paper_case`, TD-18's "one factory entry" property — the ONLY change this
suite itself needs for a new adapter). `AlpacaBroker`'s five methods are
`NotImplementedError` stubs this batch (`src/tradekit/broker/_alpaca.py`'s
own module docstring — batch B lands the real bodies), so every "alpaca-
paper" case below is expected RED this batch, same status "paper" cases
had in SPRINT P3 batch A before PaperBroker's own dev pass landed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from tradekit.broker._paper import PaperBroker
from tradekit.broker._port import BrokerPort, BrokerTokenRequired


@dataclass(frozen=True)
class Case:
    """One BrokerPort-conformant adapter's fixture for this suite. `factory`
    builds a fresh adapter instance (a broker adapter is stateful — each
    test gets its own, same discipline as a fresh `tmp_path` ledger)."""

    id: str
    factory: Callable[[], BrokerPort]


def _build_paper_case() -> BrokerPort:
    """SPRINT P3 batch B's first real `CASE_BUILDERS` entry: seeds a fresh
    `AccountCreated` on the (per-test, `TK_DATA_DIR`-isolated, autouse
    fixture) default ledger via the already-real `broker.create_paper_account`
    (TD-24, batch A), then hands back a `PaperBroker` bound to that
    `account_ref` — "a fresh instance per test", per `Case`'s own docstring.
    A fresh `account_ref` per call (ULID suffix) avoids
    `AccountAlreadyExists` across the multiple cases pytest builds from this
    one factory (one per parametrized test function)."""
    from ulid import ULID

    from tradekit import broker
    from tradekit.contracts import AccountConfig

    account_ref = f"paper:conformance-suite-{ULID()}"
    broker.create_paper_account(
        AccountConfig(
            account_ref=account_ref,
            principal_usd=Decimal("500.00"),
            max_trades_per_day=0,
        )
    )
    return PaperBroker(account_ref=account_ref)


def _build_alpaca_paper_case() -> BrokerPort:
    """SPRINT P4-PAPER batch A's `CASE_BUILDERS` entry for the dress-
    rehearsal adapter: a fresh `account_ref` per call (ULID suffix, same
    "fresh instance per test" discipline as `_build_paper_case`), bound to
    Alpaca's PAPER base URL + the paper env key names. No `AccountCreated`
    seed needed here (unlike `PaperBroker`'s ledger-projection `account()`,
    `AlpacaBroker`'s real body will read Alpaca's own `/account` endpoint,
    not a ledger event) — irrelevant anyway this batch since every method
    is a `NotImplementedError` stub."""
    from ulid import ULID

    from tradekit.broker._alpaca import (
        ALPACA_PAPER_BASE_URL,
        ALPACA_PAPER_KEY_ID_ENV,
        ALPACA_PAPER_SECRET_ENV,
        AlpacaBroker,
    )

    account_ref = f"alpaca-paper:conformance-suite-{ULID()}"
    return AlpacaBroker(
        account_ref=account_ref,
        base_url=ALPACA_PAPER_BASE_URL,
        key_id_env=ALPACA_PAPER_KEY_ID_ENV,
        secret_env=ALPACA_PAPER_SECRET_ENV,
    )


# One entry per BrokerPort adapter this suite conforms — the ONLY place a
# future adapter needs to be added (TD-18 "one factory entry" property).
CASE_BUILDERS: dict[str, Callable[[], BrokerPort]] = {
    "paper": _build_paper_case,
    "alpaca-paper": _build_alpaca_paper_case,
}


@pytest.fixture(params=list(CASE_BUILDERS), ids=list(CASE_BUILDERS))
def case(request: pytest.FixtureRequest) -> Case:
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
