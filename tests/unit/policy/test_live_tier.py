"""Live-tier context wiring (DESIGN §7.1/§7.3; SPRINT P3 batch C,
ASSUMPTIONS round-18 — ends the P2 fail-closed carve-out, ASSUMPTIONS 92).

Status: RED this batch. `policy._context._account_tier`/`assemble()`'s
`live_trades_remaining` derivation still return `None` UNCONDITIONALLY for
every `"live:"` account_ref (the P2 carve-out, see `_context.py`'s
RED-PHASE PIN docstrings on both) — every assertion below describes the
REAL behavior the dev pass implements next: `account_tier` resolves `"T2"`
for a CONFIRMED (and not-since-demoted) live account_ref, and
`live_trades_remaining` derives PURELY (no new event type, ASSUMPTIONS
round-18) as `PromotionConfirmed.live_sequence_remaining` minus the count
of this account's own `FillRecorded` events at/after that
`PromotionConfirmed`'s `ts_utc`. The fail-closed default (`None`) remains
for an UNCONFIRMED `"live:"` account_ref — that branch is NOT changing and
is asserted here as a still-passing regression guard, not a red case.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ulid import ULID

from tradekit.contracts import Event, ProposedAction
from tradekit.ledger import default_ledger
from tradekit.policy import _context
from tradekit.policy._dials import PolicyDials

_T0 = datetime(2026, 4, 1, tzinfo=UTC)


def _append(event_type: str, payload: dict, ts: datetime = _T0) -> None:
    default_ledger().append(
        Event(
            event_id=str(ULID()),
            ts_utc=ts,
            type=event_type,  # type: ignore[arg-type]
            actor="system:test-harness",
            run_id=None,
            schema_ver=1,
            payload=payload,
        )
    )


def _confirm_promotion(account_ref: str, ts: datetime = _T0, remaining: int = 3) -> None:
    _append(
        "PromotionConfirmed",
        {
            "account_ref": account_ref,
            "to_tier": "T2",
            "granted_event_id": "grant-1",
            "live_sequence_remaining": remaining,
            "confirmed_by": "mike",
        },
        ts=ts,
    )


def _fill(account_ref: str, order_id: str, ts: datetime) -> None:
    _append(
        "FillRecorded",
        {
            "order_id": order_id,
            "thesis_id": f"TH-{order_id}",
            "account_ref": account_ref,
            "ts_utc": ts.isoformat(),
            "price": "100.00",
            "qty": "0.01",
            "fees_usd": "0.05",
            "side": "buy",
            "quote_snapshot": {},
            "symbol": "BTC/USD",
        },
        ts=ts,
    )


def _action(account_ref: str, kind: str = "submit_order") -> ProposedAction:
    return ProposedAction(kind=kind, account_ref=account_ref, requested_by="agent:test")


# ---------------------------------------------------------------------------
# account_tier — confirmed vs unconfirmed vs demoted.
# ---------------------------------------------------------------------------


def test_account_tier_resolves_t2_for_a_confirmed_live_account() -> None:
    account_ref = "live:confirmed-1"
    _confirm_promotion(account_ref)

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.account_tier == "T2"


def test_account_tier_stays_none_for_an_unconfirmed_live_account_fail_closed() -> None:
    """Regression guard, NOT a red case — this branch is unchanged by batch
    C (ASSUMPTIONS round-18: "the fail-closed default remains for
    unconfirmed accounts")."""
    account_ref = "live:never-confirmed"

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.account_tier is None


def test_account_tier_reverts_to_t1_after_a_later_demoted_event() -> None:
    account_ref = "live:demoted-1"
    _confirm_promotion(account_ref, ts=_T0)
    _append(
        "Demoted",
        {
            "account_ref": account_ref,
            "from_tier": "T2",
            "to_tier": "T1",
            "trigger": "gate_violation",
            "detail": "R-009 (evt-1)",
        },
        ts=_T0 + timedelta(hours=1),
    )

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.account_tier != "T2"


# ---------------------------------------------------------------------------
# live_trades_remaining — pure derivation, no new event type.
# ---------------------------------------------------------------------------


def test_live_trades_remaining_starts_at_the_confirmed_budget_with_no_fills_yet() -> None:
    account_ref = "live:budget-fresh"
    _confirm_promotion(account_ref, remaining=3)

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.live_trades_remaining == 3


def test_live_trades_remaining_decrements_one_per_fill_since_confirmation() -> None:
    account_ref = "live:budget-decrement"
    _confirm_promotion(account_ref, ts=_T0, remaining=3)
    _fill(account_ref, "O-1", _T0 + timedelta(hours=1))

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.live_trades_remaining == 2


def test_live_trades_remaining_ignores_fills_before_confirmation() -> None:
    """A fill timestamped BEFORE this account's `PromotionConfirmed` (e.g. a
    stale/replayed event from a prior confirmation cycle) must not count
    against the current budget."""
    account_ref = "live:budget-pre-confirmation-fill"
    _fill(account_ref, "O-stale", _T0 - timedelta(days=1))
    _confirm_promotion(account_ref, ts=_T0, remaining=3)

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.live_trades_remaining == 3


def test_live_trades_remaining_reaches_zero_after_three_fills_and_denies_the_fourth() -> None:
    """The R-011 boundary, ASSUMPTIONS round-18: 3 fills -> 0 remaining ->
    a 4th is denied. Exercised at the context + rule level (not through the
    full `broker.execute_order` pipeline — see
    `tests/unit/broker/test_pipeline.py::
    test_execute_order_r011_denies_the_fourth_live_trade_after_three_confirmed_fills`
    for the end-to-end version)."""
    from tradekit.policy._rules import _check_r011

    account_ref = "live:budget-boundary"
    _confirm_promotion(account_ref, ts=_T0, remaining=3)
    for i, hours in enumerate((1, 2, 3), start=1):
        _fill(account_ref, f"O-{i}", _T0 + timedelta(hours=hours))

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.live_trades_remaining == 0

    hit = _check_r011(_action(account_ref), ctx)
    assert hit.outcome == "fail"


def test_live_trades_remaining_is_none_for_an_unconfirmed_live_account() -> None:
    """No `PromotionConfirmed` on record -> `live_trades_remaining` stays
    `None` (insufficient_context), never a fabricated budget — same
    anti-permissive discipline as every other `PolicyContext` field."""
    account_ref = "live:never-confirmed-budget"

    ctx = _context.assemble(_action(account_ref), PolicyDials())
    assert ctx.live_trades_remaining is None
