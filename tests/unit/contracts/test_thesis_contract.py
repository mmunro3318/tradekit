"""ThesisContract + InvalidationSpec (DESIGN §5.1, §5.2; SME F1, F5; TD-3).

The spine contract: if any of these validators is loose, a bad thesis reaches
policy/broker instead of dying at authoring time.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import ThesisContract


def test_contract_is_frozen(make_thesis) -> None:
    thesis = make_thesis()
    with pytest.raises(ValidationError):
        thesis.direction = "short"
    # §5: "no in-place mutation ever" — amendments go through model_copy into a
    # superseding version. A mutable thesis breaks replay determinism (TD-4).


def test_ev_block_is_mandatory(thesis_kwargs) -> None:
    del thesis_kwargs["ev_block"]
    with pytest.raises(ValidationError):
        ThesisContract(**thesis_kwargs)
    # SME F5: a thesis without an explicit numeric EV must not validate —
    # "positive expected value" as prose is exactly the dodge F5 exists to block.


def test_ev_block_fields_must_be_numeric(make_thesis) -> None:
    with pytest.raises(ValidationError):
        make_thesis(
            ev_block={
                "p_win": "pretty likely",  # prose where a number belongs (F5)
                "reward_usd": "2.50",
                "risk_usd": "1.25",
                "ev_usd": "0.81",
            }
        )


def test_direction_restricted_to_long_short(make_thesis) -> None:
    with pytest.raises(ValidationError):
        make_thesis(direction="sideways")
    # §5.1: Literal["long","short"]. Anything else makes grading arithmetic
    # (which side of the predicate is "success"?) undefined.


def test_money_fields_are_decimal(make_thesis) -> None:
    thesis = make_thesis()
    for name in ("target_price", "stop_price", "size_usd"):
        value = getattr(thesis, name)
        assert isinstance(value, Decimal), (
            f"{name} is {type(value).__name__}: money is Decimal end-to-end (TD-3) — a "
            "float here corrupts grading anchors and P&L attribution"
        )
    assert thesis.target_price == Decimal("66000.00")
    reward = thesis.ev_block.reward_usd
    assert isinstance(reward, Decimal), (
        f"ev_block.reward_usd is {type(reward).__name__}: the *_usd EV fields are money "
        "and must be Decimal (TD-3, F5)"
    )


def test_measurable_invalidation_carries_predicate(make_thesis) -> None:
    inv = make_thesis().invalidation
    assert getattr(inv, "kind", None) == "measurable", (
        f"invalidation parsed as {inv!r}: expected the measurable variant "
        "(discriminator assumption — tests/ASSUMPTIONS.md)"
    )
    assert inv.predicate.kind == "price_close", (
        "measurable invalidation must embed a machine-checkable Predicate — it is "
        "auto-evaluated by the grader with zero discretion (§10.4 VOID guard 1)"
    )


def test_structural_invalidation_requires_description_and_attestation(make_thesis) -> None:
    thesis = make_thesis(
        invalidation={"kind": "structural", "description": "FOMC surprises hawkish"}
    )
    assert thesis.invalidation.requires_attestation is True, (
        "structural invalidation without forced attestation reopens the "
        "void-your-losers exploit — attestation + reviewer sign-off is the VOID "
        "anti-gaming guard (§5.2, §10.4)"
    )
    with pytest.raises(ValidationError):
        make_thesis(invalidation={"kind": "structural", "description": ""})
    # An empty description is an uncheckable, unauditable escape hatch.
