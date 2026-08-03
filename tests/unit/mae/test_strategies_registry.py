"""tests for `tradekit.mae._strategies` — the strategy registry (T-MTF-3,
docs/design/MTF-SCAN.md "Strategy registry (data, not code)" section) and
S1's behavior-identical migration into it.

RED stage: `tradekit.mae._strategies` does not exist yet — every import
below fails at COLLECTION with ModuleNotFoundError/ImportError. That is
the expected red state for this whole file (same convention as
`test_scan_confluence_verb.py`'s T-MTF-2 red stage).

Seams: same house style as `test_scan_confluence_verb.py` — bars faked via
`"tradekit.mae._runtime.get_closed_bars"` (string-path monkeypatch), regime
faked via `monkeypatch.setattr(_regime, "compute_regime", ...)`, clock via
`"tradekit.mae._runtime._clock"`. No new seams.

ASSUMPTIONS ESCAPE HATCH — MTF-SCAN.md pins `StrategyDef`'s shape and
`STRATEGIES: tuple[StrategyDef, ...]` but does NOT pin: (1) S1's exact
`StrategyDef` field values verbatim, (2) the registry module's "lookup by
key" API name/shape, (3) the duplicate-key-registration error's exact
type/wording. Each is called out at its test with an `ASSUMPTION-FLAG`
comment and listed in the dispatch report for CTO adjudication before
green. Nothing here improvises a semantic silently.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import (
    STRATEGIES,
    STRATEGY_BY_KEY,
    StrategyDef,
    _regime,
    build_registry,
    scan_confluence,
    scan_markets,
)
from tradekit.mae._data.limits import TIMEFRAME_MAX_LOOKBACK_DAYS

# ASSUMPTION-FLAG 3: module home + "lookup by key" API. MTF-SCAN.md pins only
# `STRATEGIES: tuple[StrategyDef, ...]` and the module path
# `src/tradekit/mae/_strategies.py`. The mission's "Registry lookup by key;
# ... duplicate key registration -> loud error" is not itself pinned to a
# specific function/dict name. Best reading adopted here: a pure
# `build_registry(defs) -> dict[str, StrategyDef]` (independently testable
# with synthetic defs, so this doesn't touch the real STRATEGIES data) plus
# a pre-built `STRATEGY_BY_KEY` module constant for the real STRATEGIES
# tuple. CTO may rename/reshape either before green.


def _bar(ts_open: datetime, close: float, volume: float = 100.0) -> Bar:
    return Bar(
        ts_open=ts_open,
        open=Decimal(str(close)),
        high=Decimal(str(close + 0.3)),
        low=Decimal(str(close - 0.3)),
        close=Decimal(str(close)),
        volume=Decimal(str(volume)),
    )


def _series(
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    symbol: str = "BTC/USD",
    timeframe: str = "4h",
) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    vols = volumes if volumes is not None else [100.0] * len(closes)
    pairs = list(zip(closes, vols, strict=True))
    bars = [_bar(start + timedelta(hours=i), c, v) for i, (c, v) in enumerate(pairs)]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="fake-kraken")


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _permissive_regime(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Recommends every family the scanner's `_TAG_STRATEGY` mapping uses
    (momentum, breakout, mean_reversion) -- nothing gets pruned. Accepts
    ANY call convention (round-16 adjudication): scan_markets calls
    compute_regime positionally, scan_confluence by keyword -- a fake that
    pins one convention fails behavior-identical refactors."""
    return {
        "current_state": "low_vol_trend",
        "confidence": 0.9,
        "recommended_strategies": ["momentum", "breakout", "mean_reversion"],
    }


def _install_bars_by_key(
    monkeypatch, series_by_key: dict[tuple[str, str], BarSeries]
) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


# S1 fixture: today's hud `_SETUP_FILTERS` battery
# ({"macd_signal": "bullish_cross", "volume_spike": 1.5} @ 4h). MACD-bullish
# closes reuse `test_scan_markets_verb.py`'s own established derivation
# (flat base then an accelerating ramp settles a bullish MACD histogram
# cross) -- not re-derived from `_scanner` internals, just the same
# already-validated fixture shape. Volume spike stacked on the same series'
# last bar (identical derivation shape to `test_scan_confluence_verb.py`'s
# `_VOLUME_SPIKE_VOLUMES`: flat base then a 10x final bar, ratio clears any
# volume_spike threshold <= 6.0 by construction).
_S1_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_S1_VOLUMES = [100.0] * (len(_S1_MACD_BULLISH_CLOSES) - 1) + [1000.0]


# ---------------------------------------------------------------------------
# 1. StrategyDef field-set CONTRACT (MTF-SCAN.md "Strategy registry" dataclass
#    pin, widened per STRATEGY-PACK.md's `r_multiple_override` addition --
#    the mission pins this batch's registry must accommodate that shape).
# ---------------------------------------------------------------------------


