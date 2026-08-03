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

STRATEGIES: tuple[StrategyDef, ...] = (_S1_MOMENTUM,)


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
