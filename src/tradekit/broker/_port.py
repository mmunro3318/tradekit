"""`BrokerPort` — the venue-neutral broker protocol (DESIGN §8.1).

Five methods; every venue quirk (Alpaca fractional rules, crypto symbol
mapping, paper-sim internals) hides behind them. `broker.get(account_ref)`
(batch B) resolves an account_ref to a concrete adapter implementing this
Protocol. `submit` REQUIRES a `VerdictToken` argument (§8.2/§15) —
structural: an adapter cannot be called without SOMETHING claiming to be an
allow-verdict, even though validating that token's authenticity against the
ledgered `VerdictIssued` event is the adapter's own job (batch B/C).

Every adapter this Protocol governs (PaperBroker/AlpacaBroker/ManualBroker,
batches B/D) must pass the single conformance suite in
`tests/contract/test_broker_port.py` (TD-18 ring 2) — that suite, not this
module, is the executable spec of "what a conformant adapter does."
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from tradekit.contracts import (
    AccountState,
    Fill,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Position,
    VerdictToken,
)
from tradekit.mae._data.errors import ProviderRequestError


class BrokerTokenRequired(Exception):
    """The one refusal type every `BrokerPort.submit` adapter raises when
    `verdict` is missing/invalid (§8.2, §15) — canonical home (SPRINT P3
    batch B) so `tests/contract/test_broker_port.py`'s conformance suite and
    every adapter module import the SAME class object; `pytest.raises`
    matches by class identity, so a duplicate same-named class defined
    inside the test module (as the batch-A skeleton did, pending a real
    adapter to import from) would never actually catch a real adapter's
    exception."""


class AdvisoryOnly(Exception):
    """Raised by `ManualBroker.submit` (SPRINT P3 batch D, DESIGN §8.4,
    D16) -- an advisory account (`"advisory:*"`) never places a real
    order; the flow is thesis + recommendation -> Mike executes off-
    platform -> `broker.record_manual_fill` writes the `FillRecorded`
    event with `actor="mike"`. Canonical home alongside `BrokerTokenRequired`/
    `NoQuoteAvailable` for the same identity-match reason (the conformance
    suite and `_manual.py` must import the SAME class object)."""


class LiveTradingDisabled(Exception):
    """Raised by `broker.get("live:*")` (SPRINT P4-PAPER batch A, addendum
    2) when the live-venue routing's fail-closed conjunction is not
    satisfied: EITHER the `PolicyDials.live_trading_enabled` dial is
    `False` (the default, `config.toml`) OR the live env keys
    (`ALPACA_LIVE_KEY_ID`/`ALPACA_LIVE_SECRET`) are absent from the
    environment -- BOTH conditions (dial true AND keys present) are
    required before `"live:"` resolves to a real `AlpacaBroker` pointed at
    Alpaca's live trading base URL. This REPLACES the SPRINT P3 batch C
    temporary routing (`"live:"` -> `PaperBroker`, ASSUMPTIONS round-18) --
    `"live:"` never again resolves to `PaperBroker` (the round-19 pin,
    re-pointed this batch). Canonical home alongside `BrokerTokenRequired`/
    `NoQuoteAvailable`/`AdvisoryOnly` for the same identity-match reason."""


class BrokerCredentialsMissing(ProviderRequestError):
    """Raised by EVERY `AlpacaBroker` method (SPRINT P4-PAPER, round-23 CTO
    ratification + adjudication addendum: no-creds is loud everywhere,
    never a fabricated default -- a $0 `account()` or an empty `fills()`
    returned when the venue was never asked is exactly the fabrication
    class ASSUMPTIONS 71 exists to kill) when this account's own
    `key_id_env`/`secret_env` environment variables are absent -- the
    pre-HTTP credential guard (mirrors `mae._data.alpaca_data.
    AlpacaDataProvider.get_bars`'s "fail before the request" pattern,
    ASSUMPTIONS 35); in `submit()` it is checked AFTER token verification
    (§8.2/§15 -- an unauthorized caller with no allow-verdict is refused on
    THAT grounds first, never leaking "which env var is missing") but
    BEFORE any HTTP call. Canonical home in `broker._port`
    alongside `BrokerTokenRequired`/`AdvisoryOnly`/`LiveTradingDisabled`/
    `NoQuoteAvailable`, for the same identity-match reason -- a `broker`-
    native named type per round-23's ratification ("broker-local typed
    `BrokerCredentialsMissing` in _port.py, never import mae._data.errors
    across the module boundary" for `_alpaca.py` itself), rather than
    reusing `mae._data.errors.ProviderRequestError` bare.

    Subclasses `ProviderRequestError` -- a deliberate, documented exception
    to the ratification's "never import mae._data.errors" wording (this ONE
    declaration, here in `_port.py`, is the only place `broker` touches that
    module): `tests/unit/broker/test_alpaca_broker.py::
    test_submit_refuses_before_any_http_call_when_env_keys_are_absent` (a
    FROZEN, pre-existing test, written before the round-23 ratification
    landed) asserts `pytest.raises(ProviderRequestError)` verbatim, and a
    sibling, unrelated exception type would silently fail to match it by
    class identity. Subclassing is the only way to satisfy BOTH that frozen
    assertion AND the ratification's "broker-native named type" intent at
    once -- flagged here, not silently resolved, per the dev-pass's own
    "stop and flag anything not resolvable within scope" rule."""


class NoQuoteAvailable(Exception):
    """Raised by an adapter's fill evaluation when the order's symbol has NO
    cached closed bars to price against (CTO adjudication, SPRINT P3 batch B
    — ASSUMPTIONS Round-17 entry 111 pin): a broker that invents a price is
    the exact fabrication class ASSUMPTIONS 71 exists to kill, so a market
    order with no quote is a typed error and appends ZERO events — never a
    guess-fill, never a silently-resting order. Canonical home alongside
    `BrokerTokenRequired` for the same identity-match reason."""


@runtime_checkable
class BrokerPort(Protocol):
    def account(self) -> AccountState:
        """Equity, settled cash, buying power (§8.1)."""
        ...

    def positions(self) -> list[Position]:
        """Every open position on this account."""
        ...

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Adapters REFUSE without an allow-`VerdictToken` (§8.2, §15) —
        raises a typed refusal (e.g. `BrokerTokenRequired`, batch B) when
        `verdict` is missing/invalid, never a silent no-op submit."""
        ...

    def order_status(self, order_id: str) -> OrderStatus:
        """Current lifecycle status of a previously-submitted order."""
        ...

    def fills(self, since: datetime) -> list[Fill]:
        """Fills recorded at or after `since`, ASCENDING by `ts_utc`."""
        ...


__all__ = [
    "AdvisoryOnly",
    "BrokerCredentialsMissing",
    "BrokerPort",
    "BrokerTokenRequired",
    "LiveTradingDisabled",
    "NoQuoteAvailable",
]
