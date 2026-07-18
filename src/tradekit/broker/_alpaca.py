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

STUB STATUS (this batch, TDD red phase): every one of the five `BrokerPort`
methods below raises `NotImplementedError` unconditionally -- the
"declarative routing is real, adapter methods stay red" split `PaperBroker`
itself went through across SPRINT P3 batches A->B (`_paper.py`'s own
`test_broker_stubs.py` history). `tests/unit/broker/test_alpaca_broker.py`
and the "alpaca-paper" conformance-suite case
(`tests/contract/test_broker_port.py`) pin the REAL behavior the batch-B
dev pass must produce -- every assertion in those tests is expected RED
this batch for that reason, not a bug in the stub.

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

Pre-HTTP credential guard (batch B pin, mirrors `alpaca_data.
AlpacaDataProvider.get_bars`'s own "fail before the request" pattern,
ASSUMPTIONS 35): `submit`/`order_status`/`fills` must check
`os.environ.get(self._key_id_env)`/`self._secret_env` and raise a typed
refusal -- provisionally `tradekit.mae._data.errors.ProviderRequestError`
-- naming the missing var, BEFORE constructing any request. Checked AFTER
token verification (a caller with no allow-verdict is refused on that
grounds first, never leaking "which env var is missing" to an unauthorized
caller) but BEFORE the HTTP client touches the network.

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

from datetime import datetime
from typing import Literal

import httpx

from tradekit.contracts import (
    AccountState,
    Fill,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Position,
    VerdictToken,
)
from tradekit.ledger import Ledger, default_ledger

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


class AlpacaBroker:
    """One Alpaca trading account (paper or live, per `base_url`/
    `key_id_env`/`secret_env` at construction) -- see module docstring for
    the batch-A stub status and the batch-B pins every method's real body
    must satisfy."""

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
        """Batch B: `GET {base_url}/account` -> `AccountState` (equity,
        settled cash, buying power from Alpaca's own account object,
        `Decimal(str(x))` per field -- same JSON-number precision discipline
        as `alpaca_data.py`, ASSUMPTIONS 32)."""
        raise NotImplementedError(
            "AlpacaBroker.account(): real body lands SPRINT P4-PAPER batch B "
            "(GET {base_url}/account)"
        )

    def positions(self) -> list[Position]:
        """Batch B: `GET {base_url}/positions` -> `list[Position]`, OR (per
        the CTO pin, TD-7-style) derived from THIS account's own
        `FillRecorded` history the same way `PaperBroker.positions` is --
        flagged for the dev pass to adjudicate (ASSUMPTIONS round-23),
        never improvised here."""
        raise NotImplementedError(
            "AlpacaBroker.positions(): real body lands SPRINT P4-PAPER batch B"
        )

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Batch B: verify `verdict` via the SHARED `broker._tokens.
        verify_token` (module docstring -- closes the submit-time halt seam
        identically to `PaperBroker`), THEN the pre-HTTP credential guard
        (`self._key_id_env`/`self._secret_env`, typed refusal, no network on
        failure), THEN `POST {base_url}/orders` with the captured shape's
        request fields (`symbol`, `notional` or `qty`, `side`, `type`,
        `time_in_force`) -> append `OrderSubmitted`/`OrderAck` from the
        response's `id`/`status` (`"pending_new"` at submit time per the
        captured `order_submit` fixture -> our `"open"`, ALPACA_STATUS_MAP)."""
        raise NotImplementedError(
            "AlpacaBroker.submit(): real body lands SPRINT P4-PAPER batch B "
            "(POST {base_url}/orders, token verified via broker._tokens.verify_token first)"
        )

    def order_status(self, order_id: str) -> OrderStatus:
        """Batch B: `GET {base_url}/orders/{order_id}` -> map Alpaca's
        `status` through `ALPACA_STATUS_MAP` (module docstring's pinned
        table); `filled_qty`/`filled_avg_price` arrive as STRINGS (captured
        `order_get` fixture) -- `Decimal(str(x))`, never bare `Decimal(x)`.
        A `status == "filled"` transition (first time observed) is also
        where a `FillRecorded` gets appended from the matching activity (see
        `fills()`'s docstring) -- fees_usd via `tradekit.costs.
        price_friction("alpaca", asset.asset_class, notional_usd, side).
        fee_usd` (module docstring's worked $10 example: 0.0025 * 10 =
        0.025), since Alpaca's own activity carries no fee field."""
        raise NotImplementedError(
            "AlpacaBroker.order_status(): real body lands SPRINT P4-PAPER batch B "
            "(GET {base_url}/orders/{order_id}, ALPACA_STATUS_MAP)"
        )

    def fills(self, since: datetime) -> list[Fill]:
        """Batch B: `GET {base_url}/account/activities?activity_types=FILL`
        (captured `activities` fixture: `price`/`qty`/`cum_qty` as STRINGS,
        `transaction_time` ISO-Z, `order_id` linkage, no fee field) ->
        typed `list[Fill]` ASCENDING by `ts_utc` (§8.1's conformance pin,
        SAME as `PaperBroker.fills`/`ManualBroker.fills`) so `reconcile`
        runs unchanged over this adapter (module docstring)."""
        raise NotImplementedError(
            "AlpacaBroker.fills(): real body lands SPRINT P4-PAPER batch B "
            "(GET {base_url}/account/activities?activity_types=FILL)"
        )


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
