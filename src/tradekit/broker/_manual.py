"""`ManualBroker` -- advisory-mode adapter (DESIGN §8.4, D16, SPRINT P3
batch D). Implements `BrokerPort` structurally (no inheritance needed --
the Protocol is `runtime_checkable` and duck-typed, same as `PaperBroker`).

Flow (§8.4): the framework produces a thesis + recommendation; Mike
executes off-platform on Kraken/Cash App; `broker.record_manual_fill(...)`
writes a `FillRecorded` event with `actor="mike"` (the ONE place a human
actor, not `system:*`/`agent:*`, appears in a money-path ledger append --
DESIGN §8.4's own wording, "grading is then identical to bot positions"
once that fill lands). `submit()` is permanently disabled -- an advisory
account never places a real order through this adapter; it raises
`broker._port.AdvisoryOnly` (typed, canonical home per that module's own
docstring).

State discipline: SAME "no mutable broker state" pin as `PaperBroker`
(module docstring, `_paper.py`) -- an instance holds only `account_ref`/
`_ledger`; `account()`/`positions()`/`fills()` are ledger projections over
`FillRecorded` history for this `account_ref`, computed fresh every call.

Status THIS batch (TDD red phase, "Failing tests + stubs" dispatch): every
method below is an unconditional `NotImplementedError` stub -- the dev pass
lands real bodies, mirroring `PaperBroker.account`/`positions`/`fills`'s
already-real projection arithmetic (batch B) but sourced from
`FillRecordedPayload`s carrying THIS `account_ref` with no `OrderSubmitted`/
`OrderAck` pair backing them (advisory fills never round-trip through
`submit`). `record_manual_fill` (the module-level function `broker.
record_manual_fill` delegates to, mirroring `_pipeline.execute_order`'s
delegation shape) is the write path: append `FillRecorded(actor="mike")`,
then invoke `thesis._machine`'s private activation seam (ASSUMPTIONS 118,
"the pipeline's own pinned single caller" -- extended this batch to
`record_manual_fill` as the advisory path's equivalent caller) so an
advisory fill activates its thesis exactly like a broker-pipeline fill
does.

Kraken read-only balance tracking (sprint doc story 3.5, DESIGN §8.4):
DEFERRED past P3 (CTO pin, this batch) -- `reconcile` support for advisory
accounts is STUBBED to compare RECORDED FILLS ONLY (no external balance
fetch); wiring the read-only Kraken key is flagged P4-adjacent (needs the
rotated key, Mike's own precondition per the sprint doc) -- see
`tests/ASSUMPTIONS.md` round-20.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

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

# 'agent:<model>' | 'mike' | 'system:<job>' -- record_manual_fill's ledger
# append uses 'mike' directly (§8.4), NOT this constant; this module-level
# constant exists only for symmetry with PaperBroker/broker.__init__'s own
# _ACTOR convention documentation, unused by any write path in THIS module.
_ACTOR = "mike"


class ManualBroker:
    """One named advisory account (`"advisory:kraken"`, `"advisory:
    cashapp"`, ...) -- see module docstring for the projection discipline
    and the batch-D stub status of every method below."""

    def __init__(self, account_ref: str, ledger: Ledger | None = None) -> None:
        self.account_ref = account_ref
        self._ledger = ledger if ledger is not None else default_ledger()

    def account(self) -> AccountState:
        """Advisory `AccountState` from `FillRecorded` history for this
        `account_ref` -- same arithmetic shape as `PaperBroker.account`
        (batch B), sourced from human-recorded fills instead of simulated
        ones. STUB -- dev pass."""
        raise NotImplementedError(
            f"ManualBroker({self.account_ref!r}).account(): SPRINT P3 batch D dev pass lands "
            "this (§8.4 advisory account-state projection)"
        )

    def positions(self) -> list[Position]:
        """STUB -- dev pass; same per-symbol net-qty projection as
        `PaperBroker.positions` (batch B), over advisory `FillRecorded`
        history."""
        raise NotImplementedError(
            f"ManualBroker({self.account_ref!r}).positions(): SPRINT P3 batch D dev pass lands "
            "this (§8.4)"
        )

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Permanently disabled (§8.4, D16) -- an advisory account never
        places a real order through this adapter; the ONLY legal write path
        is `broker.record_manual_fill`. Raises `AdvisoryOnly`
        unconditionally. STUB THIS BATCH (raises `NotImplementedError`
        pending the dev pass -- see module docstring's "Failing tests +
        stubs" note); the dev pass's real body is a ONE-LINE `raise
        AdvisoryOnly(...)`, no other logic, so this stub already names the
        exact target behavior for the tests to pin against."""
        raise NotImplementedError(
            f"ManualBroker({self.account_ref!r}).submit(...): SPRINT P3 batch D dev pass lands "
            "this -- real body unconditionally raises broker._port.AdvisoryOnly (§8.4, D16)"
        )

    def order_status(self, order_id: str) -> OrderStatus:
        """An advisory account has no broker-side order lifecycle (§8.4:
        Mike executes off-platform) -- STUB; dev pass's real body is
        expected to return `OrderStatus(order_id=order_id,
        status="rejected")` unconditionally (no `OrderSubmitted` producer
        exists on this adapter), mirroring `PaperBroker.order_status`'s own
        "no submitted event on record" branch."""
        raise NotImplementedError(
            f"ManualBroker({self.account_ref!r}).order_status({order_id!r}): SPRINT P3 batch D "
            "dev pass lands this (§8.4)"
        )

    def fills(self, since: datetime) -> list[Fill]:
        """STUB -- dev pass; same `FillRecorded`-since-projection shape as
        `PaperBroker.fills` (batch B), ASCENDING by `ts_utc` (§8.1's
        conformance pin), filtered to THIS `account_ref`."""
        raise NotImplementedError(
            f"ManualBroker({self.account_ref!r}).fills({since!r}): SPRINT P3 batch D dev pass "
            "lands this (§8.4)"
        )


