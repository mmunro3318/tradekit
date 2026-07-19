"""Policy dials — `config.toml` loader (DESIGN §7.2; CTO addendum "Ambient
wiring"). REAL this batch (declarative data the tests read, same status as
`_rules.py` — CTO's batch-C red/green split call): every default below is
the exact §7.2 table, transcribed, plus the CTO's three additions
(`series_epoch`, `paper_starting_equity_usd`, `n_trials_default`).

Loading: `PolicyDials.load()` reads `TK_CONFIG_PATH` (env, resolved at CALL
time — same "no module-level caching" discipline as
`tradekit.ledger.default_ledger`'s `TK_DATA_DIR`, ASSUMPTIONS/CTO addendum)
and falls back to the committed `config.toml` at the repo root. A missing
file at an explicit `TK_CONFIG_PATH` is a caller error (raises); a missing
file at the DEFAULT repo-root path just means "use the field defaults"
(green on a fresh checkout with no config.toml reachable, e.g. an installed
wheel) — `pydantic_settings.TomlConfigSettingsSource` already treats a
nonexistent toml_file that way, no extra handling needed here.

`policy_version_hash` (CTO addendum): sha256 over (sorted rule IDs +
canonical dial dump) — pure, no I/O; lives here because it only needs a
`PolicyDials` instance and a list of rule IDs (`_rules.py` supplies the
latter, avoiding a `_rules` -> `_dials` import in either direction).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# src/tradekit/policy/_dials.py -> parents[3] is the repo root.
_REPO_ROOT_CONFIG = Path(__file__).resolve().parents[3] / "config.toml"


def _config_path() -> Path:
    override = os.environ.get("TK_CONFIG_PATH")
    return Path(override) if override else _REPO_ROOT_CONFIG


class PolicyDials(BaseSettings):
    """§7.2 rules-catalog dials, one field per "Default dial" column entry,
    plus the CTO addendum's three series/promotion knobs. Field names are
    the ones `config.toml`'s flat keys map onto (`TomlConfigSettingsSource`,
    no env-var layer — this is a FILE, not process-env, settings source)."""

    model_config = SettingsConfigDict(extra="forbid")

    # R-004
    allowed_assets_live: tuple[str, ...] = (
        "BTC/USD",
        "ETH/USD",
        "AAPL",
        "MSFT",
        "SPY",
    )
    # R-005 (SPRINT P3 batch A, TD-24: percent-of-principal migration, Mike-
    # signed 2026-07-17 — was max_position_usd_live: Decimal = Decimal("25")
    # flat; 0.05 * $500 default principal = $25, so the default account's
    # live cap is numerically UNCHANGED, only its basis moved from a flat
    # dollar figure to a fraction of AccountConfig.principal_usd).
    max_position_pct_live: Decimal = Decimal("0.05")
    max_position_pct_paper: Decimal = Decimal("0.10")
    # R-006 (TD-24 migration — was max_total_live_exposure_usd = Decimal("100");
    # 0.20 * $500 = $100, default account UNCHANGED).
    max_total_live_exposure_pct: Decimal = Decimal("0.20")
    # R-007
    max_daily_trades_live: int = 3
    max_daily_trades_paper: int = 20
    # R-008 — deliberately STAYS an absolute dollar floor (CTO exception,
    # Mike-accepted, TD-24): a fee-noise floor scales with fee schedules,
    # not with account principal.
    min_notional_usd: Decimal = Decimal("10")
    # R-009
    drawdown_breaker_pct: Decimal = Decimal("0.10")
    # R-011
    live_sequence_budget: int = 3
    # R-012
    sizing_tolerance_pct: Decimal = Decimal("0.01")
    # R-013
    correlation_cap: Decimal = Decimal("0.75")
    # R-014 (TD-24 migration — was cooling_off_notional_usd = Decimal("200");
    # 0.40 * $500 = $200, default account UNCHANGED).
    cooling_off_pct: Decimal = Decimal("0.40")
    cooling_off_hours: int = 24
    # R-015
    void_rate_window: int = 20
    void_rate_cap_pct: Decimal = Decimal("0.20")
    # R-017/R-018 (SPRINT P3 batch A, TD-24) — config.toml-layer DEFAULTS for
    # the two new per-account drawdown gates. `None` here (the code default)
    # means "disabled account-wide unless an AccountConfig sets it" — the
    # three-layer resolution order is AccountConfig field -> this dial ->
    # code default, and `None` is a legitimate value at every layer (never
    # coerced to +/-Infinity, ASSUMPTIONS round-16).
    max_daily_drawdown_default: Decimal | None = None
    max_lifetime_drawdown_default: Decimal | None = None
    # TD-24: `AccountConfig.max_trades_per_day`'s config.toml-layer default
    # when a `tk account create-paper` config file omits it — 0 == "paper/
    # sim only" per Mike's sketch (no live-trade budget granted by default).
    max_trades_per_day_default: int = 0
    # Series/promotion (CTO addendum; batch D consumes these)
    series_epoch: AwareDatetime = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    paper_starting_equity_usd: Decimal = Decimal("500")
    n_trials_default: int = 1
    # Batch D addition (FLAGGED, ASSUMPTIONS): `policy.promotion_status()`'s
    # pinned signature takes NO account_ref argument (§4.2/CTO addendum), so
    # a default account must come from somewhere for the single-account P2
    # MVP (multi-account promotion ladders are a P3 concern) — this dial is
    # that default, read by `promotion_status()`/`confirm_promotion()`.
    default_account_ref: str = "paper:alpha"
    # SPRINT P3 batch D (DESIGN §12, TD-21): reviewer subprocess dials.
    # `reviewer_binary`/`reviewer_args` resolve the adapter's argv
    # (`review._adapters.SubprocessReviewerAdapter`); `reviewer_timeout_s`/
    # `reviewer_max_output_bytes` bound a single subprocess call (a chatty
    # or hung reviewer model must never crash or block the pipeline, sprint
    # doc "Traps"). `unresolved_attack_threshold` is the deterministic
    # rubric gate (DESIGN §12.1: "any unresolved attack >= severity
    # threshold blocks approval") -- compared against
    # `ReviewArtifact.unresolved_attack_count`.
    reviewer_binary: str = "codex"
    reviewer_args: tuple[str, ...] = ()
    reviewer_timeout_s: int = 120
    reviewer_max_output_bytes: int = 1_048_576
    unresolved_attack_threshold: int = 1
    # SPRINT P3 batch E (DESIGN §11, sprint-doc addendum: "tk brief token
    # budget is a hard cap"). `brief_max_tokens` bounds `memory.brief()`'s
    # rendered output under the token≈len(text)/4 heuristic PINNED by the
    # addendum (ASSUMPTIONS round-21) — truncation is whole-section,
    # lowest-salience-first, never mid-sentence. `wiki_dir` is the path seam
    # `memory.search()`/`tk wiki add` resolve front-matter files under
    # (relative to the repo root when not absolute; TK_WIKI_DIR env, if
    # ever added, would be a CLI-layer override, not a dial concern —
    # deferred, not needed this batch).
    brief_max_tokens: int = 1500
    wiki_dir: str = "docs/wiki"
    # SPRINT P4-PAPER batch A (addendum 2): fail-closed live-venue routing
    # gate. `broker.get("live:*")` requires BOTH this dial True AND the live
    # env keys (ALPACA_LIVE_KEY_ID/ALPACA_LIVE_SECRET) present before it
    # resolves to a real AlpacaBroker pointed at the live trading base URL —
    # either condition failing raises `LiveTradingDisabled` (`broker._port`).
    # Defaults False (Mike's live keys/rotation remain blocked, per the
    # sprint doc's Addendum 2 scope note: "Live keys/rotations remain
    # Mike-blocked").
    live_trading_enabled: bool = False
    # SPRINT P5-PROP batch A (ASSUMPTIONS 143): prop-account evaluation
    # dials. All `Decimal | None = None` in CODE (TD-24 convention,
    # entry 99 lineage) — disabled unless a config.toml (or explicit
    # override) sets them; the committed config.toml carries the Kraken
    # Prop Starter venue numbers (Report-1 §6/§8) for the first five, plus
    # the CTO's internal-buffer fractions (Q.H.122-123/130-131) for the
    # last three. `prop_mdl_pct`/`prop_mdd_pct`/`prop_profit_target_pct`
    # are the VENUE's own daily-loss/max-drawdown/profit-target
    # percentages; `prop_fee_side_bps`/`prop_funding_daily_pct` are the
    # simulator's per-side commission and daily funding rate. The three
    # `internal_*` fractions size OUR walls strictly inside the venue's
    # (see `prop_account_walls` below, entry 144) — `internal_daily_soft_
    # frac` is advisory/HUD only (not consumed by any R-rule this batch).
    prop_mdl_pct: Decimal | None = None
    prop_mdd_pct: Decimal | None = None
    prop_profit_target_pct: Decimal | None = None
    prop_fee_side_bps: Decimal | None = None
    prop_funding_daily_pct: Decimal | None = None
    internal_daily_soft_frac: Decimal | None = None
    internal_daily_hard_frac: Decimal | None = None
    internal_mdd_reserve_frac: Decimal | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # File-only: no env-var/dotenv/secrets layering (a stray
        # MAX_POSITION_USD_LIVE env var must never silently retune a
        # money gate) — init kwargs still win, for tests that construct
        # `PolicyDials(**overrides)` directly without a file at all.
        return (
            init_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=_config_path()),
        )

    @classmethod
    def load(cls) -> PolicyDials:
        """Construct from `TK_CONFIG_PATH` (or the repo-root `config.toml`),
        re-resolving the path on every call — never cache at import time."""
        return cls()


def canonical_dump(dials: PolicyDials) -> dict[str, Any]:
    """JSON-stable dict of every dial value (`Decimal`/`datetime` rendered
    as strings so the dump — and therefore the hash — is independent of
    Python's `Decimal`/`datetime` repr quirks across versions)."""
    dumped = dials.model_dump(mode="json")
    return dict(sorted(dumped.items()))


def policy_version_hash(dials: PolicyDials, rule_ids: list[str]) -> str:
    """sha256 over (sorted rule IDs + canonical dial dump) — CTO addendum.
    Deterministic JSON serialization (`sort_keys`, fixed separators) so the
    hash is reproducible byte-for-byte across processes and Python versions."""
    payload = {"rule_ids": sorted(rule_ids), "dials": canonical_dump(dials)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def prop_account_walls(dials: PolicyDials) -> tuple[Decimal, Decimal] | None:
    """Internal-wall resolution for `prop:*` accounts (ASSUMPTIONS 144):
    `(prop_mdl_pct * internal_daily_hard_frac,
    prop_mdd_pct * (1 - internal_mdd_reserve_frac))`, or `None` (walls
    disabled -> R-017/R-018 `not_configured`) unless all four inputs are
    set. The soft frac is deliberately NOT one of the four — it is
    advisory/HUD only (entry 144)."""
    mdl_pct = dials.prop_mdl_pct
    mdd_pct = dials.prop_mdd_pct
    daily_hard_frac = dials.internal_daily_hard_frac
    mdd_reserve_frac = dials.internal_mdd_reserve_frac
    if (
        mdl_pct is None
        or mdd_pct is None
        or daily_hard_frac is None
        or mdd_reserve_frac is None
    ):
        return None
    return (mdl_pct * daily_hard_frac, mdd_pct * (Decimal("1") - mdd_reserve_frac))


def resolve_account_dial(
    account_value: Decimal | None, dial_default: Decimal | None
) -> Decimal | None:
    """Three-layer dial resolution (TD-24, SPRINT P3 batch A): an
    `AccountConfig` field value ALWAYS wins when set; otherwise fall back to
    the `PolicyDials` value (itself already layered AccountConfig-file-absent
    -> config.toml -> code default by `PolicyDials.load()`/pydantic-settings
    above). `None` at every layer is a legitimate "disabled", never coerced
    to a sentinel — the caller (a rule's `check`) is the one that turns a
    `None` result into a `not_configured` RuleHit, not this function."""
    return account_value if account_value is not None else dial_default


__all__ = [
    "PolicyDials",
    "canonical_dump",
    "policy_version_hash",
    "prop_account_walls",
    "resolve_account_dial",
]
