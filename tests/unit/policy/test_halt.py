"""`policy.halt`/`policy.resume` + R-001's read of unresolved `HaltSet`
(DESIGN §7.2, R-001; CTO addendum). RED this batch — `policy.halt`,
`policy.resume`, and `policy.evaluate` are unconditional `NotImplementedError`
stubs (CTO's batch-C red/green split call); every assertion below describes
the REAL expected behavior, not wrapped in `pytest.raises` (same red-phase
discipline as `test_evaluate.py`/P2 batch A's `test_lifecycle.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradekit import policy
from tradekit.contracts import EventFilter, OrderRequest, ProposedAction
from tradekit.ledger import default_ledger

NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def _mutating_action() -> ProposedAction:
    order = OrderRequest(
        thesis_id="TH-1",
        account_ref="paper:alpha",
        asset={
            "symbol": "BTC/USD",
            "venue": "kraken",
            "asset_class": "crypto",
            "tick_size": "0.01",
        },
        side="buy",
        order_type="limit",
        qty=Decimal("1"),
        limit_price=Decimal("10.00"),
    )
    return ProposedAction(
        kind="submit_order",
        account_ref="paper:alpha",
        requested_by="agent:test",
        thesis_id="TH-1",
        order=order,
    )


def test_halt_appends_halt_set_with_the_given_reason() -> None:
    policy.halt("reconciliation mismatch")
    events = default_ledger().query(EventFilter(types=["HaltSet"]))
    assert len(events) == 1
    assert events[0].payload["reason"] == "reconciliation mismatch"


def test_resume_appends_halt_cleared() -> None:
    policy.halt("reconciliation mismatch")
    policy.resume()
    events = default_ledger().query(EventFilter(types=["HaltCleared"]))
    assert len(events) == 1


def test_r001_denies_a_mutating_action_while_halted() -> None:
    policy.halt("reconciliation mismatch")
    verdict = policy.evaluate(_mutating_action())
    assert verdict.allow is False
    assert any(hit.rule_id == "R-001" and hit.outcome == "fail" for hit in verdict.rule_hits)


def test_resume_clears_the_halt_so_evaluate_no_longer_denies_via_r001() -> None:
    policy.halt("reconciliation mismatch")
    policy.resume()
    verdict = policy.evaluate(_mutating_action())
    assert all(
        not (hit.rule_id == "R-001" and hit.outcome == "fail") for hit in verdict.rule_hits
    ), "resume() must clear the halt — R-001 must not still be denying afterward"
