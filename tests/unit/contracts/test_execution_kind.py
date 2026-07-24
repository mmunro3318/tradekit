"""SPRINT-AUDIT-BUNDLE P2/A1 (audit H3): `ProposedAction.kind` closes to
`Literal["submit_order", "cancel", "promote", "void"]` == `_rules._MUTATING`
(policy/_rules.py:404). Per CTO adjudication A1: this Literal makes the
previously-unenforced invariant "every representable kind has >=1 applicable
rule" true BY CONSTRUCTION (no runtime guard added in `evaluate_pure` — canon
D3 rule 6, define errors out of existence). ASSUMPTIONS 165.

RED phase: `ProposedActionKind` does not exist yet in `contracts._execution`
(kind is still a bare `str`) — every test below fails today, either because
constructing with an invalid kind does NOT raise (contract not yet closed) or
because `ProposedActionKind`/its invariant is not yet importable. Tests
reference the target symbol via `getattr`/module access inside the test body
(never a bare top-level `from ... import ProposedActionKind`) so a missing
symbol fails the individual test, not collection of the whole file.
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from tradekit import contracts
from tradekit.contracts import OrderRequest, ProposedAction
from tradekit.policy import _rules


def _order() -> OrderRequest:
    return OrderRequest(
        thesis_id="TH-1",
        account_ref="paper:alpha",
        asset={
            "symbol": "BTC/USD",
            "venue": "kraken",
            "asset_class": "crypto",
            "tick_size": "0.01",
        },  # type: ignore[arg-type]
        side="buy",
        order_type="limit",
        qty=Decimal("1"),
        limit_price=Decimal("10.00"),
    )


def test_proposed_action_rejects_unrepresentable_kind() -> None:
    """CONTRACT: `kind="garbage"` must raise pydantic ValidationError once
    `kind` is the closed Literal (P2). Today `kind: str` accepts anything —
    this currently fails because NO exception is raised."""
    with pytest.raises(ValidationError):
        ProposedAction(
            kind="garbage",
            account_ref="paper:alpha",
            requested_by="agent:test",
            thesis_id="TH-1",
            order=_order(),
        )


def test_every_legal_kind_constructs() -> None:
    """CONTRACT: every member of `("submit_order", "cancel", "promote",
    "void")` constructs a valid `ProposedAction` — the closed Literal must
    not be narrower than `_MUTATING`."""
    for kind in ("submit_order", "cancel", "promote", "void"):
        action = ProposedAction(
            kind=kind,
            account_ref="paper:alpha",
            requested_by="agent:test",
            thesis_id="TH-1",
            order=_order(),
        )
        assert action.kind == kind


def test_every_representable_kind_has_at_least_one_applicable_rule() -> None:
    """INVARIANT (ASSUMPTIONS 165): for every kind in
    `get_args(ProposedActionKind)`, at least one rule in `policy._rules.RULES`
    names it in `applies_to`. This is the test that kills the `all([]) ==
    True` vacuous-allow by construction — once `kind` is closed, NO
    representable kind can escape every rule's `applies_to`.

    RED: `ProposedActionKind` does not exist in `_execution` yet ->
    AttributeError inside this test (not a collection-time failure)."""
    kind_values = get_args(contracts.ProposedActionKind)
    assert kind_values, "ProposedActionKind must be a non-empty closed Literal"
    for kind in kind_values:
        assert any(kind in rule.applies_to for rule in _rules.RULES), (
            f"kind {kind!r} is representable but no rule applies to it — "
            "vacuous-allow hole"
        )


def test_mutating_equals_kind_literal_args() -> None:
    """BEHAVIOR: `_rules._MUTATING` is derived from
    `get_args(ProposedActionKind)` — one source of truth, not a hand-
    maintained duplicate frozenset that can drift from the contract."""
    kind_values = frozenset(get_args(contracts.ProposedActionKind))
    assert _rules._MUTATING == kind_values
