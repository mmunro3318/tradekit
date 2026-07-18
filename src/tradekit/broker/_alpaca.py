"""`AlpacaBroker` -- the dress-rehearsal `BrokerPort` adapter against
Alpaca's TRADING API (SPRINT P4-PAPER batch A, addendum 2). Implements
`BrokerPort` structurally (no inheritance needed -- the Protocol is
`runtime_checkable` and duck-typed, same as `PaperBroker`/`ManualBroker`).

Base URLs (constructor-injected, never hardcoded per-instance -- routing
picks the pair): paper `https://paper-api.alpaca.markets/v2`, live
`https://api.alpaca.markets/v2`. `broker.get()` (this batch) resolves
`"alpaca-paper:*"` -> `AlpacaBroker` bound to the paper base + the paper env
key names (`ALPACA_API_KEY_ID`/`ALPACA_API_SECRET`, the SAME names
`mae._data.alpaca_data.AlpacaDataProvider` already uses, ASSUMPTIONS 35);
`"live:alpaca"` -> the fail-closed path (`LiveTradingDisabled` unless BOTH
`PolicyDials.live_trading_enabled` is true AND `ALPACA_LIVE_KEY_ID`/
`ALPACA_LIVE_SECRET` are present) -- see `broker/__init__.py`'s `get()`.

STATUS (SPRINT P4-PAPER dev pass, GREEN): every one of the five `BrokerPort`
methods below is real now -- the "declarative routing is real, adapter
methods stay red" split `PaperBroker` itself went through across SPRINT P3
batches A->B (`_paper.py`'s own `test_broker_stubs.py` history) is complete
for this adapter too. `tests/unit/broker/test_alpaca_broker.py` and the
"alpaca-paper" conformance-suite case (`tests/contract/test_broker_port.py`)
pin the REAL behavior implemented below; every method fails loudly with
`BrokerCredentialsMissing` on missing credentials, never a network attempt
and never a fabricated default (round-23 adjudication addendum -- see the
"Pre-HTTP credential guard" section below).

Fixtures mirror REALITY (docs/research/alpaca-paper-shapes-2026-07-18.json,
CTO-captured 2026-07-18: a real $10 BTC/USD paper order's full lifecycle) --
embedded verbatim (field names/types) in the test file's respx fixtures; the
P1A lesson stands as law here too (SPRINT-P1A, ASSUMPTIONS): a fixture that
diverges from captured reality is a HIGH defect, never a "close enough"
shape.

Token verification (batch B pin): `submit()` MUST run every `VerdictToken`
through the SAME shared verifier `PaperBroker` uses --
`broker._tokens.verify_token(self._ledger, verdict, order.thesis_id,
caller_repr=...)` -- never a second, adapter-local reimplementation (see
`_tokens.py`'s own module docstring for why that would be dishonest). This
closes the submit-time halt seam identically on this adapter: an unresolved
`HaltSet` refuses `submit` with `BrokerTokenRequired` reason `"halted"`,
BEFORE any HTTP call.

Pre-HTTP credential guard (mirrors `alpaca_data.AlpacaDataProvider.
get_bars`'s own "fail before the request" pattern, ASSUMPTIONS 35), on
EVERY method (round-23 adjudication addendum: no-creds is LOUD everywhere):
each of the five methods checks `os.environ.get(self._key_id_env)`/
`self._secret_env` and raises the round-23-ratified, broker-native typed
`BrokerCredentialsMissing` (`broker._port`, never `mae._data.errors`
imported from `_alpaca.py` itself -- see that class's own docstring for the
one documented exception, `_port.py`'s subclassing) naming the missing var,
BEFORE constructing any request. A read verb "degrading" to zero balances /
an empty fills list / a fabricated "rejected" status when we simply could
not ask the venue is fabricated data -- the exact class ASSUMPTIONS 71/
`NoQuoteAvailable` exist to kill (a $0 account reads as a real broke
account; an empty fills list reads as "reconciled clean") -- so there is no
graceful-degrade path anywhere on this adapter. In `submit()` the guard is
checked AFTER token verification (a caller with no allow-verdict is refused
on that grounds first, never leaking "which env var is missing" to an
unauthorized caller) but BEFORE the HTTP client touches the network. The
`tests/contract/test_broker_port.py` conformance cases supply this
environmental setup themselves (monkeypatched env keys + respx routes from
the captured fixtures -- conformance builders own their environmental
setup, round-23 adjudication addendum).

Status mapping (batch B pin -- READ THIS TABLE, it is the exact vocabulary
the dev pass's `order_status()` must produce; `ALPACA_STATUS_MAP` below is
the executable form):

    Alpaca `status`                                  -> our `OrderStatus.status`
    ------------------------------------------------------------------------
    new                                               -> "open"
    pending_new                                       -> "open"
    accepted                                          -> "open"
    accepted_for_bidding                              -> "open"
    pending_cancel                                    -> "open"
    pending_replace                                   -> "open"
    calculated                                        -> "open"
    partially_filled                                  -> "open"  (MVP: no
        synthetic "partially_filled" status -- MVP records fills from
        `GET /v2/account/activities?activity_types=FILL` as they appear,
        `cum_qty` tracked on the Fill events themselves; the ORDER's own
        `order_status()` stays "open" until Alpaca's own `status` flips to
        `filled`, never sooner)
    filled                                            -> "filled"
    canceled                                          -> "canceled"
    expired                                           -> "rejected"
    rejected                                          -> "rejected"
    stopped                                           -> "rejected"
    suspended                                         -> "rejected"
    done_for_day                                      -> "rejected"
    replaced                                           -> "rejected"  (MVP:
        order replacement is out of scope; a replaced order reads as
        terminal-non-fill rather than silently vanishing)
    (any other/unrecognized Alpaca status)             -> "rejected"  (fail
        closed -- an unrecognized terminal-ish status must never be read as
        "open" and silently re-polled forever, nor fabricated as "filled")

The table above governs the STATUS FIELD of a successfully-parsed 2xx
response only. HTTP-transport-level errors (P4-PAPER review MEDIUM-1,
round-25 pin) are a SEPARATE, prior classification -- `broker._port`'s
`VenueRejected`/`VenueUnavailable` taxonomy (mirrors the P1A `ProviderError`
semantics, `mae._data.errors`, but broker-native): every one of the five
methods classifies the raw HTTP response BEFORE parsing any field out of it
(`_parse_json`) --

    HTTP 429 or >= 500                    -> VenueUnavailable (raise;
        never fabricate a status/balance/list -- a transient 503 on
        order_status() must never misreport a possibly-live order as
        terminal "rejected")
    HTTP 404 on order_status() ONLY       -> OrderStatus(status="rejected")
        (the ONE pinned case a 4xx maps to a domain value instead of
        raising -- a venue-confirmed "this order does not exist" IS a real,
        terminal answer; checked BEFORE _parse_json, never generalized to
        any other 4xx or any other method)
    any other 4xx (400-499, incl. 404 on
      every OTHER method, and 422 on any
      method)                              -> VenueRejected (raise; a real
        venue answer -- bad params, unknown resource, auth failure -- just
        not one that maps to a domain value anywhere but order_status's 404)
    2xx with a body that fails to decode
      as JSON, or of the wrong top-level
      shape (e.g. an error dict where a
      list was expected)                   -> VenueUnavailable (a malformed
        200 is exactly as untrustworthy as a 5xx)
    a field access on an otherwise-valid
      2xx JSON body raises KeyError/
      TypeError/ValueError/InvalidOperation -> VenueUnavailable (never a
        bare exception leaking the parsing implementation detail to the
        caller)

`submit()`'s event-ordering discipline (round-25 pin, "validate-before-
append"): `_parse_json` and all field extraction happen BEFORE
`_append_order_submitted`/`_append_order_ack` are ever called -- a
`VenueRejected`/`VenueUnavailable` raised mid-parse means ZERO ledger events
exist for that call. This was already the ordering in the code (events were
always appended after `response.json()`, never before the POST); the fix
adds the missing status-code/malformed-body classification in front of that
existing ordering, it does not need to reorder the appends themselves.

Fees-from-costs convention (batch B pin, the arithmetic this batch's TDD
author DERIVED and pins for the dev pass): Alpaca's paper crypto fill
activities carry NO per-fill fee field (`docs/research/
alpaca-paper-shapes-2026-07-18.json`'s `activities[0]` has no `fee`/
`commission` key at all -- confirmed against the CTO's real capture, not
assumed). `FillRecordedPayload.fees_usd` at fill-recording time therefore
comes from `tradekit.costs.price_friction("alpaca", "crypto", notional_usd,
side).fee_usd` -- the SAME shared friction table `PaperBroker` prices off
(TD-8, one friction source). Worked example off the captured $10 BTC/USD
order: `tradekit.costs._TABLE[("alpaca", "crypto")]` = (fee_rate=
Decimal("0.0025"), half_spread_rate=Decimal("0.0010")) (25bps taker); at
`notional_usd = Decimal("10")`, `fee_usd = Decimal("0.0025") *
Decimal("10") = Decimal("0.025")`. This is PROVISIONAL (ASSUMPTIONS-26
spirit: Alpaca paper reports no per-fill fee, so this is our own modeled
estimate standing in for it, not a value Alpaca itself asserts) --
documented in ASSUMPTIONS round-23, not improvised silently.

reconcile() compatibility (batch B pin): `reconcile` (already real,
`_pipeline.py`) calls `adapter.fills(since)` -- `AlpacaBroker.fills` must
return the SAME typed `list[Fill]`, ASCENDING by `ts_utc`, that `PaperBroker.
fills` does, so `reconcile` runs UNCHANGED over either adapter (no
alpaca-specific branch in `_pipeline.py`).
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx
from ulid import ULID

from tradekit import costs
from tradekit.broker import _tokens
from tradekit.broker._port import BrokerCredentialsMissing, VenueRejected, VenueUnavailable
from tradekit.contracts import (
    AccountState,
    Event,
    EventFilter,
    Fill,
    FillRecordedPayload,
    OrderAck,
    OrderAckPayload,
    OrderRequest,
    OrderStatus,
    OrderSubmittedPayload,
    Position,
    VerdictToken,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime

# Trading-API base URLs (addendum 2, pinned verbatim).
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets/v2"
ALPACA_LIVE_BASE_URL = "https://api.alpaca.markets/v2"

# Env var names -- never hardcode a literal key/secret here (same discipline
# as mae._data.alpaca_data.ALPACA_API_KEY_ID_ENV/ALPACA_API_SECRET_ENV,
# ASSUMPTIONS 35). Paper reuses the data provider's OWN env names (one
# Alpaca paper credential pair for both market-data and trading this
# sprint); live is a SEPARATE, more sensitive pair the fail-closed routing
# gate in `broker/__init__.py` checks before ever constructing this adapter
# for `"live:"`.
ALPACA_PAPER_KEY_ID_ENV = "ALPACA_API_KEY_ID"
ALPACA_PAPER_SECRET_ENV = "ALPACA_API_SECRET"
ALPACA_LIVE_KEY_ID_ENV = "ALPACA_LIVE_KEY_ID"
ALPACA_LIVE_SECRET_ENV = "ALPACA_LIVE_SECRET"

# Status mapping table (batch B pin) -- see module docstring for the WHY
# behind each row. `Literal` values match `contracts.OrderStatus.status`
# exactly so a typo here is a mypy error, not a silent runtime drift.
_OrderStatusLiteral = Literal["open", "partially_filled", "filled", "canceled", "rejected"]

ALPACA_STATUS_MAP: dict[str, _OrderStatusLiteral] = {
    "new": "open",
    "pending_new": "open",
    "accepted": "open",
    "accepted_for_bidding": "open",
    "pending_cancel": "open",
    "pending_replace": "open",
    "calculated": "open",
    "partially_filled": "open",
    "filled": "filled",
    "canceled": "canceled",
    "expired": "rejected",
    "rejected": "rejected",
    "stopped": "rejected",
    "suspended": "rejected",
    "done_for_day": "rejected",
    "replaced": "rejected",
}

# 'agent:<model>' | 'mike' | 'system:<job>' -- every event this adapter
# appends directly (OrderSubmitted/OrderAck/FillRecorded) is a machine
# transcription of a real venue response, same convention as
# `_paper.py`'s own `_ACTOR = "system:paper-broker"`.
_ACTOR = "system:alpaca-broker"

_REQUEST_TIMEOUT_S = 10.0


def _parse_alpaca_ts(t: str) -> datetime:
    """Alpaca timestamps are ISO-8601 with a trailing "Z" (and, per the
    captured fixtures, up to nanosecond fractional precision) -- normalize
    to aware-UTC the SAME way `mae._data.alpaca_data._parse_alpaca_ts`
    does (`datetime.fromisoformat` silently truncates sub-microsecond
    digits, never raises on them)."""
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t)


class AlpacaBroker:
    """One Alpaca trading account (paper or live, per `base_url`/
    `key_id_env`/`secret_env` at construction) -- see module docstring;
    every method raises `BrokerCredentialsMissing` on missing credentials
    (round-23 adjudication addendum: loud everywhere, no fabricated
    defaults)."""

    def __init__(
        self,
        account_ref: str,
        *,
        base_url: str,
        key_id_env: str,
        secret_env: str,
        ledger: Ledger | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.account_ref = account_ref
        self._base_url = base_url
        self._key_id_env = key_id_env
        self._secret_env = secret_env
        self._ledger = ledger if ledger is not None else default_ledger()
        self._client = client

    def account(self) -> AccountState:
        """`GET {base_url}/account` -> `AccountState` (equity, settled cash,
        buying power from Alpaca's own account object, `Decimal(str(x))`
        per field -- same JSON-number precision discipline as
        `alpaca_data.py`, ASSUMPTIONS 32). Missing credentials -> raises
        `BrokerCredentialsMissing`, no network attempt (round-23
        adjudication addendum: no-creds is loud on EVERY method -- a $0
        account returned when we simply could not ask is fabricated data,
        the exact class ASSUMPTIONS 71 exists to kill)."""
        headers = self._headers(*self._require_credentials("account"))
        response = self._get(f"{self._base_url}/account", headers=headers)
        data = self._parse_json(response, method="account")
        try:
            if not isinstance(data, dict):
                raise TypeError(f"expected a JSON object, got {type(data).__name__}")
            return AccountState(
                account_ref=self.account_ref,
                equity_usd=Decimal(str(data["equity"])),
                settled_cash_usd=Decimal(str(data["cash"])),
                buying_power_usd=Decimal(str(data["buying_power"])),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).account(...): malformed venue response "
                f"(missing/invalid account fields): {exc}"
            ) from exc

    def positions(self) -> list[Position]:
        """`GET {base_url}/positions` -> `list[Position]` (CTO ratification,
        round-23: venue truth, not ledger-derived -- "ledger-derived
        positions would make reconcile circular; venue-truth is the dress
        rehearsal's purpose"). Missing credentials -> raises
        `BrokerCredentialsMissing`, no network attempt (see `account()`'s
        docstring -- round-23 adjudication addendum, loud everywhere)."""
        headers = self._headers(*self._require_credentials("positions"))
        response = self._get(f"{self._base_url}/positions", headers=headers)
        rows = self._parse_json(response, method="positions")
        try:
            if not isinstance(rows, list):
                raise TypeError(f"expected a JSON array, got {type(rows).__name__}")
            return [
                Position(
                    account_ref=self.account_ref,
                    symbol=row["symbol"],
                    qty=Decimal(str(row["qty"])),
                    avg_price=Decimal(str(row["avg_entry_price"])),
                    market_value_usd=(
                        Decimal(str(row["market_value"]))
                        if row.get("market_value") is not None
                        else None
                    ),
                )
                for row in rows
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).positions(...): malformed venue response "
                f"(missing/invalid position fields): {exc}"
            ) from exc

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Verify `verdict` via the SHARED `broker._tokens.verify_token`
        (module docstring -- closes the submit-time halt seam identically to
        `PaperBroker`), THEN the pre-HTTP credential guard (raises
        `BrokerCredentialsMissing`, no network on failure), THEN `POST
        {base_url}/orders` with the captured shape's request fields
        (`symbol`, `notional` or `qty`, `side`, `type`, `time_in_force`) ->
        append `OrderSubmitted`/`OrderAck` from the response's `id`/`status`
        (`"pending_new"` at submit time per the captured `order_submit`
        fixture -> our `"open"`, ALPACA_STATUS_MAP). `OrderAck.status`
        echoes the mapped VENUE status (widened `contracts.OrderAck.status`
        Literal, additive) rather than a fixed `"accepted"` -- the POST
        response already carries a real, venue-observed lifecycle status
        that would otherwise be silently discarded."""
        _tokens.verify_token(
            self._ledger,
            verdict,
            order.thesis_id,
            caller_repr=f"AlpacaBroker({self.account_ref!r})",
        )
        headers = self._headers(*self._require_credentials("submit"))

        body: dict[str, Any] = {
            "symbol": order.asset.symbol,
            "side": order.side,
            "type": "limit" if order.order_type in ("limit", "stop_limit") else "market",
            "time_in_force": "gtc",
        }
        if order.order_type in ("limit", "stop", "stop_limit"):
            body["qty"] = str(order.qty)
            if order.limit_price is not None:
                body["limit_price"] = str(order.limit_price)
        else:
            # Market: notional-based when a reference price is known (the
            # qty-deriving entry price `_pipeline._build_order_request`
            # always carries on `OrderRequest.limit_price` regardless of
            # order_type, DESIGN §8.2 step 1) -- matches the captured
            # `ORDER_SUBMIT_FIXTURE` shape (`notional="10"`, `qty=None`).
            # qty-based fallback for a bare `OrderRequest` with no
            # limit_price at all (e.g. `test_alpaca_broker.py`'s own
            # `_order()` helper) -- never fabricate a price to convert one.
            if order.limit_price is not None:
                body["notional"] = str(order.qty * order.limit_price)
            else:
                body["qty"] = str(order.qty)

        response = self._post(f"{self._base_url}/orders", headers=headers, json=body)
        data = self._parse_json(response, method="submit")
        try:
            if not isinstance(data, dict):
                raise TypeError(f"expected a JSON object, got {type(data).__name__}")
            venue_order_id = str(data["id"])
            alpaca_status = str(data.get("status", ""))
            mapped_status = ALPACA_STATUS_MAP.get(alpaca_status, "rejected")
            ts_raw = data.get("submitted_at") or data.get("created_at")
            ts = _parse_alpaca_ts(ts_raw) if ts_raw else _mae_runtime.clock()
        except (KeyError, TypeError, ValueError) as exc:
            # Validate-before-append discipline (round-25 pin): nothing may
            # be appended to the ledger until the venue's response has been
            # fully parsed and validated -- a malformed/error body must
            # raise here, before EITHER OrderSubmitted or OrderAck exists,
            # never leave a ledger trace claiming an order that was never
            # actually confirmed.
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).submit(...): malformed venue response "
                f"(missing/invalid order fields): {exc}"
            ) from exc

        self._append_order_submitted(order, venue_order_id, ts)
        self._append_order_ack(venue_order_id, order.thesis_id, mapped_status, ts)
        return OrderAck(
            order_id=venue_order_id,
            status=mapped_status,  # type: ignore[arg-type]
            ts_utc=ts,
            venue_order_id=venue_order_id,
        )

    def order_status(self, order_id: str) -> OrderStatus:
        """`GET {base_url}/orders/{order_id}` -> map Alpaca's `status`
        through `ALPACA_STATUS_MAP` (module docstring's pinned table);
        `filled_qty`/`filled_avg_price` arrive as STRINGS (captured
        `order_get` fixture) -- `Decimal(str(x))`, never bare `Decimal(x)`.
        A `status == "filled"` transition (first time observed -- no
        already-recorded `FillRecorded` for this `order_id`/`account_ref`)
        also appends a `FillRecorded`, built directly from THIS SAME
        response's own `filled_qty`/`filled_avg_price`/`symbol`/`side`
        fields (never a second HTTP round-trip to `/account/activities` --
        the order-GET response already carries everything a fill needs, and
        `tests/unit/broker/test_alpaca_broker.py`'s own `order_status`
        fill-recording test registers no activities-endpoint respx route,
        pinning this "one call, not two" design). fees_usd via
        `tradekit.costs.price_friction("alpaca", asset_class, notional_usd,
        side).fee_usd` (module docstring's worked $10 example: 0.0025 * 10 =
        0.025), since Alpaca's own order/activity objects carry no fee
        field. Missing credentials -> raises `BrokerCredentialsMissing`, no
        network attempt (see `account()`'s docstring -- a fabricated
        `"rejected"` when we could not ask would misreport a possibly-live
        order as terminal; round-23 adjudication addendum)."""
        headers = self._headers(*self._require_credentials("order_status"))
        response = self._get(f"{self._base_url}/orders/{order_id}", headers=headers)

        if response.status_code == 404:
            # The ONE pinned case where a 4xx maps to a domain value rather
            # than raising (round-25 pin, module docstring's status-mapping
            # table): a venue-confirmed "this order does not exist" IS a
            # real, terminal answer -- reads as "rejected", never
            # generalized to any other 4xx or any other method.
            return OrderStatus(
                order_id=order_id,
                status="rejected",
                filled_qty=Decimal("0"),
                remaining_qty=None,
            )

        data = self._parse_json(response, method="order_status")
        try:
            if not isinstance(data, dict):
                raise TypeError(f"expected a JSON object, got {type(data).__name__}")

            alpaca_status = str(data.get("status", ""))
            mapped_status = ALPACA_STATUS_MAP.get(alpaca_status, "rejected")
            filled_qty_raw = data.get("filled_qty")
            filled_qty = (
                Decimal(str(filled_qty_raw)) if filled_qty_raw is not None else Decimal("0")
            )

            remaining_qty: Decimal | None = None
            qty_raw = data.get("qty")
            if qty_raw is not None:
                remaining_qty = Decimal(str(qty_raw)) - filled_qty
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).order_status(...): malformed venue "
                f"response (missing/invalid order fields): {exc}"
            ) from exc

        if mapped_status == "filled":
            self._record_fill_from_order(order_id=order_id, data=data)
            remaining_qty = Decimal("0")

        return OrderStatus(
            order_id=order_id,
            status=mapped_status,
            filled_qty=filled_qty,
            remaining_qty=remaining_qty,
        )

    def fills(self, since: datetime) -> list[Fill]:
        """`GET {base_url}/account/activities?activity_types=FILL` (captured
        `activities` fixture: `price`/`qty`/`cum_qty` as STRINGS,
        `transaction_time` ISO-Z, `order_id` linkage, no fee field) -> typed
        `list[Fill]` ASCENDING by `ts_utc` (§8.1's conformance pin, SAME as
        `PaperBroker.fills`/`ManualBroker.fills`) so `reconcile` runs
        unchanged over this adapter (module docstring). Missing credentials
        -> raises `BrokerCredentialsMissing`, no network attempt (see
        `account()`'s docstring -- an empty fills list when we could not ask
        reads as "reconciled clean"; round-23 adjudication addendum)."""
        headers = self._headers(*self._require_credentials("fills"))
        response = self._get(
            f"{self._base_url}/account/activities",
            headers=headers,
            params={"activity_types": "FILL"},
        )
        rows = self._parse_json(response, method="fills")
        try:
            if not isinstance(rows, list):
                raise TypeError(f"expected a JSON array, got {type(rows).__name__}")

            out = []
            for row in rows:
                ts = _parse_alpaca_ts(row["transaction_time"])
                if ts < since:
                    continue
                order_id = str(row.get("order_id", ""))
                out.append(
                    Fill(
                        order_id=order_id,
                        thesis_id=self._thesis_id_for_order(order_id),
                        ts_utc=ts,
                        price=Decimal(str(row["price"])),
                        qty=Decimal(str(row["qty"])),
                        fees_usd=self._fees_for(
                            symbol=str(row.get("symbol", "")),
                            side=str(row.get("side", "buy")),
                            price=Decimal(str(row["price"])),
                            qty=Decimal(str(row["qty"])),
                        ),
                        quote_snapshot={},
                    )
                )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).fills(...): malformed venue response "
                f"(missing/invalid activity fields): {exc}"
            ) from exc
        out.sort(key=lambda f: f.ts_utc)
        return out

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    def _require_credentials(self, method: str) -> tuple[str, str]:
        """EVERY method's pre-HTTP credential guard (round-23 adjudication
        addendum: no-creds is LOUD everywhere, never a fabricated default --
        a $0 `account()` reads as a real broke account, an empty `fills()`
        reads as "reconciled clean", exactly the fabrication class
        ASSUMPTIONS 71/`NoQuoteAvailable` exist to kill) -- raises
        `BrokerCredentialsMissing` naming the missing var, BEFORE any HTTP
        call. In `submit()` this is checked AFTER token verification
        (module docstring's ordering rationale)."""
        key_id = os.environ.get(self._key_id_env)
        secret = os.environ.get(self._secret_env)
        if key_id and secret:
            return key_id, secret
        missing = self._key_id_env if not key_id else self._secret_env
        raise BrokerCredentialsMissing(
            f"AlpacaBroker({self.account_ref!r}).{method}(...): missing required env var "
            f"{missing!r} -- refusing before any HTTP call (ASSUMPTIONS 35 pattern, round-23 "
            "adjudication: no-creds is loud on every method, never a fabricated default)"
        )

    @staticmethod
    def _headers(key_id: str, secret: str) -> dict[str, str]:
        return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}

    def _get(
        self, url: str, *, headers: dict[str, str], params: dict[str, str] | None = None
    ) -> httpx.Response:
        try:
            if self._client is not None:
                return self._client.get(
                    url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT_S
                )
            return httpx.get(url, headers=headers, params=params, timeout=_REQUEST_TIMEOUT_S)
        except httpx.HTTPError as exc:
            # Timeouts/connection failures/etc -- the venue never answered at
            # all (round-25 pin: never distinguishable from a 5xx in terms of
            # what we're allowed to infer -- nothing).
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}): GET {url} failed: {exc}"
            ) from exc

    def _post(self, url: str, *, headers: dict[str, str], json: dict[str, Any]) -> httpx.Response:
        try:
            if self._client is not None:
                return self._client.post(
                    url, headers=headers, json=json, timeout=_REQUEST_TIMEOUT_S
                )
            return httpx.post(url, headers=headers, json=json, timeout=_REQUEST_TIMEOUT_S)
        except httpx.HTTPError as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}): POST {url} failed: {exc}"
            ) from exc

    def _parse_json(self, response: httpx.Response, *, method: str) -> Any:
        """Venue-error taxonomy (P4-PAPER review MEDIUM-1, round-25 pin):
        classify `response` BEFORE any field access ever happens, so no
        caller can accidentally parse a non-2xx/malformed body as if it were
        a real answer.

        - 429 or 5xx: `VenueUnavailable` -- the venue did not really answer
          (rate-limited/overloaded/erroring); never fabricate a status/
          balance/list from this.
        - Any other 4xx: `VenueRejected` -- a REAL venue answer (bad params,
          unknown resource, auth failure); `order_status` is the ONE caller
          that special-cases 404 into a domain value BEFORE ever reaching
          this method (module docstring) -- every other 4xx everywhere else
          raises here.
        - 2xx with a body that fails to decode as JSON: `VenueUnavailable`
          (a malformed 200 is exactly as untrustworthy as a 5xx -- round-25
          pin, "malformed 200 -> RAISE, never fabricate a status")."""
        status = response.status_code
        if status == 429 or status >= 500:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).{method}(...): venue unavailable "
                f"(HTTP {status}): {response.text}"
            )
        if 400 <= status < 500:
            raise VenueRejected(
                f"AlpacaBroker({self.account_ref!r}).{method}(...): venue rejected the "
                f"request (HTTP {status}): {response.text}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise VenueUnavailable(
                f"AlpacaBroker({self.account_ref!r}).{method}(...): malformed response body "
                f"(HTTP {status}, not valid JSON): {exc}"
            ) from exc

    def _append(self, event_type: str, payload: dict[str, Any], ts: datetime) -> str:
        event = Event(
            event_id=str(ULID()),
            ts_utc=ts,
            type=event_type,  # type: ignore[arg-type]
            actor=_ACTOR,
            run_id=None,
            schema_ver=1,
            payload=payload,
        )
        return self._ledger.append(event)

    def _append_order_submitted(self, order: OrderRequest, order_id: str, ts: datetime) -> None:
        payload = OrderSubmittedPayload(
            order_id=order_id,
            thesis_id=order.thesis_id,
            account_ref=order.account_ref,
            asset=order.asset.model_dump(mode="json"),
            side=order.side,
            order_type=order.order_type,
            qty=order.qty,
            limit_price=order.limit_price,
            ts_utc=ts,
        )
        self._append("OrderSubmitted", payload.model_dump(mode="json"), ts)

    def _append_order_ack(self, order_id: str, thesis_id: str, status: str, ts: datetime) -> None:
        payload = OrderAckPayload(
            order_id=order_id,
            thesis_id=thesis_id,
            status=status,  # type: ignore[arg-type]
            ts_utc=ts,
            venue_order_id=order_id,
        )
        self._append("OrderAck", payload.model_dump(mode="json"), ts)

    def _local_order_submitted(self, order_id: str) -> Event | None:
        for event in self._ledger.query(EventFilter(types=["OrderSubmitted"])):
            payload = event.payload
            if payload.get("order_id") == order_id and payload.get("account_ref") == (
                self.account_ref
            ):
                return event
        return None

    def _existing_fill(self, order_id: str) -> Event | None:
        for event in self._ledger.query(EventFilter(types=["FillRecorded"])):
            payload = event.payload
            if payload.get("order_id") == order_id and payload.get("account_ref") == (
                self.account_ref
            ):
                return event
        return None

    def _thesis_id_for_order(self, order_id: str) -> str:
        submitted = self._local_order_submitted(order_id)
        if submitted is not None:
            return str(submitted.payload.get("thesis_id", ""))
        return ""

    @staticmethod
    def _asset_class_for_symbol(symbol: str) -> str:
        """Alpaca crypto symbols carry a `"/"` (e.g. `"BTC/USD"`); equities
        don't (e.g. `"AAPL"`) -- a cheap, reliable discriminator when the
        response body itself doesn't carry `asset_class` (the activities
        endpoint doesn't)."""
        return "crypto" if "/" in symbol else "equity"

    def _fees_for(self, *, symbol: str, side: str, price: Decimal, qty: Decimal) -> Decimal:
        """Fees-from-costs convention (module docstring's worked $10
        example): Alpaca's own fill objects carry no fee field, so
        `fees_usd` is a MODELED estimate off `tradekit.costs.
        price_friction`, never fabricated from nothing."""
        asset_class = self._asset_class_for_symbol(symbol)
        notional_usd = price * qty
        friction = costs.price_friction("alpaca", asset_class, notional_usd, side)  # type: ignore[arg-type]
        return friction.fee_usd

    def _record_fill_from_order(self, *, order_id: str, data: dict[str, Any]) -> None:
        """First-observed-fill recorder for `order_status()` -- see that
        method's docstring for why this reads the order-GET response
        directly rather than a second `/account/activities` call."""
        if self._existing_fill(order_id) is not None:
            return
        filled_qty_raw = data.get("filled_qty")
        filled_avg_price_raw = data.get("filled_avg_price")
        if filled_qty_raw is None or filled_avg_price_raw is None:
            # Defensive only -- a real "filled" order always carries both
            # (captured fixture); never fabricate a price/qty if it doesn't.
            return

        qty = Decimal(str(filled_qty_raw))
        price = Decimal(str(filled_avg_price_raw))
        side = str(data.get("side", "buy"))
        symbol = str(data.get("symbol", ""))
        fees_usd = self._fees_for(symbol=symbol, side=side, price=price, qty=qty)

        ts_raw = data.get("filled_at")
        ts = _parse_alpaca_ts(ts_raw) if ts_raw else _mae_runtime.clock()
        thesis_id = self._thesis_id_for_order(order_id)

        payload = FillRecordedPayload(
            order_id=order_id,
            thesis_id=thesis_id,
            account_ref=self.account_ref,
            ts_utc=ts,
            price=price,
            qty=qty,
            fees_usd=fees_usd,
            side=side,  # type: ignore[arg-type]
            quote_snapshot={},
            symbol=symbol,
        )
        self._append("FillRecorded", payload.model_dump(mode="json"), ts)


__all__ = [
    "ALPACA_LIVE_BASE_URL",
    "ALPACA_LIVE_KEY_ID_ENV",
    "ALPACA_LIVE_SECRET_ENV",
    "ALPACA_PAPER_BASE_URL",
    "ALPACA_PAPER_KEY_ID_ENV",
    "ALPACA_PAPER_SECRET_ENV",
    "ALPACA_STATUS_MAP",
    "AlpacaBroker",
]
