"""Prop dial block + internal-wall resolution (SPRINT P5-PROP batch A;
ASSUMPTIONS 143-144). Money-path (policy layer): the venue numbers are the
OUTER truth the simulator models; R-017/R-018 enforce only the internal
walls this file pins.
"""

from __future__ import annotations

from decimal import Decimal

from tradekit.policy._dials import PolicyDials, prop_account_walls

_STARTER = {
    "prop_mdl_pct": Decimal("0.03"),
    "prop_mdd_pct": Decimal("0.06"),
    "prop_profit_target_pct": Decimal("0.10"),
    "prop_fee_side_bps": Decimal("4"),
    "prop_funding_daily_pct": Decimal("0.00033"),
    "internal_daily_soft_frac": Decimal("0.50"),
    "internal_daily_hard_frac": Decimal("0.70"),
    "internal_mdd_reserve_frac": Decimal("0.40"),
}


class TestPropDialBlock:
    def test_code_defaults_are_disabled(self) -> None:
        """TD-24 convention (entry 143): every prop slot defaults to None
        in CODE — the venue numbers ship in config.toml, not here."""
        dials = PolicyDials()
        assert dials.prop_mdl_pct is None
        assert dials.prop_mdd_pct is None
        assert dials.prop_profit_target_pct is None
        assert dials.prop_fee_side_bps is None
        assert dials.prop_funding_daily_pct is None
        assert dials.internal_daily_soft_frac is None
        assert dials.internal_daily_hard_frac is None
        assert dials.internal_mdd_reserve_frac is None

    def test_starter_values_load(self) -> None:
        dials = PolicyDials(**_STARTER)
        assert dials.prop_mdl_pct == Decimal("0.03")
        assert dials.internal_mdd_reserve_frac == Decimal("0.40")

    def test_prop_dials_participate_in_policy_version_hash(self) -> None:
        """A prop dial change must change the policy version hash — same
        property every other dial has (canonical_dump covers all fields)."""
        from tradekit.policy._dials import policy_version_hash

        base = PolicyDials()
        tuned = PolicyDials(prop_mdl_pct=Decimal("0.03"))
        rule_ids = ["R-017", "R-018"]
        assert policy_version_hash(base, rule_ids) != policy_version_hash(
            tuned, rule_ids
        )


class TestPropAccountWalls:
    def test_starter_walls(self) -> None:
        """(0.03 x 0.70, 0.06 x (1 - 0.40)) = (0.021, 0.036) — entry 144's
        one resolution point."""
        walls = prop_account_walls(PolicyDials(**_STARTER))
        assert walls == (Decimal("0.021"), Decimal("0.036"))

    def test_disabled_when_any_input_missing(self) -> None:
        """All four inputs (mdl, mdd, hard frac, reserve frac) must be set;
        otherwise walls are disabled -> None (R-017/R-018 not_configured).
        The SOFT frac is advisory (HUD), deliberately NOT required."""
        assert prop_account_walls(PolicyDials()) is None
        for missing in (
            "prop_mdl_pct",
            "prop_mdd_pct",
            "internal_daily_hard_frac",
            "internal_mdd_reserve_frac",
        ):
            partial = {k: v for k, v in _STARTER.items() if k != missing}
            assert prop_account_walls(PolicyDials(**partial)) is None, missing

    def test_soft_frac_not_required(self) -> None:
        partial = {k: v for k, v in _STARTER.items() if k != "internal_daily_soft_frac"}
        assert prop_account_walls(PolicyDials(**partial)) == (
            Decimal("0.021"),
            Decimal("0.036"),
        )
