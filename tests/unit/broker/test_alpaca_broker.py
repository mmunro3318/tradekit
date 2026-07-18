"""`AlpacaBroker` — the dress-rehearsal `BrokerPort` adapter (SPRINT
P4-PAPER batch A, addendum 2). `src/tradekit/broker/_alpaca.py`'s five
methods are `NotImplementedError` stubs THIS batch — every test below pins
the EXACT behavior the batch-B dev pass must produce (respx fixtures,
status mapping, fees-from-costs arithmetic) and is therefore expected RED
for that reason, same status `tests/unit/broker/test_paper_fills.py` had
against SPRINT P3 batch B's own `PaperBroker` stub.

Fixtures embed `docs/research/alpaca-paper-shapes-2026-07-18.json`
VERBATIM (CTO-captured, 2026-07-18 UTC: a real $10 BTC/USD Alpaca PAPER
order's full lifecycle — POST /v2/orders -> GET /v2/orders/{id} ->
GET /v2/account/activities?activity_types=FILL). The P1A lesson stands as
law (ASSUMPTIONS, `tests/unit/mae_data/test_alpaca.py`'s own module
docstring): a fixture that diverges from captured reality is a HIGH defect,
never "close enough".

House pattern: `_seed_allow_verdict` mirrors `test_paper_fills.py`'s own
helper of the same name — the allow-verdict must be EARNED (a real
`VerdictIssued(allow=true)` on the ledger), never shape-only (CTO
adjudication 2026-07-17, same class of call as P2 batch C's R-010).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from ulid import ULID

from tradekit import costs
from tradekit.broker._alpaca import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_LIVE_KEY_ID_ENV,
    ALPACA_LIVE_SECRET_ENV,
    ALPACA_PAPER_BASE_URL,
    ALPACA_PAPER_KEY_ID_ENV,
    ALPACA_PAPER_SECRET_ENV,
    ALPACA_STATUS_MAP,
    AlpacaBroker,
)
from tradekit.broker._port import BrokerTokenRequired
from tradekit.contracts import (
    AssetRef,
    Event,
    HaltSetPayload,
    OrderRequest,
    VerdictIssuedPayload,
    VerdictToken,
)
from tradekit.ledger import default_ledger

_ACCOUNT_REF = "alpaca-paper:main"
_ASSET = AssetRef(symbol="BTC/USD", venue="alpaca", asset_class="crypto", tick_size=Decimal("0.01"))
_VERDICT = VerdictToken(verdict_id="v-alpaca-1", policy_version_hash="0" * 64)
_T0 = datetime(2026, 1, 2, tzinfo=UTC)

# ---------------------------------------------------------------------------
# CTO-captured shapes (docs/research/alpaca-paper-shapes-2026-07-18.json,
# 2026-07-18 UTC probe) — embedded VERBATIM, field names/types unchanged.
# ---------------------------------------------------------------------------

ORDER_SUBMIT_FIXTURE = {
    "id": "b529b05d-1caf-4d7b-85cb-78ab9c11d51f",
    "client_order_id": "7d86374d-64da-4100-90e5-7cfe6136fa9e",
    "created_at": "2026-07-18T02:11:31.258635991Z",
    "updated_at": "2026-07-18T02:11:31.259121861Z",
    "submitted_at": "2026-07-18T02:11:31.258635991Z",
    "filled_at": None,
    "expired_at": None,
    "canceled_at": None,
    "failed_at": None,
    "asset_id": "276e2673-764b-4ab6-a611-caf665ca6340",
    "symbol": "BTC/USD",
    "asset_class": "crypto",
    "notional": "10",
    "qty": None,
    "filled_qty": "0",
    "filled_avg_price": None,
    "order_type": "market",
    "type": "market",
    "side": "buy",
    "time_in_force": "gtc",
    "limit_price": None,
    "stop_price": None,
    "status": "pending_new",
    "extended_hours": False,
}

ORDER_GET_FILLED_FIXTURE = {
    **ORDER_SUBMIT_FIXTURE,
    "updated_at": "2026-07-18T02:11:31.279137581Z",
    "filled_at": "2026-07-18T02:11:31.261291206Z",
    "filled_qty": "0.000153355",
    "filled_avg_price": "63930.5",
    "status": "filled",
}

ACTIVITIES_FIXTURE = [
    {
        "id": "20260717221131261::a8a1ebd1-871e-46ef-a731-9497868de24c",
        "activity_type": "FILL",
        "transaction_time": "2026-07-18T02:11:31.261291Z",
        "type": "fill",
        "price": "63930.5",
        "qty": "0.000153355",
        "side": "buy",
        "symbol": "BTC/USD",
        "leaves_qty": "0",
        "order_id": "b529b05d-1caf-4d7b-85cb-78ab9c11d51f",
        "cum_qty": "0.000153355",
        "order_status": "filled",
        "swap_rate": "1",
    }
]


def _seed_allow_verdict(
    account_ref: str = _ACCOUNT_REF,
    *,
    thesis_id: str | None = None,
    verdict_id: str = "v-alpaca-1",
    ts_utc: datetime = _T0,
) -> None:
    """Earn the allow — mirrors `test_paper_fills.py`'s helper of the same
    name (house pattern): a `VerdictToken` is only valid because a REAL
    `VerdictIssued(allow=true)` event sits on the ledger."""
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts_utc,
            type="VerdictIssued",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=VerdictIssuedPayload(
                verdict_id=verdict_id,
                kind="submit_order",
                account_ref=account_ref,
                thesis_id=thesis_id,
                allow=True,
                policy_version_hash=_VERDICT.policy_version_hash,
            ).model_dump(mode="json"),
        )
    )


def _order(*, thesis_id: str = "TH-alpaca-buy") -> OrderRequest:
    return OrderRequest(
        thesis_id=thesis_id,
        account_ref=_ACCOUNT_REF,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.000153355"),
    )


@pytest.fixture(autouse=True)
def _alpaca_paper_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALPACA_PAPER_KEY_ID_ENV, "AKFAKE00000000000000")
    monkeypatch.setenv(ALPACA_PAPER_SECRET_ENV, "fakeSecretValueXYZ")


def _paper_broker() -> AlpacaBroker:
    return AlpacaBroker(
        account_ref=_ACCOUNT_REF,
        base_url=ALPACA_PAPER_BASE_URL,
        key_id_env=ALPACA_PAPER_KEY_ID_ENV,
        secret_env=ALPACA_PAPER_SECRET_ENV,
    )


# ---------------------------------------------------------------------------
# Construction / routing-adjacent — REAL this batch (declarative), GREEN.
# ---------------------------------------------------------------------------


def test_constructor_wires_base_url_and_env_names() -> None:
    """The constructor itself is NOT a stub — `broker.get()`'s routing
    depends on it storing exactly what it was handed (addendum 2: "AlpacaBroker
    ... constructor takes base_url/key-env-names")."""
    adapter = AlpacaBroker(
        account_ref="alpaca-paper:main",
        base_url=ALPACA_PAPER_BASE_URL,
        key_id_env=ALPACA_PAPER_KEY_ID_ENV,
        secret_env=ALPACA_PAPER_SECRET_ENV,
    )
    assert adapter.account_ref == "alpaca-paper:main"
    assert adapter._base_url == ALPACA_PAPER_BASE_URL
    assert adapter._key_id_env == ALPACA_PAPER_KEY_ID_ENV
    assert adapter._secret_env == ALPACA_PAPER_SECRET_ENV


def test_live_base_url_and_env_names_are_the_pinned_constants() -> None:
    """Sanity pin on the two base URLs/env-name pairs `broker/__init__.py`'s
    routing wires — a typo here would silently point 'live:' at the paper
    sandbox or vice versa."""
    assert ALPACA_PAPER_BASE_URL == "https://paper-api.alpaca.markets/v2"
    assert ALPACA_LIVE_BASE_URL == "https://api.alpaca.markets/v2"
    assert ALPACA_LIVE_KEY_ID_ENV == "ALPACA_LIVE_KEY_ID"
    assert ALPACA_LIVE_SECRET_ENV == "ALPACA_LIVE_SECRET"


# ---------------------------------------------------------------------------
# Status mapping table (batch B pin) — the dict itself is real, GREEN;
# parametrized per the addendum's own pinned rows.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alpaca_status,expected",
    [
        ("new", "open"),
        ("pending_new", "open"),
        ("accepted", "open"),
        ("partially_filled", "open"),
        ("filled", "filled"),
        ("canceled", "canceled"),
        ("expired", "rejected"),
        ("rejected", "rejected"),
    ],
)
def test_alpaca_status_map_pinned_table(alpaca_status: str, expected: str) -> None:
    assert ALPACA_STATUS_MAP[alpaca_status] == expected


