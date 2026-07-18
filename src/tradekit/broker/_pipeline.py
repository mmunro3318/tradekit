"""The two-phase money pipeline + reconcile->auto-halt path (DESIGN §8.2,
§15; SPRINT P3 batch C — CTO pre-registered Opus review focus: TOKEN GATE +
HALT PATH). RED this batch (CTO's red/green split call, same discipline as
`policy._evaluate`'s batch-C-red pass): every function below is an
unconditional `NotImplementedError` stub naming this batch's dev pass; the
docstrings ARE the pinned spec the dev pass implements against, not
aspirational prose to revise later.

`broker.execute_order`/`broker.reconcile`/`broker.cancel_order` (the
`__init__.py` verb surface) delegate here — this module owns the actual
algorithm, per the house deep-module split (`_pipeline.py`/`_paper.py`/
`_manual.py`/`_alpaca.py`, CTO addendum "broker/ layout" pin).

===========================================================================
execute_order(thesis_id) — DESIGN §8.2, VERBATIM STEP ORDER (the sprint's
own "ordering guarantee" chokepoint; tests assert on ledger event order):
===========================================================================

  1. Load the thesis (`thesis._machine.require_state`, allowed=={"approved"}
     only — `thesis._machine.IllegalTransition` propagates unchanged for any
     other state, e.g. draft/submitted/active/rejected/graded). Read the
     thesis's own `ThesisDrafted.contract` for `account_ref`/`asset`/`entry`
     and its `SizingComputed.sizing.recommended_size_usd` (the SAME record
     R-012 sizing-purity compares against — `thesis.submit` already
     ledgered it; this pipeline must not recompute sizing, only read it
     back). Build `contracts.OrderRequest`: `qty = recommended_size_usd /
     entry_price` (entry_price = the contract's own `entry.limit_price`
     when `entry.order_type == "limit"`, else the last `MarketSnapshotTaken.
     last_close` for a market entry — FLAGGED, ASSUMPTIONS round-18: the
     contract's `entry` spec, not a fresh quote, drives both `order_type`
     AND the qty-deriving price, so the submitted order is a mechanical
     transcription of what was already approved, never a fresh sizing
     decision at submit time), `order_type`/`limit_price` copied verbatim
     from `contract["entry"]`, `account_ref` from the contract (NOT a CLI
     argument — the contract is the single source of truth for which
     account this thesis trades against).

  2. `policy.evaluate(ProposedAction(kind="submit_order", account_ref=...,
     requested_by="system:broker-pipeline", thesis_id=thesis_id,
     order=order))` — the module-attribute form (`from tradekit import
     policy` then `policy.evaluate(...)`, never `from tradekit.policy import
     evaluate`) so tests can monkeypatch `"tradekit.broker._pipeline.
     policy.evaluate"` (or equivalently patch `tradekit.policy.evaluate`
     itself — both resolve through the same module object) to force a deny
     or a raise without needing a full rule-catalog fixture. `policy.
     evaluate` itself already appends `ActionProposed` THEN `VerdictIssued`
     (DESIGN §8.2 steps 2-3 are `policy`'s OWN job, not re-implemented
     here) — this pipeline's contribution to the ordering guarantee is
     calling `evaluate` BEFORE `broker.get(account_ref).submit(...)`, never
     after, and never submitting when the verdict denies.

  3. `verdict.allow is False` -> raise `PipelineDenied(verdict)` (typed,
     carries the `Verdict` — the CLI's job to catch this and exit 1 with
     it, `_guard_not_implemented`-style but a NEW guard, since
     `PipelineDenied` is not a `NotImplementedError`). ZERO `Order*` events
     on this path — `policy.evaluate` never touches `broker`, so a deny
     verdict structurally cannot have produced one.

  4. `verdict.allow is True` -> mint a `contracts.VerdictToken(verdict_id=
     verdict.verdict_id, policy_version_hash=verdict.policy_version_hash)`
     (ASSUMPTIONS round-18, the token-minting rule pinned by the sprint
     doc: "token = the verdict_id + policy_version_hash pair, which
     `_verify_token` already validates" — no new ULID, no separate token
     registry; the token IS those two fields, verified against the
     `VerdictIssued` event `policy.evaluate` just appended). Call
     `broker.get(order.account_ref).submit(order, token)` (module-attribute
     `broker.get`, so a monkeypatched adapter is picklable by tests same as
     `policy.evaluate` above). A raise from `.submit(...)` (e.g. a
     monkeypatched adapter simulating a venue outage) propagates UNCAUGHT —
     `ActionProposed`+`VerdictIssued` remain on the ledger (intent + verdict
     survive a broker-side failure, DESIGN §8.2's own ordering guarantee:
     "verdict recorded BEFORE broker call" implies the verdict record
     cannot be undone by what the broker call does next).

  5. `adapter.submit` itself appends `OrderSubmitted`/`OrderAck` (§8.3, a
     `PaperBroker` concern, already real — batch B). This pipeline does NOT
     append those events a second time.

  6. Poll ONCE, synchronously: `adapter.order_status(ack.order_id)` (single
     call — ASSUMPTIONS round-18, "single-poll MVP" pin: paper fills are
     synchronous at `submit()` time for market orders per §8.3, so a market
     order's poll always observes `status="filled"` immediately; a limit
     order's poll may observe `status="open"` and this pipeline does NOT
     loop or block waiting for a later fill — `tk order status` is the
     user-facing re-poll verb for a still-resting limit, not this
     pipeline). `status.status == "filled"` -> proceed to step 7; anything
     else -> return the `OrderAck` as-is, no thesis activation, no R-011
     decrement (a resting limit order has not yet moved money).

  7. On the FIRST fill (i.e., THIS call observed the transition into
     "filled" — never re-fire on an already-filled order's poll, though
     for the market-order synchronous case step 6 and "first fill" are the
     same instant): call the PRIVATE `thesis._machine._activate_on_fill`
     seam (ASSUMPTIONS round-18: "a private thesis._machine-level function
     the pipeline calls, NOT a public verb" — §4.2 pins `thesis`'s public
     surface at exactly six verbs; activation-on-fill is internal
     machinery invoked BY the broker pipeline, per DESIGN §4.2's own
     wording, so it must not grow a seventh public thesis verb). This
     appends `ThesisActivated(thesis_id, order_id, ts_utc)` — legal only
     from `approved` (mirrors every other thesis transition's own
     `require_state` guard); a thesis somehow no longer `approved` here
     (a fabricated race, not reachable through this pipeline's own step-1
     guard in a single-threaded MVP) raises `IllegalTransition` same as any
     other thesis verb.

     THEN, if `order.account_ref` is live-tier (`account_ref.startswith
     ("live:")`) — R-011's live-sequence decrement: ASSUMPTIONS round-18,
     "no new event type" pin. `live_sequence_remaining` is a PURE
     DERIVATION, never a ledgered decrement event:
     `PromotionConfirmed.live_sequence_remaining` (the budget at
     confirmation, always 3) MINUS the count of `FillRecorded` events for
     this `account_ref` at OR AFTER that `PromotionConfirmed`'s own
     `ts_utc` (i.e. "live fills since confirmation" — a live account that
     has already consumed all 3 has no PRODUCER-side action to take here;
     the derivation lives in `policy._context.assemble`'s live-tier wiring,
     read by R-011 on the NEXT `policy.evaluate` call, not written by this
     pipeline at all). This pipeline's own responsibility on the live path
     is exactly ONE thing: nothing beyond appending the `FillRecorded` the
     adapter already appended in step 5 — the decrement is a read-time
     fact, not a write-time one, so there is no separate "decrement" call
     to make here. (Documented here because the sprint doc's step 6 pin
     ["R-011 decrement on live fills"] names this pipeline as the trigger
     point; the actual mechanism lives in `policy._context`.)

  Returns the `OrderAck` from step 5/6 (whichever the caller last observed
  — filled or still-open).

===========================================================================
reconcile(account_ref) — DESIGN §8.2 step 7, §15's "out-of-band detection"
row:
===========================================================================

  Compare `broker.get(account_ref).fills(since=<epoch or account creation>)`
  against this account's own `FillRecorded` ledger history (via
  `EventFilter(types=["FillRecorded"])`, filtered to `account_ref`, mirroring
  `PaperBroker._fill_events`'s own read). Match key: `(order_id, ts_utc,
  qty)` (ASSUMPTIONS round-18, pinned by the sprint doc verbatim — no
  fuzzy/tolerance matching, an exact triple or it's a mismatch). ANY broker
  fill absent from the ledger by that key -> append
  `contracts.ReconciliationRunPayload(result="mismatch", ...)` naming every
  unmatched fill, THEN append `HaltSet(reason=<names the mismatch>, scope=
  "all", set_by="system:broker-pipeline")` (automatic — the SAME `policy.
  halt`-shaped event `policy.halt()` itself appends, appended directly here
  rather than via `policy.halt()` to avoid a `broker` -> `policy` verb-level
  dependency for what is fundamentally a `broker`-observed fact, mirroring
  how `policy.evaluate` never calls into `broker`). Once halted, R-001
  denies every subsequent mutating `policy.evaluate` call — this pipeline
  does not need to do anything further to enforce that; R-001 is already
  real (P2). A CLEAN run (every broker fill matched) appends
  `ReconciliationRun(result="ok", ...)` and NO halt.

  For `PaperBroker` specifically: a paper account's fills are DERIVED from
  the ledger (`PaperBroker.fills()` reads `FillRecorded` back), so a real
  `PaperBroker` can never disagree with its own ledger — the only way to
  exercise the mismatch branch against a `PaperBroker` account is a FAKE
  `BrokerPort` in tests that reports a fill the ledger never saw
  (ASSUMPTIONS round-18: "mocks mirror real shapes" — the fake must return
  `contracts.Fill` instances, not ad hoc dicts, or the reconcile comparison
  itself becomes untyped).

===========================================================================
cancel_order(account_ref, order_id) — additive fifth broker verb (MVP,
ASSUMPTIONS round-18):
===========================================================================

  Only a RESTING order may be canceled: `broker.get(account_ref).
  order_status(order_id).status == "open"` (a limit order that has not yet
  traded through). Any other status (`"filled"`, `"canceled"`, `"rejected"`,
  `"partially_filled"`) -> typed refusal `OrderNotCancelable` (raised here,
  never a silent no-op) naming the observed status; ZERO events appended on
  the refusal path. A cancelable order appends `contracts.
  OrderCancelledPayload` (`OrderCancelled` event type) — this pipeline's
  own append, since no adapter method exists for it (§8.1's five methods
  are unchanged; cancellation is pipeline-level bookkeeping over the
  adapter's own `order_status` read, not a sixth adapter method).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from ulid import ULID

from tradekit.contracts import (
    AssetRef,
    Event,
    EventFilter,
    Fill,
    HaltSetPayload,
    OrderAck,
    OrderCancelledPayload,
    OrderRequest,
    ProposedAction,
    ReconciliationRunPayload,
    Verdict,
    VerdictToken,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime
from tradekit.thesis import _machine as _thesis_machine

# 'agent:<model>' | 'mike' | 'system:<job>' — every event this module
# produces directly (OrderCancelled / ReconciliationRun / the auto-halt
# HaltSet) is a machine-derived pipeline action, not an LLM or human action.
_ACTOR = "system:broker-pipeline"


class PipelineDenied(Exception):
    """Raised by `execute_order` when `policy.evaluate` returns a deny
    verdict (DESIGN §8.2 step 4). Carries the `Verdict` so the CLI can exit
    1 with it (`tk order submit`'s own job, `cli/main.py`) without a second
    ledger read — the denying rule_hits are already ON the `Verdict`
    `policy.evaluate` returned."""

    def __init__(self, verdict: Verdict) -> None:
        denying = [hit.rule_id for hit in verdict.rule_hits if hit.outcome == "fail"]
        super().__init__(
            f"execute_order denied by verdict_id={verdict.verdict_id!r} "
            f"(rules: {', '.join(denying) or 'none — see rule_hits'})"
        )
        self.verdict = verdict


class OrderNotCancelable(Exception):
    """Raised by `cancel_order` when the referenced order is not currently
    resting (`order_status(...).status != "open"`) — MVP cancel semantics
    (ASSUMPTIONS round-18), never a silent no-op."""

    def __init__(self, order_id: str, status: str) -> None:
        super().__init__(
            f"order_id={order_id!r} cannot be canceled — status={status!r} is not "
            "'open' (MVP: only resting orders are cancelable)"
        )
        self.order_id = order_id
        self.status = status


def _append(ledger: Ledger, event_type: str, payload: dict[str, Any], ts: datetime) -> str:
    event = Event(
        event_id=str(ULID()),
        ts_utc=ts,
        type=event_type,  # type: ignore[arg-type]
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    return ledger.append(event)


def _latest_payload_for_thesis(
    ledger: Ledger, event_type: str, thesis_id: str
) -> dict[str, Any] | None:
    """Latest `event_type` payload for `thesis_id` — `thesis._machine.
    latest_payload` only searches the lifecycle-marker event types
    (`THESIS_EVENT_TYPES`), which does NOT cover `MarketSnapshotTaken`/
    `SizingComputed` (submit-time records, not lifecycle transitions), so
    this pipeline needs its own direct ledger read for those two, mirroring
    `policy._context`'s identically-named private helper."""
    matches = [
        event
        for event in ledger.query(EventFilter(types=[event_type]))
        if event.payload.get("thesis_id") == thesis_id
    ]
    return matches[-1].payload if matches else None


def _entry_price(contract: dict[str, Any], ledger: Ledger, thesis_id: str) -> Decimal:
    """The qty-deriving entry price per DESIGN §8.2 step 1: a limit entry's
    own `limit_price` (verbatim from `contract["entry"]`), else — for a
    market entry — the `MarketSnapshotTaken.last_close` this thesis's own
    `submit()` already recorded (the last CLOSED bar, never a fresh quote).
    This SAME price also becomes `OrderRequest.limit_price` regardless of
    `order_type` (money-path rules — R-003/R-005/R-006/R-008/R-012 —
    price the order's notional off `qty * limit_price`; a market order's
    reference price is exactly this entry_price, `PaperBroker.submit`'s
    own market-fill branch never reads `limit_price` so carrying it costs
    nothing operationally, and R-012's sizing-purity check is structurally
    unable to compare a submitted notional against the recorded
    `SizingComputed` value without it)."""
    entry = contract["entry"]
    if entry["order_type"] == "limit":
        return Decimal(str(entry["limit_price"]))
    snapshot = _latest_payload_for_thesis(ledger, "MarketSnapshotTaken", thesis_id)
    if snapshot is None:  # pragma: no cover — submit() always records this before approval
        raise ValueError(f"no MarketSnapshotTaken event found for thesis_id={thesis_id!r}")
    return Decimal(str(snapshot["last_close"]))


def _build_order_request(thesis_id: str, ledger: Ledger) -> OrderRequest:
    drafted = _thesis_machine.latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:  # pragma: no cover — require_state already proved a real thesis
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    contract = drafted["contract"]

    sizing = _latest_payload_for_thesis(ledger, "SizingComputed", thesis_id)
    if sizing is None:  # pragma: no cover — submit() always records this before approval
        raise ValueError(f"no SizingComputed event found for thesis_id={thesis_id!r}")
    recommended_size_usd = Decimal(str(sizing["sizing"]["recommended_size_usd"]))

    entry_price = _entry_price(contract, ledger, thesis_id)
    qty = recommended_size_usd / entry_price

    return OrderRequest(
        thesis_id=thesis_id,
        account_ref=str(contract["account_ref"]),
        asset=AssetRef.model_validate(contract["asset"]),
        side="buy" if contract["direction"] == "long" else "sell",
        order_type=contract["entry"]["order_type"],
        qty=qty,
        limit_price=entry_price,
    )


def _fill_event_for_order(ledger: Ledger, order_id: str) -> Event | None:
    matches = [
        event
        for event in ledger.query(EventFilter(types=["FillRecorded"]))
        if event.payload.get("order_id") == order_id
    ]
    return matches[-1] if matches else None


def execute_order(thesis_id: str) -> OrderAck:
    """DESIGN §8.2's seven-step two-phase pipeline — see the module
    docstring for the pinned step-by-step algorithm this implements
    verbatim."""
    from tradekit import broker as _broker
    from tradekit import policy as _policy

    ledger = default_ledger()

    # Step 1 — thesis-state guard + build the OrderRequest from the
    # thesis's own contract/sizing (a mechanical transcription of what was
    # already approved, never a fresh sizing decision at submit time).
    _thesis_machine.require_state(ledger, thesis_id, frozenset({"approved"}), "execute_order")
    order = _build_order_request(thesis_id, ledger)

    # Steps 2-3 — policy.evaluate() itself appends ActionProposed THEN
    # VerdictIssued; this pipeline's own contribution is calling it BEFORE
    # the broker call and never submitting on a deny verdict.
    verdict: Verdict = _policy.evaluate(
        ProposedAction(
            kind="submit_order",
            account_ref=order.account_ref,
            requested_by="system:broker-pipeline",
            thesis_id=thesis_id,
            order=order,
        )
    )
    if not verdict.allow:
        raise PipelineDenied(verdict)

    # Step 4 — mint the token FROM the just-ledgered allow Verdict and call
    # the adapter (module-attribute `broker.get`, monkeypatchable). A raise
    # from `.submit(...)` propagates uncaught — ActionProposed/VerdictIssued
    # already survive on the ledger.
    token = VerdictToken(
        verdict_id=verdict.verdict_id, policy_version_hash=verdict.policy_version_hash
    )
    adapter = _broker.get(order.account_ref)
    ack = adapter.submit(order, token)

    # Step 6 — single-poll MVP: one synchronous order_status() call, no
    # looping/blocking on a still-resting limit order.
    status = adapter.order_status(ack.order_id)
    if status.status != "filled":
        return ack

    # Step 7 — first-fill activation. The adapter (step 5) already appended
    # FillRecorded; read it back for the ts this ThesisActivated carries.
    fill_event = _fill_event_for_order(ledger, ack.order_id)
    if fill_event is None:  # pragma: no cover — adapter.submit() always records the fill first
        raise ValueError(f"no FillRecorded event found for order_id={ack.order_id!r}")
    _thesis_machine._activate_on_fill(ledger, thesis_id, ack.order_id, fill_event.ts_utc)

    # R-011's live-sequence decrement is a pure read-time derivation
    # (`policy._context`'s live-tier wiring) over the FillRecorded event the
    # adapter already appended above — nothing further to do here.
    return ack


def reconcile(account_ref: str) -> None:
    """Broker `fills()` vs this account's own `FillRecorded` ledger history
    — exact `(order_id, ts_utc, qty)` triple match (§8.2 step 7 / §15). Any
    unmatched broker fill -> `ReconciliationRun(mismatch)` + automatic
    `HaltSet`; a clean run -> `ReconciliationRun(ok)`, no halt.

    MED-3 (P3 review, CTO-pinned fix) — the REVERSE check: a `FillRecorded`
    on the ledger for this account with NO matching broker fill (same
    exact triple) is a "phantom ledger fill" — a ledger claim of a trade
    the broker's own record never confirms — and is exactly as dangerous
    as the forward mismatch (an out-of-band broker fill the ledger never
    saw): both mean the ledger and the venue disagree about reality. Any
    phantom ledger fill -> mismatch + `HaltSet`, reason names
    `phantom_ledger_fill`. A real `PaperBroker` can never produce this
    (its `fills()` derive FROM the same ledger), so this branch is only
    reachable via a fake/other `BrokerPort` adapter reporting fewer fills
    than the ledger has."""
    from tradekit import broker as _broker

    ledger = default_ledger()
    adapter = _broker.get(account_ref)

    ledger_fills = [
        event
        for event in ledger.query(EventFilter(types=["FillRecorded"]))
        if event.payload.get("account_ref") == account_ref
    ]
    ledger_keyed = [
        (
            (
                str(event.payload.get("order_id")),
                _as_utc(event.payload.get("ts_utc")),
                str(Decimal(str(event.payload.get("qty")))),
            ),
            event.payload,
        )
        for event in ledger_fills
    ]
    ledger_keys = {key for key, _payload in ledger_keyed}

    epoch = datetime.fromtimestamp(0, tz=UTC)
    broker_fills: list[Fill] = adapter.fills(since=epoch)
    broker_keys = {(fill.order_id, _as_utc(fill.ts_utc), str(fill.qty)) for fill in broker_fills}

    mismatches: list[dict[str, Any]] = []
    for fill in broker_fills:
        key = (fill.order_id, _as_utc(fill.ts_utc), str(fill.qty))
        if key not in ledger_keys:
            mismatches.append(fill.model_dump(mode="json"))

    phantom_order_ids: list[str] = []
    for key, payload in ledger_keyed:
        if key not in broker_keys:
            phantom_order_ids.append(str(payload.get("order_id")))
            mismatches.append({**payload, "kind": "phantom_ledger_fill"})

    now = _mae_runtime.clock()
    result: Literal["ok", "mismatch"] = "mismatch" if mismatches else "ok"
    run_payload = ReconciliationRunPayload(
        account_ref=account_ref,
        result=result,
        broker_fill_count=len(broker_fills),
        ledger_fill_count=len(ledger_fills),
        mismatches=mismatches,
        ts_utc=now,
    )
    _append(ledger, "ReconciliationRun", run_payload.model_dump(mode="json"), now)

    if mismatches:
        reasons = []
        broker_order_ids = sorted(
            {str(m.get("order_id")) for m in mismatches if m.get("kind") != "phantom_ledger_fill"}
        )
        if broker_order_ids:
            reasons.append(f"unmatched broker fill(s) order_id={{{', '.join(broker_order_ids)}}}")
        if phantom_order_ids:
            reasons.append(
                "phantom_ledger_fill: ledger FillRecorded with no matching broker fill "
                f"order_id={{{', '.join(sorted(set(phantom_order_ids)))}}}"
            )
        halt_payload = HaltSetPayload(
            reason=f"reconcile mismatch for account_ref={account_ref!r}: " + "; ".join(reasons),
            scope="all",
            set_by=_ACTOR,
            # SPRINT P4-PAPER batch B, addendum 2: no-auto-resume on the live
            # path, structurally — a reconcile-mismatch halt on a "live:"
            # account is marked so policy.resume() refuses it without a
            # manual confirm_live=True (Mike-manual step).
            live_path=account_ref.startswith("live:"),
        )
        _append(ledger, "HaltSet", halt_payload.model_dump(mode="json"), now)


def _as_utc(value: Any) -> str:
    """Normalize a `ts_utc` (a `datetime` off a `Fill`, or its ISO string
    round-trip off a ledgered `FillRecorded` payload) to a canonical
    comparable string for the exact-triple reconcile match key."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(UTC).isoformat()


def cancel_order(account_ref: str, order_id: str) -> None:
    """MVP: only a RESTING order (`order_status(...).status == "open"`) may
    be canceled — any other status refuses with typed `OrderNotCancelable`,
    zero events appended. A cancelable order appends `OrderCancelled`."""
    from tradekit import broker as _broker

    ledger = default_ledger()
    adapter = _broker.get(account_ref)
    status = adapter.order_status(order_id)
    if status.status != "open":
        raise OrderNotCancelable(order_id, status.status)

    now = _mae_runtime.clock()
    payload = OrderCancelledPayload(order_id=order_id, account_ref=account_ref, ts_utc=now)
    _append(ledger, "OrderCancelled", payload.model_dump(mode="json"), now)


__all__ = ["OrderNotCancelable", "PipelineDenied", "cancel_order", "execute_order", "reconcile"]
