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

Status: both `CASE_BUILDERS` entries are REAL adapters now and every case
below is GREEN — `PaperBroker`'s methods (fill-model dev pass, SPRINT P3
batch B) and `AlpacaBroker`'s methods (SPRINT P4-PAPER batch B) both pass
the full conformance suite, including `BrokerTokenRequired` on a missing/
invalid `VerdictToken` (see `tests/unit/broker/test_paper_fills.py` for the
token-required pin that originally prescribed this behavior).

SPRINT P4-PAPER batch A added the "alpaca-paper" case (`_build_alpaca_
paper_case`, TD-18's "one factory entry" property — the ONLY change this
suite itself needs for a new adapter). Dev-pass update (round-23
adjudication addendum, PRE-AUTHORIZED test edit: "conformance builders own
their environmental setup"): `AlpacaBroker`'s five methods are REAL and
every one of them raises `BrokerCredentialsMissing` without credentials
(no-creds is loud everywhere — never a fabricated zero-balance/empty-list
default), so the "alpaca-paper" builder seeds monkeypatched env keys AND
registers respx routes mirroring the CTO-captured shapes
(docs/research/alpaca-paper-shapes-2026-07-18.json, same fixtures
`tests/unit/broker/test_alpaca_broker.py` embeds) — the adapter then runs
its honest code path offline, exactly like a real venue session. Builders
therefore take `(monkeypatch, respx_mock)` (mirroring
`test_marketdata_port.py`'s own builder signature); the suite BODIES —
the actual conformance assertions — are untouched.

P4-PAPER review MEDIUM-1 (round-25) added a typed `VenueRejected`/
`VenueUnavailable` HTTP-error taxonomy to `AlpacaBroker` (`broker._port`);
this conformance suite's own `order_status()` case
(`test_order_status_returns_a_typed_order_status`) already covers the ONE
domain-mapped 4xx (404 -> `OrderStatus(status="rejected")`) via the
`order-does-not-exist` respx route above — the broader taxonomy (503/429/
malformed-200/other-4xx) is unit-tested directly in
`tests/unit/broker/test_alpaca_broker.py`, not duplicated here (this suite
stays adapter-agnostic, per its own "suite bodies untouched" convention).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
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


def _build_paper_case(
    monkeypatch: pytest.MonkeyPatch, respx_mock: Any
) -> BrokerPort:
    """SPRINT P3 batch B's first real `CASE_BUILDERS` entry: seeds a fresh
    `AccountCreated` on the (per-test, `TK_DATA_DIR`-isolated, autouse
    fixture) default ledger via the already-real `broker.create_paper_account`
    (TD-24, batch A), then hands back a `PaperBroker` bound to that
    `account_ref` — "a fresh instance per test", per `Case`'s own docstring.
    A fresh `account_ref` per call (ULID suffix) avoids
    `AccountAlreadyExists` across the multiple cases pytest builds from this
    one factory (one per parametrized test function). `monkeypatch`/
    `respx_mock` are unused here (a paper account is a pure ledger
    projection, no env/HTTP surface) — the shared builder signature exists
    for `_build_alpaca_paper_case`, which owns real environmental setup
    (round-23 adjudication addendum), mirroring `test_marketdata_port.py`'s
    own per-builder-fixture convention."""
    del monkeypatch, respx_mock  # signature parity only — see docstring
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


def _build_alpaca_paper_case(
    monkeypatch: pytest.MonkeyPatch, respx_mock: Any
) -> BrokerPort:
    """SPRINT P4-PAPER's `CASE_BUILDERS` entry for the dress-rehearsal
    adapter: a fresh `account_ref` per call (ULID suffix, same "fresh
    instance per test" discipline as `_build_paper_case`), bound to
    Alpaca's PAPER base URL + the paper env key names. No `AccountCreated`
    seed needed here (unlike `PaperBroker`'s ledger-projection `account()`,
    `AlpacaBroker` reads Alpaca's own endpoints — venue truth, round-23).

    Environmental setup (round-23 adjudication addendum: "conformance
    builders own their environmental setup" — the generic suite bodies must
    stay adapter-agnostic and untouched): every `AlpacaBroker` method
    raises `BrokerCredentialsMissing` without credentials (no-creds is loud
    everywhere), so this builder seeds fake env keys (monkeypatched, same
    literals as `test_alpaca_broker.py`'s autouse fixture) and registers
    respx routes for the four endpoints the suite may touch, shaped off the
    CTO-captured docs/research/alpaca-paper-shapes-2026-07-18.json
    lifecycle — so the adapter runs its honest offline code path exactly
    like a real venue session. The `submit` conformance case never reaches
    HTTP at all (the bogus token refuses first) and respx's pytest fixture
    does not require every registered route to be called, so unused routes
    per individual test are fine. Shapes NOT in the capture (the 2026-07-18
    probe covered the order lifecycle + activities only), flagged as
    Alpaca-DOCUMENTED rather than CTO-captured: (a) `/account` and
    `/positions` bodies (string-decimal money fields, Alpaca's own account/
    positions object convention — the same string discipline the captured
    lifecycle shows for `filled_qty`/`filled_avg_price`); (b) the
    unknown-order GET: Alpaca's documented order-not-found error body
    (`{"code": 40410000, "message": ...}`, HTTP 404) — `order_status` maps
    any unrecognized/absent status to `"rejected"` (fail closed,
    ALPACA_STATUS_MAP's own catch-all rule)."""
    import json
    from pathlib import Path

    from ulid import ULID

    from tradekit.broker._alpaca import (
        ALPACA_PAPER_BASE_URL,
        ALPACA_PAPER_KEY_ID_ENV,
        ALPACA_PAPER_SECRET_ENV,
        AlpacaBroker,
    )

    # Fixture provenance: read the CTO-captured shapes from their SOURCE OF
    # TRUTH file directly (tests/ is not an importable package, so
    # test_alpaca_broker.py's embedded copies can't be imported here — and
    # reading the capture itself is strictly more honest anyway).
    shapes_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "alpaca-paper-shapes-2026-07-18.json"
    )
    shapes = json.loads(shapes_path.read_text(encoding="utf-8"))
    order_get_fixture = shapes["order_get"]
    activities_fixture = shapes["activities"]

    monkeypatch.setenv(ALPACA_PAPER_KEY_ID_ENV, "AKFAKE00000000000000")
    monkeypatch.setenv(ALPACA_PAPER_SECRET_ENV, "fakeSecretValueXYZ")

    # /account and /positions shapes: the string-decimal field convention of
    # Alpaca's account/positions objects (equity/cash/buying_power and
    # qty/avg_entry_price arrive as STRINGS, same discipline the captured
    # order lifecycle shows for filled_qty/filled_avg_price).
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/account").mock(
        return_value=httpx.Response(
            200,
            json={"equity": "500.00", "cash": "500.00", "buying_power": "500.00"},
        )
    )
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/positions").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/account/activities").mock(
        return_value=httpx.Response(200, json=activities_fixture)
    )
    order_id = order_get_fixture["id"]
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/orders/{order_id}").mock(
        return_value=httpx.Response(200, json=order_get_fixture)
    )
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/orders/order-does-not-exist").mock(
        return_value=httpx.Response(
            404, json={"code": 40410000, "message": "order not found"}
        )
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
# Builders take (monkeypatch, respx_mock) — each owns its environmental
# setup (round-23 adjudication addendum), same convention as
# test_marketdata_port.py's CASE_BUILDERS.
CASE_BUILDERS: dict[str, Callable[[pytest.MonkeyPatch, Any], BrokerPort]] = {
    "paper": _build_paper_case,
    "alpaca-paper": _build_alpaca_paper_case,
}


@pytest.fixture(params=list(CASE_BUILDERS), ids=list(CASE_BUILDERS))
def case(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, respx_mock: Any
) -> Case:
    builder = CASE_BUILDERS[request.param]
    return Case(id=request.param, factory=lambda: builder(monkeypatch, respx_mock))


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