def record_manual_fill(
    thesis_id: str,
    price: Decimal,
    qty: Decimal,
    fees_usd: Decimal,
    side: Literal["buy", "sell"],
    symbol: str,
    account_ref: str,
) -> Fill:
    """`tk fill record` / `broker.record_manual_fill`'s real body (SPRINT
    P3 batch D dev pass lands this) -- STUB this batch.

    Pinned algorithm (DESIGN §8.4, D16, encoded here so the dev pass never
    has to re-derive it):
      1. append `FillRecordedPayload` via a ledger `Event` whose `actor`
         field is the LITERAL string `"mike"` (§8.4 -- the one human actor
         in a money-path ledger append; `order_id` is a fresh ULID since an
         advisory fill has no preceding `OrderSubmitted`/`OrderAck` pair).
      2. invoke `thesis._machine`'s private activation seam (ASSUMPTIONS
         118's "pipeline's own pinned single caller" pin, extended to this
         module as the advisory path's equivalent caller) so the thesis
         transitions `approved -> active` on the FIRST advisory fill,
         exactly like a broker-pipeline fill does -- "grading is then
         identical to bot positions" (§8.4).
      3. return the `contracts.Fill` read-model shape (mirrors
         `PaperBroker.submit`'s own `OrderAck` return discipline: the
         caller gets a typed confirmation, not a raw event id).

    R-009/R-014 (§8.4: "advisory accounts get the SAME R-009 drawdown
    breaker and R-014 cooling-off ... the pipeline exists to catch that, so
    it applies to Mike too") are NOT re-checked here -- `record_manual_fill`
    is a POST-HOC recording verb (Mike already executed off-platform by the
    time this is called), not a pre-trade gate; R-009/R-014 apply to
    advisory accounts via `policy.evaluate`'s existing context assembly
    whenever a THESIS is submitted/approved for an `"advisory:*"`
    `account_ref`, same as any other account. FLAGGED (ASSUMPTIONS round-20):
    confirm this reading with Mike -- the sprint doc's phrasing could also
    be read as "record_manual_fill itself must re-run the breaker check",
    which this stub does NOT implement.
    """
    raise NotImplementedError(
        f"broker._manual.record_manual_fill(thesis_id={thesis_id!r}, account_ref="
        f"{account_ref!r}): SPRINT P3 batch D dev pass lands this (§8.4, D16)"
    )


__all__ = ["ManualBroker", "record_manual_fill"]
