"""Strategy registry — data, not code (T-MTF-3, docs/design/MTF-SCAN.md
"Strategy registry" section). `StrategyDef` pins the STRATEGY-PACK.md
7-field shape (widened with `r_multiple_override`); `STRATEGIES` is the
priority-ordered tuple of real definitions; `build_registry` is the pure
lookup-by-key constructor (independently testable with synthetic defs);
`STRATEGY_BY_KEY` is the pre-built lookup for the real `STRATEGIES`.

S1 (`s1_momentum`) is today's hud `_SETUP_TIMEFRAME`/`_SETUP_FILTERS`
battery (hud/_build.py:38,133-161,246,554) migrated behavior-identical —
see tests/unit/mae/test_strategies_registry.py for the CTO-adjudicated
field values (ASSUMPTIONS 173: `min_tags=1`, CTO re-adjudication, round
17 — decision-identical to today's hud, whose arm gate already requires
>= 1 surviving tag (hud/_build.py:~434) before a setup ever arms; an
empty-tag scan match maps to "wait" either way. `min_tags=1` also
prevents an unconditional S1 leg from shadowing S2 under T-MTF-4's
first-match-wins walk (review round 17 F3))."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from tradekit.mae._confluence import ScanLeg


@dataclass(frozen=True)
class StrategyDef:
    key: str
    side: Literal["buy", "sell"]
    legs: tuple[ScanLeg, ...]
    regime_families: tuple[str, ...]
    size_scale: Decimal
    r_multiple_override: Decimal | None
    tag: str
    # SPEC-cadence T1 (supersedes ASSUMPTIONS 173.1's batch-scoped 7-field
    # ruling): the walk's claiming def drives the ticket/thesis horizon.
    # 168h (7d) default matches every pre-batch thesis; S4 overrides to 48h
    # (its time-stop restriction, STRATEGY-PACK.md "restricted reversion").
    horizon_hours: int = 168


_S1_MOMENTUM = StrategyDef(
    key="s1_momentum",
    side="buy",
    legs=(
        {
            "timeframe": "4h",
            "filters": {"macd_signal": "bullish_cross", "volume_spike": 1.5},
            "min_tags": 1,
        },
    ),
    regime_families=("momentum", "breakout"),
    size_scale=Decimal("1"),
    r_multiple_override=None,
    tag="s1_momentum",
)

_S2_PULLBACK = StrategyDef(
    key="s2_pullback",
    side="buy",
    legs=(
        {
            "timeframe": "4h",
            "filters": {"ema_above": 50, "macd_signal": "bullish_cross"},
            "min_tags": 2,
        },
        {
            "timeframe": "1h",
            "filters": {"rsi_band": [35, 50]},
            "min_tags": 1,
        },
    ),
    regime_families=("momentum", "breakout"),
    size_scale=Decimal("1"),
    r_multiple_override=None,
    tag="s2_pullback",
)

_S4_REVERSION = StrategyDef(
    key="s4_reversion",
    side="buy",
    legs=(
        {
            "timeframe": "1h",
            # ASSUMPTION-FLAG S4-1 (CTO ratified, ASSUMPTIONS 174.4
            # precedent): "below_lower" is the filter VALUE; "at_support"
            # (STRATEGY-PACK.md's sample) is the TAG that value produces
            # (_scanner._BB_POSITION_TAGS) — same typo class as S2's
            # "bullish".
            "filters": {"rsi_max": 25, "bb_position": "below_lower"},
            "min_tags": 2,
        },
    ),
    regime_families=("mean_reversion",),
    # Restricted sizing/target is the "restricted" in "restricted
    # reversion" (STRATEGY-PACK.md S4): half size, target the mean (1R)
    # rather than a trend — both permanent, load-bearing restrictions.
    size_scale=Decimal("0.5"),
    r_multiple_override=Decimal("1"),
    tag="s4_reversion",
    horizon_hours=48,
)

STRATEGIES: tuple[StrategyDef, ...] = (_S1_MOMENTUM, _S2_PULLBACK, _S4_REVERSION)


def build_registry(defs: tuple[StrategyDef, ...]) -> dict[str, StrategyDef]:
    """Key-lookup dict from `defs`. Loud (`ValueError` naming the key) on a
    duplicate key — TICKET-001 convention, same as `_confluence.py`."""
    registry: dict[str, StrategyDef] = {}
    for strategy_def in defs:
        if strategy_def.key in registry:
            raise ValueError(
                f"build_registry: duplicate strategy key {strategy_def.key!r}"
            )
        registry[strategy_def.key] = strategy_def
    return registry


STRATEGY_BY_KEY: dict[str, StrategyDef] = build_registry(STRATEGIES)
