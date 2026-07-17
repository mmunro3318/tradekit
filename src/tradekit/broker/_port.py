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


class BrokerTokenRequired(Exception):
    """The one refusal type every `BrokerPort.submit` adapter raises when
    `verdict` is missing/invalid (§8.2, §15) — canonical home (SPRINT P3
    batch B) so `tests/contract/test_broker_port.py`'s conformance suite and
    every adapter module import the SAME class object; `pytest.raises`
    matches by class identity, so a duplicate same-named class defined
    inside the test module (as the batch-A skeleton did, pending a real
    adapter to import from) would never actually catch a real adapter's
    exception."""


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


__all__ = ["BrokerPort", "BrokerTokenRequired", "NoQuoteAvailable"]
