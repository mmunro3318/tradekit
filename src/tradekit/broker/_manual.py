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

Status (SPRINT P3 batch D dev pass, GREEN): every method is real now,
mirroring `PaperBroker.account`/`positions`/`fills`'s already-real
projection arithmetic (batch B) but sourced from `FillRecordedPayload`s
carrying THIS `account_ref` with no `OrderSubmitted`/`OrderAck` pair backing
them (advisory fills never round-trip through `submit`). `record_manual_fill`
(the module-level function `broker.record_manual_fill` delegates to,
mirroring `_pipeline.execute_order`'s delegation shape) is the write path:
append `FillRecorded(actor="mike")`, then invoke `thesis._machine`'s private
activation seam (ASSUMPTIONS 118, "the pipeline's own pinned single caller"
-- extended this batch to `record_manual_fill` as the advisory path's
equivalent caller) so an advisory fill activates its thesis exactly like a
broker-pipeline fill does -- swallowing `ValueError`/`IllegalTransition` when
the thesis isn't a real, currently-`approved` one (this verb never refuses,
ASSUMPTIONS round-20 CTO ratification), plus an R-009 lockout visibility
append (`GateViolationDetected`, same ratification).

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
from typing import Any, Literal

from ulid import ULID

from tradekit.broker._port import AdvisoryOnly
from tradekit.contracts import (
    AccountState,
    Event,
    EventFilter,
    Fill,
    FillRecordedPayload,
    GateViolationDetectedPayload,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Position,
    VerdictToken,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.policy import _context as _policy_context
from tradekit.policy._dials import PolicyDials
from tradekit.thesis import _machine as _thesis_machine
from tradekit.thesis._machine import IllegalTransition

# 'agent:<model>' | 'mike' | 'system:<job>' -- record_manual_fill's
# FillRecorded append uses the LITERAL string 'mike' directly (§8.4, the
# ONE human actor in a money-path ledger append), NOT this constant. This
# constant IS the actor for record_manual_fill's own R-009 visibility
# append (`GateViolationDetected`, ASSUMPTIONS round-20) -- a machine-
# derived detection, not a human action, same convention as
# `policy.__init__`'s own `_ACTOR = "system:policy"`.
_ACTOR = "system:broker-manual"


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
        ones. No `AccountCreated` producer exists for advisory accounts
        (Mike's off-platform balance, not a principal this codebase seeds)
        -- principal is a GENUINELY COMPUTED `Decimal("0")` (never assumed
        otherwise), so `equity_usd`/`settled_cash_usd`/`buying_power_usd`
        all collapse to realized fill cash flow alone."""
        cash = Decimal("0")
        for fill in self._fill_events():
            notional = fill["price"] * fill["qty"]
            if fill["side"] == "buy":
                cash -= notional + fill["fees_usd"]
            else:
                cash += notional - fill["fees_usd"]
        return AccountState(
            account_ref=self.account_ref,
            equity_usd=cash,
            settled_cash_usd=cash,
            buying_power_usd=cash,
        )

    def positions(self) -> list[Position]:
        """Same per-symbol net-qty projection as `PaperBroker.positions`
        (batch B), over advisory `FillRecorded` history."""
        by_symbol: dict[str, tuple[Decimal, Decimal]] = {}
        for fill in self._fill_events():
            symbol = fill["symbol"]
            qty, avg_price = by_symbol.get(symbol, (Decimal("0"), Decimal("0")))
            if fill["side"] == "buy":
                new_qty = qty + fill["qty"]
                avg_price = (
                    fill["price"]
                    if qty == 0
                    else (qty * avg_price + fill["qty"] * fill["price"]) / new_qty
                )
                qty = new_qty
            else:
                qty = qty - fill["qty"]
            by_symbol[symbol] = (qty, avg_price)

        return [
            Position(account_ref=self.account_ref, symbol=symbol, qty=qty, avg_price=avg_price)
            for symbol, (qty, avg_price) in by_symbol.items()
            if qty != 0
        ]

    def submit(self, order: OrderRequest, verdict: VerdictToken) -> OrderAck:
        """Permanently disabled (§8.4, D16) -- an advisory account never
        places a real order through this adapter; the ONLY legal write path
        is `broker.record_manual_fill`."""
        raise AdvisoryOnly(
            f"ManualBroker({self.account_ref!r}).submit(...): advisory accounts never place a "
            "real order through this adapter -- record a fill via broker.record_manual_fill "
            "once Mike has executed off-platform (§8.4, D16)"
        )

    def order_status(self, order_id: str) -> OrderStatus:
        """An advisory account has no broker-side order lifecycle (§8.4:
        Mike executes off-platform) -- no `OrderSubmitted` producer exists
        on this adapter, so every `order_id` reports `"rejected"`
        unconditionally, mirroring `PaperBroker.order_status`'s own "no
        submitted event on record" branch."""
        return OrderStatus(order_id=order_id, status="rejected")

    def fills(self, since: datetime) -> list[Fill]:
        """Same `FillRecorded`-since-projection shape as `PaperBroker.fills`
        (batch B), ASCENDING by `ts_utc` (§8.1's conformance pin), filtered
        to THIS `account_ref`."""
        out = []
        for event in self._ledger.query(EventFilter(types=["FillRecorded"], since=since)):
            payload = event.payload
            if payload.get("account_ref") != self.account_ref:
                continue
            out.append(
                Fill(
                    order_id=payload["order_id"],
                    thesis_id=payload["thesis_id"],
                    ts_utc=payload["ts_utc"],
                    price=Decimal(str(payload["price"])),
                    qty=Decimal(str(payload["qty"])),
                    fees_usd=Decimal(str(payload["fees_usd"])),
                    quote_snapshot=payload.get("quote_snapshot", {}),
                )
            )
        out.sort(key=lambda f: f.ts_utc)
        return out

    def _fill_events(self) -> list[dict[str, Any]]:
        """This account's `FillRecorded` payloads, ASCENDING by `ts_utc`, as
        plain dicts with money fields normalized to `Decimal` -- mirrors
        `PaperBroker._fill_events`."""
        rows = []
        for event in self._ledger.query(EventFilter(types=["FillRecorded"])):
            payload = event.payload
            if payload.get("account_ref") != self.account_ref:
                continue
            rows.append(
                {
                    "ts_utc": payload["ts_utc"],
                    "price": Decimal(str(payload["price"])),
                    "qty": Decimal(str(payload["qty"])),
                    "fees_usd": Decimal(str(payload["fees_usd"])),
                    "side": payload["side"],
                    "symbol": payload["symbol"],
                }
            )
        rows.sort(key=lambda r: r["ts_utc"])
        return rows


def record_manual_fill(
    thesis_id: str,
    price: Decimal,
    qty: Decimal,
    fees_usd: Decimal,
    side: Literal["buy", "sell"],
    symbol: str,
    account_ref: str,
) -> Fill:
    """`tk fill record` / `broker.record_manual_fill`'s real body (DESIGN
    §8.4, D16, SPRINT P3 batch D).

    Algorithm:
      1. append `FillRecordedPayload` via a ledger `Event` whose `actor`
         field is the LITERAL string `"mike"` (§8.4 -- the one human actor
         in a money-path ledger append; `order_id` is a fresh ULID since an
         advisory fill has no preceding `OrderSubmitted`/`OrderAck` pair).
      2. invoke `thesis._machine`'s private activation seam (ASSUMPTIONS
         118's "pipeline's own pinned single caller" pin, extended to this
         module as the advisory path's equivalent caller) so the thesis
         transitions `approved -> active` on the FIRST advisory fill,
         exactly like a broker-pipeline fill does -- "grading is then
         identical to bot positions" (§8.4). A thesis_id with no real
         `ThesisDrafted` event, or one not currently `approved` (a
         synthetic/test thesis_id, a fill recorded against a thesis that
         never went through the lifecycle), does NOT block the fill --
         `_machine.derive_state`'s `ValueError`/`_machine.IllegalTransition`
         are swallowed here: this verb's OWN job is recording what actually
         happened off-platform, never gating on thesis lifecycle state
         (that gating already lives in `thesis`'s own verbs).
      3. R-009 lockout visibility (CTO ratification, ASSUMPTIONS round-20,
         2026-07-17: "the verb NEVER refuses -- the ledger must reflect
         reality, a fill that happened cannot be denied retroactively;
         instead, recording while an R-009 lockout ... is in force appends
         GateViolationDetected alongside the fill (visibility -> series
         cleanliness -> promotion consequences, F7's actual teeth)"): read
         the SAME trailing-30d-drawdown computation `policy._rules._check_
         r009` uses (`policy._context._trailing_drawdown_pct`) for this
         `account_ref`; `>= dials.drawdown_breaker_pct` -> append
         `GateViolationDetected(rule_id="R-009", ...)` ALONGSIDE the fill --
         never instead of it, never gating the append above. R-014
         (cooling-off) re-enforcement is FLAGGED, not implemented here
         (ASSUMPTIONS round-20 entry 131 -- ordinary pre-trade enforcement
         via `policy.evaluate` at submit/approve time covers advisory
         accounts identically to any other `account_ref`; this verb stays a
         POST-HOC recorder with no gate of its own beyond the R-009
         visibility append above).
      4. return the `contracts.Fill` read-model shape (mirrors
         `PaperBroker.submit`'s own `OrderAck` return discipline: the
         caller gets a typed confirmation, not a raw event id).
    """
    ledger = default_ledger()
    now = _mae_runtime.clock()
    order_id = str(ULID())

    fill_payload = FillRecordedPayload(
        order_id=order_id,
        thesis_id=thesis_id,
        account_ref=account_ref,
        ts_utc=now,
        price=price,
        qty=qty,
        fees_usd=fees_usd,
        side=side,
        quote_snapshot={},
        symbol=symbol,
    )
    _append(ledger, "FillRecorded", fill_payload.model_dump(mode="json"), now, actor="mike")

    try:
        _thesis_machine._activate_on_fill(ledger, thesis_id, order_id, now)
    except (ValueError, IllegalTransition):
        # A synthetic/nonexistent thesis, or one not currently `approved` --
        # this verb records what happened off-platform; it never refuses on
        # thesis lifecycle state (see docstring point 2).
        pass

    dials = PolicyDials.load()
    drawdown = _policy_context._trailing_drawdown_pct(ledger, dials, account_ref, now)
    if drawdown >= dials.drawdown_breaker_pct:
        violation_payload = GateViolationDetectedPayload(
            rule_id="R-009",
            account_ref=account_ref,
            thesis_id=thesis_id,
            measured=str(drawdown),
            limit=str(dials.drawdown_breaker_pct),
            why=(
                "R-009 drawdown circuit breaker is active for this account -- the manual fill "
                "is recorded for visibility, never refused (§8.4, ASSUMPTIONS round-20)"
            ),
        )
        _append(
            ledger, "GateViolationDetected", violation_payload.model_dump(mode="json"), now,
            actor=_ACTOR,
        )

    return Fill(
        order_id=order_id,
        thesis_id=thesis_id,
        ts_utc=now,
        price=price,
        qty=qty,
        fees_usd=fees_usd,
        quote_snapshot={},
    )


def _append(
    ledger: Ledger, event_type: str, payload: dict[str, Any], ts: datetime, *, actor: str
) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type=event_type,  # type: ignore[arg-type]
        actor=actor,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


__all__ = ["ManualBroker", "record_manual_fill"]