# ---------------------------------------------------------------------------
# Fees-from-costs arithmetic (batch B pin) — tradekit.costs itself is real,
# GREEN; this is the worked $10 BTC/USD example the module docstring cites.
# ---------------------------------------------------------------------------


def test_fees_from_costs_arithmetic_for_the_captured_10_dollar_order() -> None:
    """Alpaca paper's crypto FILL activity carries no fee field (see
    `ACTIVITIES_FIXTURE` above — no `fee`/`commission` key); `fees_usd` at
    `FillRecorded` time is modeled via `tradekit.costs.price_friction`.
    `_TABLE[("alpaca", "crypto")]` = (fee_rate=0.0025, half_spread=0.0010);
    at $10 notional, fee_usd = 0.0025 * 10 = 0.025."""
    friction = costs.price_friction("alpaca", "crypto", Decimal("10"), "buy")
    assert friction.fee_usd == Decimal("0.025")


# ---------------------------------------------------------------------------
# submit() — pinned real behavior (RED: NotImplementedError stub).
# ---------------------------------------------------------------------------


def test_submit_posts_orders_and_returns_typed_ack(respx_mock: object) -> None:
    """Pinned batch-B behavior: token verified via the shared verifier, then
    `POST {base_url}/orders` (captured `ORDER_SUBMIT_FIXTURE` shape) ->
    `OrderAck(status="open")` (ALPACA_STATUS_MAP["pending_new"]) plus typed
    `OrderSubmitted`/`OrderAck` ledger events. Currently RED: `submit` is an
    unconditional `NotImplementedError` stub, so this assertion never runs —
    the exception propagates uncaught (no respx route is exercised, so
    there is nothing for the autouse zero-network guard to complain about)."""
    _seed_allow_verdict(thesis_id="TH-alpaca-buy")
    respx_mock.post(f"{ALPACA_PAPER_BASE_URL}/orders").mock(
        return_value=httpx.Response(200, json=ORDER_SUBMIT_FIXTURE)
    )

    adapter = _paper_broker()
    ack = adapter.submit(_order(), _VERDICT)

    assert ack.status == "open"
    assert ack.order_id


