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

from tradekit.contracts import OrderAck, Verdict


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


def execute_order(thesis_id: str) -> OrderAck:
    """STUB — SPRINT P3 batch C dev pass lands this (see module docstring
    for the pinned §8.2 seven-step algorithm)."""
    raise NotImplementedError(
        f"tradekit.broker._pipeline.execute_order({thesis_id!r}): SPRINT P3 batch C dev "
        "pass lands the two-phase pipeline (see module docstring for the pinned §8.2 "
        "step-by-step algorithm)"
    )


def reconcile(account_ref: str) -> None:
    """STUB — SPRINT P3 batch C dev pass lands this (see module docstring
    for the pinned broker-fills-vs-ledger + auto-halt algorithm)."""
    raise NotImplementedError(
        f"tradekit.broker._pipeline.reconcile({account_ref!r}): SPRINT P3 batch C dev "
        "pass lands the reconcile -> auto-halt path (see module docstring)"
    )


def cancel_order(account_ref: str, order_id: str) -> None:
    """STUB — SPRINT P3 batch C dev pass lands this (see module docstring
    for the pinned resting-only cancel semantics)."""
    raise NotImplementedError(
        f"tradekit.broker._pipeline.cancel_order({account_ref!r}, {order_id!r}): SPRINT P3 "
        "batch C dev pass lands this (see module docstring)"
    )


__all__ = ["OrderNotCancelable", "PipelineDenied", "cancel_order", "execute_order", "reconcile"]
