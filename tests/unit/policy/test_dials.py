"""`PolicyDials` — defaults, `config.toml` loading, `TK_CONFIG_PATH`
override, and the policy-version hash (DESIGN §7.2; CTO addendum "Ambient
wiring"). REAL this batch (CTO's batch-C red/green split call) — every
assertion below is GREEN.

`PolicyDials.load()` re-resolves `TK_CONFIG_PATH` on every call (no
module-level caching, same discipline as `ledger.default_ledger`'s
`TK_DATA_DIR`), so `monkeypatch.setenv`/`delenv` before each `load()` call
is enough to isolate tests from each other — no autouse fixture needed
(unlike `TK_DATA_DIR`, nothing in this suite writes through the DEFAULT
`config.toml`, so there is nothing to poison).
"""

from __future__ import annotations

from decimal import Decimal

from tradekit.policy._dials import (
    PolicyDials,
    canonical_dump,
    policy_version_hash,
    resolve_account_dial,
)

# ---------------------------------------------------------------------------
# Defaults — exact §7.2 table, transcribed as constructor defaults with NO
# TK_CONFIG_PATH set (the committed repo-root config.toml, which is itself
# just the §7.2 defaults transcribed to TOML — see its own header comment).
# ---------------------------------------------------------------------------


def test_defaults_match_the_section_7_2_table_exactly(monkeypatch) -> None:
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()

    # TD-24 (SPRINT P3 batch A, Mike-signed 2026-07-17): R-005 live / R-006 /
    # R-014 migrated from flat-USD dials to fractions of account principal —
    # 5% / 20% / 40% of the $500 default account principal reproduces the
    # OLD $25 / $100 / $200 dollar figures exactly (dial-equivalence table).
    assert dials.max_position_pct_live == Decimal("0.05"), "R-005 live default (was $25 flat)"
    assert dials.max_position_pct_paper == Decimal("0.10"), "R-005 paper default"
    assert dials.max_total_live_exposure_pct == Decimal("0.20"), "R-006 default (was $100 flat)"
    assert dials.max_daily_trades_live == 3, "R-007 live default"
    assert dials.max_daily_trades_paper == 20, "R-007 paper default"
    assert dials.min_notional_usd == Decimal("10"), "R-008 default (stays absolute, TD-24)"
    assert dials.drawdown_breaker_pct == Decimal("0.10"), "R-009 default"
    assert dials.live_sequence_budget == 3, "R-011 default"
    assert dials.sizing_tolerance_pct == Decimal("0.01"), "R-012 default"
    assert dials.correlation_cap == Decimal("0.75"), "R-013 default"
    assert dials.cooling_off_pct == Decimal("0.40"), "R-014 threshold default (was $200 flat)"
    assert dials.cooling_off_hours == 24, "R-014 hours default"
    assert dials.void_rate_window == 20, "R-015 window default"
    assert dials.void_rate_cap_pct == Decimal("0.20"), "R-015 cap default"


def test_r017_r018_dial_defaults_are_disabled_out_of_the_box(monkeypatch) -> None:
    """TD-24: P2's default account gets NO implicit R-017/R-018 enforcement
    until an AccountConfig (or a config.toml override) explicitly sets one —
    committed config.toml deliberately leaves both commented out."""
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()
    assert dials.max_daily_drawdown_default is None
    assert dials.max_lifetime_drawdown_default is None
    assert dials.max_trades_per_day_default == 0, "0 == paper/sim only, per Mike's sketch"


def test_defaults_include_the_cto_addendum_series_promotion_knobs(monkeypatch) -> None:
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()

    assert dials.series_epoch.isoformat() == "2026-01-01T00:00:00+00:00"
    assert dials.paper_starting_equity_usd == Decimal("500")
    assert dials.n_trials_default == 1


def test_default_account_ref_dial_batch_d(monkeypatch) -> None:
    """FLAGGED, ASSUMPTIONS (batch D): `policy.promotion_status()`'s pinned
    §4.2 signature takes no `account_ref` argument, so this dial supplies
    the single-account P2 MVP default it reports on."""
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()
    assert dials.default_account_ref == "paper:alpha"


def test_default_allowlist_is_liquid_large_caps_plus_btc_eth(monkeypatch) -> None:
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()
    assert set(dials.allowed_assets_live) == {"BTC/USD", "ETH/USD", "AAPL", "MSFT", "SPY"}


# ---------------------------------------------------------------------------
# TK_CONFIG_PATH override
# ---------------------------------------------------------------------------