def test_submit_refuses_without_a_valid_verdict_token() -> None:
    """§8.2/§15, shared with PaperBroker: `submit` must refuse a missing/
    unregistered `VerdictToken` with `BrokerTokenRequired`. Currently RED:
    the stub raises unconditional `NotImplementedError`, which `pytest.
    raises(BrokerTokenRequired)` does not match — the mismatch itself IS
    the red signal for this batch."""
    adapter = _paper_broker()
    bogus = VerdictToken(verdict_id="not-a-real-verdict", policy_version_hash="0" * 64)
    with pytest.raises(BrokerTokenRequired):
        adapter.submit(_order(), bogus)


def test_submit_refuses_before_any_http_call_when_env_keys_are_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinned batch-B behavior (mirrors `alpaca_data.AlpacaDataProvider.
    get_bars`'s pre-HTTP credential guard, ASSUMPTIONS 35): missing env keys
    must raise `ProviderRequestError` (provisional home — same class used by
    `mae._data.alpaca_data`, `_alpaca.py`'s module docstring) BEFORE any
    network call, verdict permitting. Currently RED: the stub raises
    unconditional `NotImplementedError` instead — no respx route registered
    at all, so there is nothing for the zero-network guard to complain
    about regardless of which exception ends up propagating."""
    from tradekit.mae._data.errors import ProviderRequestError

    monkeypatch.delenv(ALPACA_PAPER_KEY_ID_ENV, raising=False)
    _seed_allow_verdict(thesis_id="TH-alpaca-buy")

    adapter = _paper_broker()
    with pytest.raises(ProviderRequestError):
        adapter.submit(_order(), _VERDICT)


# ---------------------------------------------------------------------------
# order_status() — pinned real behavior (RED).
# ---------------------------------------------------------------------------


def test_order_status_maps_filled_and_records_a_fill_with_decimal_str_prices(
    respx_mock: object,
) -> None:
    """Pinned batch-B behavior: `GET {base}/orders/{id}` -> `filled` (string
    decimals `filled_qty`/`filled_avg_price`) -> our `OrderStatus(status=
    "filled")`, `Decimal(str(x))` per the JSON-number/string precision
    discipline every Alpaca provider in this codebase follows. Currently
    RED (NotImplementedError stub)."""
    order_id = ORDER_GET_FILLED_FIXTURE["id"]
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/orders/{order_id}").mock(
        return_value=httpx.Response(200, json=ORDER_GET_FILLED_FIXTURE)
    )

    adapter = _paper_broker()
    status = adapter.order_status(order_id)

    assert status.status == "filled"
    assert status.filled_qty == Decimal("0.000153355")


# ---------------------------------------------------------------------------
# fills() — pinned real behavior (RED).
# ---------------------------------------------------------------------------


def test_fills_returns_typed_list_ascending_from_activities(respx_mock: object) -> None:
    """Pinned batch-B behavior: `GET {base}/account/activities?
    activity_types=FILL` (captured `ACTIVITIES_FIXTURE`) -> typed
    `list[Fill]`, ASCENDING by `ts_utc` (§8.1's conformance pin). Currently
    RED."""
    respx_mock.get(f"{ALPACA_PAPER_BASE_URL}/account/activities").mock(
        return_value=httpx.Response(200, json=ACTIVITIES_FIXTURE)
    )

    adapter = _paper_broker()
    fills = adapter.fills(datetime(2026, 1, 1, tzinfo=UTC))

    timestamps = [f.ts_utc for f in fills]
    assert timestamps == sorted(timestamps)
    assert fills[0].price == Decimal("63930.5")
    assert fills[0].qty == Decimal("0.000153355")


def test_reconcile_over_alpaca_broker_fixtures_vs_seeded_ledger_both_directions() -> None:
    """Deliverable pin: `reconcile` must run UNCHANGED over `AlpacaBroker`
    (module docstring's "reconcile() compatibility" note) — this seeds a
    ledger `FillRecorded` matching `ACTIVITIES_FIXTURE`'s own
    `(order_id, ts_utc, qty)` triple and calls `broker.reconcile(account_
    ref)`, which resolves the adapter via `broker.get()` and calls `adapter.
    fills(...)` internally. Currently RED: `AlpacaBroker.fills` is a
    `NotImplementedError` stub, so `reconcile` itself blows up before it can
    compare either direction (forward: broker-fill-not-on-ledger: MED-3
    reverse: ledger-fill-not-on-broker) — both directions are therefore
    exercised by ONE red test this batch, per the deliverable's own
    phrasing ("both directions")."""
    from tradekit import broker as _broker
    from tradekit.contracts import FillRecordedPayload

    account_ref = "alpaca-paper:reconcile-test"
    activity = ACTIVITIES_FIXTURE[0]
    fill_payload = FillRecordedPayload(
        order_id=activity["order_id"],
        thesis_id="TH-reconcile",
        account_ref=account_ref,
        ts_utc=datetime.fromisoformat(activity["transaction_time"].replace("Z", "+00:00")),
        price=Decimal(activity["price"]),
        qty=Decimal(activity["qty"]),
        fees_usd=Decimal("0.025"),
        side="buy",  # type: ignore[arg-type]
        quote_snapshot={},
        symbol=activity["symbol"],
    )
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=fill_payload.ts_utc,
            type="FillRecorded",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=fill_payload.model_dump(mode="json"),
        )
    )

    with pytest.raises(NotImplementedError):
        _broker.reconcile(account_ref)


# ---------------------------------------------------------------------------
# Halt seam (addendum 2, NEW shared-verifier behavior) — parametrized across
# BOTH adapters. PaperBroker's case is a genuinely NEW red (the extraction
# adds submit-time halt refusal it never had before); AlpacaBroker's case
# stays red for the pre-existing stub reason.
# ---------------------------------------------------------------------------


def _seed_halt(ts_utc: datetime) -> None:
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts_utc,
            type="HaltSet",
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=HaltSetPayload(
                reason="test-halt", scope="all", set_by="system:test-harness"
            ).model_dump(mode="json"),
        )
    )


@pytest.mark.parametrize("adapter_kind", ["paper", "alpaca-paper"])
def test_submit_refuses_with_reason_halted_when_an_unresolved_halt_set_exists(
    adapter_kind: str,
) -> None:
    """Addendum 2's submit-time halt seam: an unresolved `HaltSet` must
    refuse `submit` with `BrokerTokenRequired` (message mentions "halted"),
    on EVERY adapter, even with an otherwise-valid earned allow-verdict.

    - "paper": GREEN is the target, but this is the DELIBERATE new-red case
      against PaperBroker's PRIOR behavior (before this batch's extraction,
      `PaperBroker.submit` never checked halt state at all) — now real via
      `_tokens.verify_token`, so this case is expected GREEN this batch
      (the extraction ships real code, not a stub).
    - "alpaca-paper": RED (NotImplementedError stub never reaches the
      shared verifier this batch)."""
    account_ref = f"{adapter_kind}:halt-seam-test"
    thesis_id = "TH-halt-seam"
    _seed_allow_verdict(account_ref=account_ref, thesis_id=thesis_id, verdict_id="v-halt-1")
    _seed_halt(_T0 + timedelta(hours=1))

    if adapter_kind == "paper":
        from tradekit.broker._paper import PaperBroker

        adapter = PaperBroker(account_ref=account_ref)
    else:
        adapter = AlpacaBroker(
            account_ref=account_ref,
            base_url=ALPACA_PAPER_BASE_URL,
            key_id_env=ALPACA_PAPER_KEY_ID_ENV,
            secret_env=ALPACA_PAPER_SECRET_ENV,
        )

    order = OrderRequest(
        thesis_id=thesis_id,
        account_ref=account_ref,
        asset=_ASSET,
        side="buy",
        order_type="market",
        qty=Decimal("0.001"),
    )
    token = VerdictToken(verdict_id="v-halt-1", policy_version_hash="0" * 64)

    with pytest.raises(BrokerTokenRequired, match="halted"):
        adapter.submit(order, token)
