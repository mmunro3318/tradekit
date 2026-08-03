"""tests for STRATEGY-PACK S4 (`s4_reversion`) — the downside-extreme
restricted-reversion strategy, LAST batch of the sprint (S3 deferred)
(docs/design/STRATEGY-PACK.md "S4 — Downside-extreme reversion";
tests/ASSUMPTIONS.md 172-174 govern the shared `scan_confluence`/registry
semantics this batch builds on, same house style as
`test_s2_pullback_strategy.py`, which this file mirrors).

RED stage: `s4_reversion` does not exist in `_strategies.STRATEGIES` yet
(`STRATEGY_BY_KEY["s4_reversion"]` raises `KeyError`) — every test that
looks it up fails for that reason. `rsi_max`/`bb_position` are pre-existing,
already-wired production filters (unlike S2's brand-new `ema_above`/
`rsi_band`), so the end-to-end/regime tests below exercise REAL, currently
correct scanner code through a leg dict built by hand (not yet through the
registry) to prove the fixture — then via `STRATEGY_BY_KEY["s4_reversion"]`
to prove the registration, which is what's actually red.

=== DOC-VS-DISPATCH TENSION (flag, not improvised): bb_position "at_support" ===
STRATEGY-PACK.md's S4 code sample (line ~117) writes
`"bb_position": "at_support"`. `"at_support"` is NOT a member of the closed
`bb_position` vocabulary (`_vocab.BBPosition` / `_scanner._BB_ALLOWED` =
`{"below_lower", "above_upper", "inside"}`) — passing it through
`scan_confluence` raises `ValueError` at the closed-vocabulary gate, same as
S2's now-ratified "bullish"/"bullish_cross" typo (ASSUMPTIONS 174.4).
Textual proof this is the SAME typo class, not new vocabulary the doc is
defining: `_scanner.py`'s own "Signal tag / strategy-family mapping" table
(module docstring, `_BB_POSITION_TAGS`) already reads
`bb_position below_lower -> "at_support" -> mean_reversion` — "at_support"
is the existing TAG a `"below_lower"` filter hit emits, not a filter value.
The doc's S4 sample has conflated the resulting tag name with the input
filter value it names in its own leg dict. Pin adopted here (ASSUMPTION-FLAG
S4-1): the correct filter value is `"below_lower"` (the existing
oversold-side value; "at_support" is what a passing `below_lower` leg tags
the match with, verified below). CTO ratification needed before green if a
literal new `"at_support"` filter value is intended instead.

=== ASSUMPTIONS ESCAPE HATCH ===
ASSUMPTION-FLAG S4-2 (horizon_hours / S4-to-thesis wiring, deferred): the
dispatch pins `ThesisContract` gaining a `horizon_hours: int = 168` field
(covered in `tests/unit/contracts/test_thesis_horizon_hours.py`, this
batch), but no production code path today constructs a `ThesisContract`
FROM a `StrategyDef` at all — `hud/_serve.py:_build_minimal_contract` is the
only draft-building function found, and it hardcodes
`strategy_tag="hud-ack-manual"` and `horizon_end = now + timedelta(days=7)`
with zero reference to `_strategies.STRATEGY_BY_KEY` or any `StrategyDef`.
That wiring (an S4-recommended scan match producing a thesis draft whose
`horizon_hours` is `s4.horizon_hours` if such a field even existed on
`StrategyDef`, and whose `horizon_end` is `captured_at + horizon_hours`)
does not exist as a code path, so no test is written against it here per
the mission's explicit instruction not to invent tests against nonexistent
wiring — this is scope for a future T-MTF-4/cadence batch, not this one.
Consequently `StrategyDef` stays the pinned 7-field shape (no
`horizon_hours` field added to it this batch); `horizon_hours` lives ONLY
on `ThesisContract` per the dispatch's PINNED block.

UPDATE (SPEC-cadence T1, supersedes S4-2 above): the deferred wiring has
now landed its spec. `StrategyDef` gains `horizon_hours: int = 168` (S4
sets 48) and `hud/_serve.py`'s contract builder becomes strategy-aware
(docs/specs/SPEC-cadence.md T1 interface pins) -- `test_s4_strategy_def_
field_for_field_pin` below is extended with the `horizon_hours == 48`
assertion; the field-set re-pin itself lives in
`test_strategies_registry.py` per that file's own 173.1-superseding
comment.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import strategies
from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import STRATEGIES, STRATEGY_BY_KEY, build_registry, scan_confluence
from tradekit.mae._vocab import BBPosition


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
    timeframe: str = "1h",
) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    vols = volumes if volumes is not None else [100.0] * len(closes)
    pairs = list(zip(closes, vols, strict=True))
    bars = [_bar(start + timedelta(hours=i), c, v) for i, (c, v) in enumerate(pairs)]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe=timeframe, bars=bars, source="fake-kraken")


def _install_fixed_clock(monkeypatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _install_bars_by_key(
    monkeypatch, series_by_key: dict[tuple[str, str], BarSeries]
) -> list[tuple[str, str, int]]:
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


def _restrictive_regime(*_args: object, **_kwargs: object) -> dict[str, object]:
    """Recommends ONLY momentum -- neither of S4's tags (oversold,
    at_support, both mean_reversion-family) survives. Accepts ANY call
    convention (round-16/17 established precedent, same as
    `test_strategies_registry.py`'s `_permissive_regime`) -- scan_confluence
    calls compute_regime by keyword; a fake pinning one convention would
    fail a behavior-preserving refactor."""
    return {
        "current_state": "trending",
        "confidence": 0.8,
        "recommended_strategies": ["momentum"],
    }


def _mean_reversion_regime(*_args: object, **_kwargs: object) -> dict[str, object]:
    """Recommends mean_reversion (and nothing else) -- both of S4's tags
    survive the gate; the OPPOSITE-of-restrictive case, proving the gate is
    not just "always drops everything"."""
    return {
        "current_state": "chop",
        "confidence": 0.7,
        "recommended_strategies": ["mean_reversion"],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# RSI-oversold-only fixture (reused verbatim from the established
# test_scan_confluence_verb.py / test_scan_markets_verb.py derivation): pure
# descending run -> avg_gain == 0.0 -> RSI(14) == 0.0 (well under rsi_max=25).
# Independently checked during fixture authoring (uv run python, momentum.rsi
# / volatility.bollinger as an ORACLE, not as the code under test -- this is
# a BEHAVIOR/CONTRACT fixture, not a GOLDEN numeric assertion): last
# bollinger position for this series is "inside" (close=101.0, lower band
# ~=98.97, upper ~=122.03; 110.5 is the band MEAN) -- i.e. the RSI condition fires ALONE, the
# bb_position condition does NOT -- the outright-failure "(0/2 tags)" case
# per ASSUMPTIONS 172.1 AND-kill semantics (round-19 adjudication).
_RSI_OVERSOLD_ONLY_CLOSES = [120.0 - i for i in range(20)]

# Both-conditions-fire fixture: 24 bars of seeded small noise (SAME seed and
# base shape as the established `_BB_BELOW_LOWER_CLOSES` fixture in
# test_scan_markets_verb.py, so the "noise settles near 100 the bands don't
# gap-jump" derivation is already validated precedent) followed by a sharp
# drop to 70.0 (deeper than that fixture's 80.0, chosen so BOTH rsi_max=25
# AND bb_position=below_lower fire from the SAME series -- S4's leg needs
# both conditions on one 1h series, unlike S2's two-timeframe legs).
# Independently checked during fixture authoring (uv run python, momentum.rsi
# / volatility.bollinger as an ORACLE): last RSI(14) = 7.052678445289089
# (<= 25 -> "oversold" fires), last close 70.0 < lower band 85.41429... ->
# "below_lower" -> "at_support" fires. Both tags present -> 2/2 >= min_tags.
def _s4_both_fire_closes() -> list[float]:
    import random

    rng = random.Random(20260716)
    return [100.0 + rng.uniform(-0.5, 0.5) for _ in range(24)] + [70.0]


_S4_BOTH_FIRE_CLOSES = _s4_both_fire_closes()

_S4_LEG_FILTERS = {"rsi_max": 25, "bb_position": "below_lower"}


# ---------------------------------------------------------------------------
# 1. S4 registry def: field-for-field CONTRACT pin.
# ---------------------------------------------------------------------------


def test_s4_strategy_def_field_for_field_pin() -> None:
    s4 = STRATEGY_BY_KEY["s4_reversion"]
    assert s4.key == "s4_reversion"
    assert s4.side == "buy"
    assert len(s4.legs) == 1

    leg = s4.legs[0]
    assert leg["timeframe"] == "1h"
    # ASSUMPTION-FLAG S4-1 (module docstring): "below_lower", not the doc
    # sample's "at_support" (invalid filter value / typo for the tag it
    # produces).
    assert leg["filters"] == {"rsi_max": 25, "bb_position": "below_lower"}
    assert leg["min_tags"] == 2

    assert s4.regime_families == ("mean_reversion",)
    assert s4.size_scale == Decimal("0.5")
    assert s4.r_multiple_override == Decimal("1")
    assert s4.tag == "s4_reversion"
    # SPEC-cadence T1-AC-5: S4's time-stop restriction -- 48h, not the 168h
    # default (STRATEGY-PACK.md "restricted reversion").
    assert s4.horizon_hours == 48


def test_s4_registered_last_in_strategies_tuple() -> None:
    # PIN: "Registry order: S1, S2, S3, S4 (last = lowest priority, by
    # evidence grade)." S3 is deferred this batch, so the real tuple today
    # is S1, S2, S4 -- S4 still last.
    keys = [s.key for s in STRATEGIES]
    assert keys == ["s1_momentum", "s2_pullback", "s4_reversion"]


def test_strategy_by_key_contains_s4_and_matches_build_registry() -> None:
    registry = build_registry(STRATEGIES)
    assert registry["s4_reversion"] is STRATEGY_BY_KEY["s4_reversion"]
    assert STRATEGY_BY_KEY["s4_reversion"].key == "s4_reversion"


def test_s4_strategy_def_is_frozen_immutable() -> None:
    s4 = STRATEGY_BY_KEY["s4_reversion"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s4.side = "sell"  # type: ignore[misc]


def test_build_registry_still_succeeds_with_s1_s2_s4_present() -> None:
    registry = build_registry(STRATEGIES)
    # Superset pin (round-19 adjudication): exact-set pins break on every
    # future strategy append -- the fragile-exact-pin class.
    assert {"s1_momentum", "s2_pullback", "s4_reversion"} <= set(registry.keys())


# ---------------------------------------------------------------------------
# 2. S4 leg semantics end-to-end through scan_confluence: min_tags=2 needs
#    BOTH rsi_max and bb_position to fire; rsi oversold alone (bb absent)
#    fails outright -- "(0/2 tags)" per 172.1's AND-kill semantics (CTO
#    adjudication, round 19; min_tags=2's independent bite is via regime
#    pruning, not partial filter passes).
# ---------------------------------------------------------------------------


def test_s4_end_to_end_both_conditions_fire_yields_match_with_both_tags(
    monkeypatch,
) -> None:
    series = _series(_S4_BOTH_FIRE_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    s4 = STRATEGY_BY_KEY["s4_reversion"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s4.legs),
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    matches = result["matches"]
    assert len(matches) == 1
    match = matches[0]
    assert match["confluence"] is True
    assert set(match["legs"]["1h"]["signal_tags"]) == {"oversold", "at_support"}


def test_s4_end_to_end_oversold_without_bb_support_fails_leg_outright(
    monkeypatch,
) -> None:
    series = _series(_RSI_OVERSOLD_ONLY_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))

    s4 = STRATEGY_BY_KEY["s4_reversion"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s4.legs),
        symbols=["BTC/USD"],
        regime_gate=False,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (0/2 tags)" in result["warnings"]


# ---------------------------------------------------------------------------
# 3. Regime: S4's tags (oversold, at_support) are BOTH mean_reversion-family
#    today (`strategies.TAGS`) -- a momentum-only regime prunes both (leg
#    fails); a mean_reversion-recommending regime keeps both (leg passes).
#    Note the inversion the mission flags: S4 is a BEAR/chop-restricted
#    strategy, but "regime recommends mean_reversion" is what lets it pass,
#    not "regime is bearish" per se (no bearish regime family exists in the
#    3-state vocabulary -- momentum/breakout/mean_reversion).
# ---------------------------------------------------------------------------


def test_s4_tags_are_mean_reversion_family_in_shared_registry() -> None:
    assert strategies.TAGS["oversold"] == "mean_reversion"
    assert strategies.TAGS["at_support"] == "mean_reversion"


def test_s4_leg_fails_under_momentum_only_regime(monkeypatch) -> None:
    series = _series(_S4_BOTH_FIRE_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))
    monkeypatch.setattr("tradekit.mae._regime.compute_regime", _restrictive_regime)

    s4 = STRATEGY_BY_KEY["s4_reversion"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s4.legs),
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    assert result["matches"] == []
    assert "BTC/USD: leg 1h failed (0/2 tags)" in result["warnings"]


def test_s4_leg_passes_under_mean_reversion_recommending_regime(monkeypatch) -> None:
    series = _series(_S4_BOTH_FIRE_CLOSES, symbol="BTC/USD", timeframe="1h")
    _install_bars_by_key(monkeypatch, {("BTC/USD", "1h"): series})
    _install_fixed_clock(monkeypatch, datetime(2026, 7, 27, tzinfo=UTC))
    monkeypatch.setattr("tradekit.mae._regime.compute_regime", _mean_reversion_regime)

    s4 = STRATEGY_BY_KEY["s4_reversion"]
    result = scan_confluence(
        asset_class="crypto",
        legs=list(s4.legs),
        symbols=["BTC/USD"],
        regime_gate=True,
    )

    matches = result["matches"]
    assert len(matches) == 1
    assert set(matches[0]["legs"]["1h"]["signal_tags"]) == {"oversold", "at_support"}


# ---------------------------------------------------------------------------
# 4. Regression: S1/S2 defs byte-identical after S4's registration; existing
#    BBPosition vocabulary and its tag mapping unaffected.
# ---------------------------------------------------------------------------


def test_s1_strategy_def_unchanged_by_s4_addition() -> None:
    s1 = STRATEGY_BY_KEY["s1_momentum"]
    assert s1.key == "s1_momentum"
    assert s1.side == "buy"
    assert len(s1.legs) == 1
    assert s1.legs[0]["filters"] == {"macd_signal": "bullish_cross", "volume_spike": 1.5}
    assert s1.legs[0]["min_tags"] == 1
    assert s1.size_scale == Decimal("1")
    assert s1.r_multiple_override is None
    assert s1.tag == "s1_momentum"


def test_s2_strategy_def_unchanged_by_s4_addition() -> None:
    s2 = STRATEGY_BY_KEY["s2_pullback"]
    assert s2.key == "s2_pullback"
    assert s2.side == "buy"
    assert len(s2.legs) == 2
    assert s2.legs[0]["filters"] == {"ema_above": 50, "macd_signal": "bullish_cross"}
    assert s2.legs[1]["filters"] == {"rsi_band": [35, 50]}
    assert s2.size_scale == Decimal("1")
    assert s2.r_multiple_override is None
    assert s2.tag == "s2_pullback"


def test_bb_position_closed_vocabulary_unaffected_by_s4() -> None:
    # S4 reuses "below_lower" -- no new BBPosition member added by this
    # batch (ASSUMPTION-FLAG S4-1: "at_support" is NOT a new vocabulary
    # value, it is the tag "below_lower" already produces).
    assert {member.value for member in BBPosition} == {
        "below_lower",
        "above_upper",
        "inside",
    }