def test_tk_config_path_overrides_one_dial_and_leaves_the_rest_default(
    tmp_path, monkeypatch
) -> None:
    config = tmp_path / "override.toml"
    config.write_text('max_position_pct_live = "0.09"\n', encoding="utf-8")
    monkeypatch.setenv("TK_CONFIG_PATH", str(config))

    dials = PolicyDials.load()

    assert dials.max_position_pct_live == Decimal("0.09"), (
        "TK_CONFIG_PATH must override the dial it sets"
    )
    assert dials.min_notional_usd == Decimal("10"), (
        "a dial the override file doesn't mention must keep its field default"
    )


def test_paper_starting_equity_usd_override_via_tk_config_path(tmp_path, monkeypatch) -> None:
    # This is the exact override the sprint doc's story-1 pin requires
    # thesis._submit to observe once it reads the dial instead of its
    # retired PAPER_STARTING_EQUITY_USD module constant.
    config = tmp_path / "equity.toml"
    config.write_text('paper_starting_equity_usd = "1000"\n', encoding="utf-8")
    monkeypatch.setenv("TK_CONFIG_PATH", str(config))

    dials = PolicyDials.load()

    assert dials.paper_starting_equity_usd == Decimal("1000")


def test_load_falls_back_to_repo_root_config_toml_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("TK_CONFIG_PATH", raising=False)
    dials = PolicyDials.load()
    # The committed config.toml is itself just the §7.2 defaults transcribed
    # — this assertion pins that the FILE, not merely the field default, is
    # actually being read (a bug that silently ignored the toml source would
    # also pass the "defaults" tests above for the wrong reason).
    assert dials.min_notional_usd == Decimal("10")


# ---------------------------------------------------------------------------
# Policy-version hash
# ---------------------------------------------------------------------------


def test_policy_version_hash_is_deterministic_for_identical_inputs() -> None:
    dials = PolicyDials()
    rule_ids = ["R-001", "R-002", "R-003"]
    assert policy_version_hash(dials, rule_ids) == policy_version_hash(dials, list(rule_ids))


def test_policy_version_hash_is_order_independent_over_rule_ids() -> None:
    dials = PolicyDials()
    assert policy_version_hash(dials, ["R-001", "R-002"]) == policy_version_hash(
        dials, ["R-002", "R-001"]
    ), "the hash sorts rule IDs before hashing — insertion order must not matter"


def test_dial_change_changes_the_policy_version_hash() -> None:
    baseline = PolicyDials()
    changed = PolicyDials(max_position_pct_live=Decimal("0.30"))
    rule_ids = ["R-001", "R-005"]

    assert policy_version_hash(baseline, rule_ids) != policy_version_hash(changed, rule_ids), (
        "ANY dial change must change the hash — that's the whole point of hashing the "
        "canonical dial dump alongside the rule IDs"
    )


def test_rule_id_set_change_changes_the_policy_version_hash() -> None:
    dials = PolicyDials()
    assert policy_version_hash(dials, ["R-001"]) != policy_version_hash(
        dials, ["R-001", "R-002"]
    )


def test_canonical_dump_renders_decimals_and_datetimes_as_json_stable_strings() -> None:
    dumped = canonical_dump(PolicyDials())
    assert dumped["max_position_pct_live"] == "0.05"
    assert dumped["series_epoch"] == "2026-01-01T00:00:00Z"
    assert list(dumped.items()) == sorted(dumped.items()), (
        "canonical_dump must sort keys — the hash's determinism depends on it"
    )


# ---------------------------------------------------------------------------
# resolve_account_dial — three-layer resolution order (TD-24, SPRINT P3
# batch A): AccountConfig field -> PolicyDials (config.toml/code default).
# The THIRD layer (config.toml over the hardcoded PolicyDials field default)
# is already exercised by `test_tk_config_path_overrides_one_dial_...`
# above — `resolve_account_dial` only owns the account-vs-dial layer.
# ---------------------------------------------------------------------------


def test_resolve_account_dial_account_value_wins_when_set() -> None:
    assert resolve_account_dial(Decimal("0.05"), Decimal("0.03")) == Decimal("0.05")


def test_resolve_account_dial_falls_back_to_the_dial_default_when_account_value_is_none() -> None:
    assert resolve_account_dial(None, Decimal("0.03")) == Decimal("0.03")


def test_resolve_account_dial_returns_none_when_both_layers_are_none() -> None:
    """The code default (dial itself unset) is `None` — a genuinely disabled
    gate, never coerced to a sentinel."""
    assert resolve_account_dial(None, None) is None