def test_strategy_def_field_set_matches_pinned_shape() -> None:
    # SPEC-cadence T1 (supersedes 173.1's batch-scoped 7-field ruling):
    # StrategyDef gains an 8th field, horizon_hours, so the walk's claiming
    # def can drive the ticket/thesis horizon (docs/specs/SPEC-cadence.md
    # T1 interface pins).
    field_names = {f.name for f in dataclasses.fields(StrategyDef)}
    assert field_names == {
        "key",
        "side",
        "legs",
        "regime_families",
        "size_scale",
        "r_multiple_override",
        "tag",
        "horizon_hours",
    }


def test_strategy_def_is_frozen_immutable() -> None:
    s1 = STRATEGY_BY_KEY["s1_momentum"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s1.side = "sell"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. STRATEGIES tuple CONTRACT: type, deterministic order, key lookup.
# ---------------------------------------------------------------------------


def test_strategies_is_a_tuple_of_strategy_def() -> None:
    assert isinstance(STRATEGIES, tuple)
    assert all(isinstance(item, StrategyDef) for item in STRATEGIES)


def test_registry_lookup_by_key_returns_matching_def() -> None:
    registry = build_registry(STRATEGIES)
    assert registry["s1_momentum"] is STRATEGY_BY_KEY["s1_momentum"]
    assert registry["s1_momentum"].key == "s1_momentum"


def test_duplicate_key_registration_raises_loud_error() -> None:
    # ASSUMPTION-FLAG 4: exact exception type/message not pinned by
    # MTF-SCAN.md. Best reading: ValueError naming the offending key, same
    # TICKET-001 "loud, named" convention used throughout `_confluence.py`
    # and `_scanner.py`.
    dup_a = StrategyDef(
        key="dup_key",
        side="buy",
        legs=({"timeframe": "4h", "filters": {}, "min_tags": 0},),
        regime_families=("momentum",),
        size_scale=Decimal("1"),
        r_multiple_override=None,
        tag="dup_key",
    )
    dup_b = dataclasses.replace(dup_a, side="sell")
    with pytest.raises(ValueError, match="dup_key"):
        build_registry((dup_a, dup_b))


# ---------------------------------------------------------------------------
# 3. S1 migration: the registry's S1 def encodes today's hud setup battery
#    verbatim. ASSUMPTION-FLAG 1 (see below) on the field MTF-SCAN.md
#    doesn't pin verbatim -- derived from `hud/_build.py`'s
#    `_SETUP_FILTERS`/`_SETUP_TIMEFRAME` and the behavior-identity
#    requirement itself (see test 4 below for min_tags=1's behavior-identity
#    proof).
# ---------------------------------------------------------------------------


def test_s1_strategy_def_encodes_todays_hud_setup_battery() -> None:
    s1 = STRATEGY_BY_KEY["s1_momentum"]
    assert s1.side == "buy"  # hud/_build.py:246,554 -- S1 is buy-only today
    assert len(s1.legs) == 1
    leg = s1.legs[0]
    assert leg["timeframe"] == "4h"  # hud/_build.py:38 _SETUP_TIMEFRAME
    assert leg["filters"] == {"macd_signal": "bullish_cross", "volume_spike": 1.5}
    # min_tags=1: decision-identical to today's hud, whose arm gate already
    # requires >= 1 surviving tag (hud/_build.py:~434) before a setup ever
    # arms -- an empty-tag scan match maps to "wait" either way, so this is
    # not a behavior change. min_tags=1 also prevents an unconditional S1
    # leg from shadowing S2 under T-MTF-4's first-match-wins walk.
    # CTO re-adjudication, round 17 (ASSUMPTIONS 173).
    assert leg["min_tags"] == 1
    assert s1.size_scale == Decimal("1")
    assert s1.r_multiple_override is None
    assert s1.tag == "s1_momentum"
    # SPEC-cadence T1-AC-5: S1 default horizon_hours 168 (7d, byte-identical
    # to every pre-batch thesis per ASSUMPTIONS 175.3).
    assert s1.horizon_hours == 168
    # ASSUMPTION-FLAG 1: regime_families not pinned verbatim by MTF-SCAN.md
    # for S1. Derived from the two tags S1's filters can emit
    # (`_scanner.py`:118-123: macd_signal bullish_cross -> "macd_bullish" ->
    # momentum; volume_spike hit -> "volume_spike" -> breakout) -- the
    # families S1's own tags belong to. CTO may pin a different set (e.g.
    # requiring both families jointly recommended, which `regime_families`
    # as a flat "must be in recommended_strategies" tuple cannot express
    # without knowing the T-MTF-4 walk's exact any-vs-all semantics).
    assert set(s1.regime_families) == {"momentum", "breakout"}


def test_s1_leg_lookback_matches_pinned_4h_table_entry() -> None:
    # SEAM: the registry's leg must reference a timeframe key that resolves
    # to MTF-SCAN.md's pinned 90-day 4h lookback (docs/design/MTF-SCAN.md
    # retention table; `_data/limits.py` TIMEFRAME_MAX_LOOKBACK_DAYS) -- not
    # a restated number anywhere in the registry.
    s1 = STRATEGY_BY_KEY["s1_momentum"]
    leg = s1.legs[0]
    assert TIMEFRAME_MAX_LOOKBACK_DAYS[leg["timeframe"]] == 90


# ---------------------------------------------------------------------------
# 4. Behavior-identity: running S1's registry def through scan_confluence
#    (single-leg) yields the SAME surviving tags as today's direct
#    scan_markets call with hud's own filters, for identical faked bars.
#    BEHAVIOR (MTF-SCAN.md task-cut pin: "T-MTF-3 ... S1 migrated into it
#    (behavior-identical for S1)").
# ---------------------------------------------------------------------------


def test_s1_registry_def_through_scan_confluence_matches_direct_scan_markets(
    monkeypatch,
) -> None:
    series = _series(_S1_MACD_BULLISH_CLOSES, _S1_VOLUMES, symbol="BTC/USD", timeframe="4h")
    monkeypatch.setattr(_regime, "compute_regime", _permissive_regime)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    _install_bars_by_key(monkeypatch, {("BTC/USD", "4h"): series})
    direct_result = scan_markets(
        "crypto",
        ["4h"],
        filters={"macd_signal": "bullish_cross", "volume_spike": 1.5},
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    s1 = STRATEGY_BY_KEY["s1_momentum"]
    _install_bars_by_key(monkeypatch, {("BTC/USD", "4h"): series})
    confluence_result = scan_confluence(
        asset_class="crypto",
        legs=list(s1.legs),
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    direct_tags = next(
        m["signal_tags"] for m in direct_result["matches"] if m["symbol"] == "BTC/USD"
    )
    confluence_match = next(
        m for m in confluence_result["matches"] if m["symbol"] == "BTC/USD"
    )
    confluence_tags = confluence_match["legs"]["4h"]["signal_tags"]

    assert direct_tags  # sanity: the fixture actually produces a match
    assert set(confluence_tags) == set(direct_tags)


def test_s1_min_tags_one_matches_the_divergence_min_tags_zero_would_have_opened(
    monkeypatch,
) -> None:
    """A symbol whose bars produce NO raw filter match (flat closes, flat
    volume -- neither macd_signal bullish_cross nor volume_spike fires) must
    be absent from BOTH `scan_markets` matches AND the S1-def-through-
    `scan_confluence` matches now that `min_tags=1`. This is the exact
    divergence surface `min_tags=0` would have opened (round 17 F3/F4): with
    0, `_confluence.confluence` never checks `len(pruned_tags) < min_tags`
    against a floor above zero, so a no-signal symbol with an empty
    `signal_tags` list would still satisfy the leg and confluence would
    emit a match `scan_markets` never would (`scan_markets` requires
    `signal_tags` to be non-empty to report a match at all)."""
    flat_closes = [100.0] * 60
    flat_volumes = [100.0] * 60
    series = _series(flat_closes, flat_volumes, symbol="ETH/USD", timeframe="4h")
    monkeypatch.setattr(_regime, "compute_regime", _permissive_regime)
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 16, tzinfo=UTC))

    _install_bars_by_key(monkeypatch, {("ETH/USD", "4h"): series})
    direct_result = scan_markets(
        "crypto",
        ["4h"],
        filters={"macd_signal": "bullish_cross", "volume_spike": 1.5},
        symbols=["ETH/USD"],
        regime_gate=True,
    )

    s1 = STRATEGY_BY_KEY["s1_momentum"]
    _install_bars_by_key(monkeypatch, {("ETH/USD", "4h"): series})
    confluence_result = scan_confluence(
        asset_class="crypto",
        legs=list(s1.legs),
        symbols=["ETH/USD"],
        regime_gate=True,
    )

    assert not any(m["symbol"] == "ETH/USD" for m in direct_result["matches"])
    assert not any(m["symbol"] == "ETH/USD" for m in confluence_result["matches"])


def test_s1_leg_unknown_timeframe_rejected_loudly_via_scan_confluence(monkeypatch) -> None:
    # CONTRACT/BEHAVIOR: StrategyDef.legs are literally ScanLeg-compatible --
    # feeding a def with a bad leg straight into scan_confluence hits the
    # SAME loud-before-fetch validation scan_confluence already owns
    # (MTF-SCAN.md error map: "leg timeframe not in
    # TIMEFRAME_MAX_LOOKBACK_DAYS -> ValueError at scan_confluence entry").
    bad_def = StrategyDef(
        key="bad_tf_probe",
        side="buy",
        legs=({"timeframe": "3h", "filters": {}, "min_tags": 0},),
        regime_families=(),
        size_scale=Decimal("1"),
        r_multiple_override=None,
        tag="bad_tf_probe",
    )
    with pytest.raises(ValueError, match="3h"):
        scan_confluence(
            asset_class="crypto",
            legs=list(bad_def.legs),
            symbols=["BTC/USD"],
            regime_gate=True,
        )
