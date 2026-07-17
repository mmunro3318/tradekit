"""`PaperBroker` — our own deterministic paper-fill adapter (DESIGN §8.3,
TD-7, SPRINT P3 batch B, Opus-gated fill model). Implements `BrokerPort`
(`_port.py`) structurally (no inheritance needed — the Protocol is
`runtime_checkable` and duck-typed).

State discipline (CTO pin, binding): a `PaperBroker` instance holds NO
mutable trading state of its own — `account_ref` and a `Ledger` handle are
the only instance attributes. Every other value (`account()`, `positions()`,
`fills()`) is a projection computed FRESH from ledger events
(`AccountCreated` for principal, `FillRecorded` history for realized cash/
positions) on every call — the same "ledger events only" discipline as
`thesis`/`policy`'s read verbs, so two `PaperBroker(account_ref=...)`
instances pointed at the same ledger always agree, and replaying the event
log reproduces identical state (§8.3's determinism pin, TD-18 ring 3).

Fill model (§8.3, the sprint's pre-registered Opus review focus — pinned
here for the batch-B dev pass; `tests/unit/broker/test_paper_fills.py` is
the executable spec, `test_paper_account_state.py` covers the ledger-
projection arithmetic):

  MARKET orders — price = the latest CLOSED cached bar's `close` (fetched
  via `mae._runtime.get_closed_bars`, the module-attribute form, same
  sanctioned-seam discipline as `thesis._grade_wiring`) as the venue MID,
  adjusted by the half-spread from `tradekit.costs.price_friction(venue,
  asset_class, notional_usd, side)` — BUY pays UP (`mid * (1 +
  half_spread_rate)`), SELL receives DOWN (`mid * (1 - half_spread_rate)`).
  `notional_usd` for the friction lookup is `mid * qty` (the pre-adjustment
  notional — friction prices OFF the mid, not off its own output, avoiding
  circularity). The SAME `Friction.fee_usd` is charged as a separate fee
  field (never folded into the fill price). The quote snapshot
  (`ts_open`/`close`/`source` of the bar that priced the fill) is stored ON
  the `FillRecordedPayload` — every paper fill auditable (§8.3).

  LIMIT orders — rest until a LATER closed bar trades THROUGH the limit by
  >= 1 tick: a buy limit `L` fills when `bar.low <= L - tick_size`; a sell
  limit `L` fills when `bar.high >= L + tick_size`. An exact touch
  (`bar.low == L` / `bar.high == L`) is NEVER a fill (G5). Fill price is the
  LIMIT price itself, not the bar's through price (conservative — no
  assumption of favorable execution). No partial fills in MVP: an order
  either fills its full `qty` in one `FillRecorded` event or stays
  `OrderStatus(status="open")` forever (until canceled, out of scope this
  batch).

  Unknown symbol / no cached bars: a market or limit evaluation that cannot
  fetch ANY closed bars for `order.asset.symbol` raises
  `broker._port.NoQuoteAvailable` (CTO adjudication, ASSUMPTIONS Round-17
  entry 111 — pinned, no longer open) and appends ZERO events — never a
  guess-fill; a broker that invents prices is the exact fabrication class
  ASSUMPTIONS 71 exists to kill.

Token gate (§8.2/§15, batch-B scope — SHAPE ONLY): `submit()` refuses
(`BrokerTokenRequired`) when `verdict` is `None`/absent, or structurally
malformed (empty `verdict_id`/`policy_version_hash`). Full ledger-side
verification — does `verdict.verdict_id` reference a REAL, unconsumed,
allow `VerdictIssued` event for THIS thesis with no later deny — is
deliberately deferred to batch C's `_verify_token` hardening pass (the
two-phase pipeline, `execute_order`, is the only caller in the real money
path; PaperBroker's own shape check is a structural floor, not the full
guarantee). `_verify_token` below is the documented seam batch C extends;
it must not be reimplemented ad hoc elsewhere.

STUB (SPRINT P3 batch B, red phase): every method below raises
`NotImplementedError` unconditionally. The dev pass that turns this batch
green implements the fill model exactly as pinned above and in the test
files' hand-derived arithmetic.
"""

from __future__ import annotations

from datetime import datetime

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


class PaperBroker:
    """One named paper account (`"paper:alpha"`, `"paper:conformance-
    suite"`, ...), a ledger projection — see module docstring for the "no
    mutable broker state" discipline and the fill model this batch pins."""

    def __init__(self, account_ref: str, ledger: Ledger | None = None) -> None:
        self.account_ref = account_ref
        self._ledger = ledger if ledger is not None else default_ledger()

    def account(self) -> AccountState:
        """`AccountState` from `AccountCreated.principal_usd` + realized
        `FillRecorded` history (settled cash = principal + Sigma(sell
        proceeds - buy cost - fees), §8.1/TD-24). STUB — batch B dev pass."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r}).account(): batch B dev pass computes "
            "AccountState from AccountCreated principal + realized FillRecorded history "
            "(§8.1, TD-24)"
        )

    def positions(self) -> list[Position]:
        """Position qty/avg_price per symbol, derived from `FillRecorded`
        history for this `account_ref` (§8.1). STUB — batch B dev pass."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r}).positions(): batch B dev pass derives "
            "Position rows from FillRecorded history (§8.1)"
        )

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Validate `verdict` via `_verify_token` (shape-only this batch,
        see module docstring), then evaluate the market/limit fill model
        (§8.3) and append `OrderSubmitted`/`OrderAck`/`FillRecorded` (market)
        or leave the order resting (limit, until a later `fills`/status
        check trades through it). STUB — batch B dev pass."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r}).submit(...): batch B dev pass implements "
            "the fill model (§8.3) behind _verify_token's shape-only gate (§8.2/§15)"
        )

    def order_status(self, order_id: str) -> OrderStatus:
        """Current lifecycle status of a previously-submitted order —
        `"filled"` immediately for a market order (§8.3: no partials, fills
        synchronously at `submit()` time against the latest closed bar),
        `"open"` for a limit order until a later closed bar trades through
        it. STUB — batch B dev pass."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r}).order_status({order_id!r}): batch B dev "
            "pass implements order-status derivation (§8.3)"
        )

    def fills(self, since: datetime) -> list[Fill]:
        """`FillRecorded` events at/after `since` for this `account_ref`,
        ASCENDING by `ts_utc` (§8.1's conformance pin). STUB — batch B dev
        pass."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r}).fills({since!r}): batch B dev pass reads "
            "FillRecorded history off the ledger (§8.1)"
        )

    def _verify_token(self, verdict: VerdictToken | None) -> None:
        """Documented seam (§8.2/§15): batch B's shape-only check (`verdict`
        present, `verdict_id`/`policy_version_hash` non-empty) raises
        `BrokerTokenRequired` on failure; batch C hardens this into a real
        ledger lookup (does `verdict.verdict_id` name a real, unconsumed,
        allow `VerdictIssued` for this thesis with no later deny) WITHOUT
        changing this method's name or call site. STUB — batch B dev pass
        implements even the shape-only check; not called by anything yet
        (`submit` itself is still an unconditional stub above)."""
        raise NotImplementedError(
            f"PaperBroker({self.account_ref!r})._verify_token(...): batch B dev pass "
            "implements the shape-only check; batch C hardens it into a ledger lookup "
            "(§8.2/§15) without renaming this seam"
        )


__all__ = ["PaperBroker"]
