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
    # R-005
    max_position_usd_live: Decimal = Decimal("25")
    max_position_pct_paper: Decimal = Decimal("0.10")
    # R-006
    max_total_live_exposure_usd: Decimal = Decimal("100")
    # R-007
    max_daily_trades_live: int = 3
    max_daily_trades_paper: int = 20
    # R-008
    min_notional_usd: Decimal = Decimal("10")
    # R-009
    drawdown_breaker_pct: Decimal = Decimal("0.10")
    # R-011
    live_sequence_budget: int = 3
    # R-012
    sizing_tolerance_pct: Decimal = Decimal("0.01")
    # R-013
    correlation_cap: Decimal = Decimal("0.75")
    # R-014
    cooling_off_notional_usd: Decimal = Decimal("200")
    cooling_off_hours: int = 24
    # R-015
    void_rate_window: int = 20
    void_rate_cap_pct: Decimal = Decimal("0.20")
    # Series/promotion (CTO addendum; batch D consumes these)
    series_epoch: AwareDatetime = datetime.fromisoformat("2026-01-01T00:00:00+00:00")
    paper_starting_equity_usd: Decimal = Decimal("500")
    n_trials_default: int = 1

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


__all__ = ["PolicyDials", "canonical_dump", "policy_version_hash"]
