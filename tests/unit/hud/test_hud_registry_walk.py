"""RED-stage failing tests for T-MTF-4 (docs/design/MTF-SCAN.md "Strategy
registry (data, not code)" section): hud's `scan_setup` seam default walks
`tradekit.mae.STRATEGIES` in priority order instead of running the old
hardcoded S1 battery.

DOC PINS (quoted verbatim, docs/design/MTF-SCAN.md):

  "hud's `scan_setup` seam default changes from the hardcoded S1 battery to:
  walk `STRATEGIES` in order, arm a def only if `regime_families` matches
  the symbol's regime, return the first def whose legs all pass -
  `_SetupResult` gains `strategy_key: str` (and the report's setup gate
  rationale names it). One strategy per symbol per scan (first-match; no
  stacking - stacking is a future ASSUMPTIONS decision, not an implementer
  choice)."

  "STRATEGIES: tuple[StrategyDef, ...]  # ordered by priority; first match
  wins per symbol"

tests/ASSUMPTIONS.md 173.4 (T-MTF-4 PIN, required before its red): "a
StrategyDef 'passes' for first-match-wins ONLY with non-empty surviving
tags on every leg; an empty-tag confluence match must not arm anything."

tests/ASSUMPTIONS.md 174.5: "regime_families is unconsumed metadata until
T-MTF-4; adjudicate there when the walk consumes it." MTF-SCAN.md's T-MTF-4
text above DOES say the walk consumes it ("arm a def only if
regime_families matches the symbol's regime") -- so this batch is where
174.5's tension resolves. What is NOT pinned is the any-vs-all semantics of
"matches" for a MULTI-element regime_families tuple (e.g. S1's
("momentum","breakout")) -- see ASSUMPTION-FLAG 3 below; only the
unambiguous singleton-family case is tested here.

RED stage: `tradekit.hud._build._default_scan_setup` still calls
`mae.scan_markets` directly with the hardcoded `_SETUP_FILTERS`/
`_SETUP_TIMEFRAME` battery (hud/_build.py:133-161) and `_SetupResult` has no
`strategy_key` field (hud/_build.py:59-68) -- every test below fails either
on `AttributeError: '_SetupResult' object has no attribute 'strategy_key'`
or on a missing `strategy_key` field in the dataclasses.fields() CONTRACT
check. This is the expected red state.

Seams (house style, same as test_strategies_registry.py /
test_s4_reversion_strategy.py / test_scan_setup_vocabulary_contract.py):
bars faked via "tradekit.mae._runtime.get_closed_bars" (string-path
monkeypatch, keyed by (symbol, timeframe)); regime faked via
monkeypatch.setattr(_regime, "compute_regime", ...); clock via
"tradekit.mae._runtime._clock". `_default_scan_setup` is called DIRECTLY
(not through the `hud._build.scan_setup` module seam) -- same convention as
test_scan_setup_vocabulary_contract.py's TestDefaultScanSetupRealScannerContract,
which exercises the real, un-mocked scan pipeline end to end.

ASSUMPTIONS ESCAPE HATCH -- flagged here, never improvised (see also the
dispatch report):

1. STRATEGIES-swap seam. MTF-SCAN.md pins `STRATEGIES: tuple[StrategyDef,
   ...]` as the walk's data source but does not pin how a test substitutes
   a synthetic registry for controlled walk-semantics tests (ordering,
   short-circuit, empty-tag guard) independent of the real S1/S2/S4
   fixtures. Best reading adopted here (same "data, not code" spirit as
   `build_registry`'s own independent testability): monkeypatch the
   `STRATEGIES` tuple itself, both on `tradekit.mae` (the public
   re-export) and `tradekit.mae._strategies` (the definition module), so
   the walk picks up the substitution regardless of which binding it reads
   at call time. If the eventual implementation threads `strategies`
   through as an explicit parameter instead, these tests will need a
   one-line seam-target update, not a semantic rewrite.
2. `strategy_key` "no match" sentinel. The doc types the field
   `strategy_key: str` (not `str | None`), but doesn't pin the literal
   value when no def arms. Tests assert falsiness (`not result.strategy_key`)
   rather than committing to `""` vs some other sentinel.
3. `regime_families` any-vs-all semantics for multi-element tuples (e.g.
   S1's `("momentum", "breakout")`) are NOT pinned by MTF-SCAN.md's T-MTF-4
   text -- only that "regime_families matches the symbol's regime" gates
   arming. Tests here only exercise the unambiguous singleton-tuple case
   (`regime_families=("breakout",)` against a regime recommending exactly
   `["breakout"]` or exactly `["momentum"]`); the multi-family case is left
   untested pending CTO adjudication.
4. Sizing/r_multiple_override wiring (mission area 7): per
   tests/ASSUMPTIONS.md 175.3, StrategyDef -> thesis/sizing wiring is
   DEFERRED to the cadence batch; hud/_serve.py's hardcoded values stand
   until then. No test is written against that wiring here, consistent
   with test_s4_reversion_strategy.py's ASSUMPTION-FLAG S4-2 precedent of
   not inventing tests against nonexistent wiring.
5. Report-naming exact format: MTF-SCAN.md says only "the report's setup
   gate rationale names it" -- no exact string format pinned. The test
   asserts the strategy_key SUBSTRING appears in the setup gate's
   `.observed` or `.rationale` (relative/substring pin, per the
   fragile-exact-pin doctrine, ASSUMPTIONS 175.4), not exact string
   equality.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries

# ---------------------------------------------------------------------------
# Shared fixture helpers (same house style as test_strategies_registry.py /
# test_s4_reversion_strategy.py).
# ---------------------------------------------------------------------------


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


def _install_fixed_clock(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: now)


def _install_bars_by_key(
    monkeypatch: pytest.MonkeyPatch, series_by_key: dict[tuple[str, str], BarSeries]
) -> list[tuple[str, str, int]]:
    """SEAM: mae._runtime.get_closed_bars, keyed by (symbol, timeframe) --
    records every call so "later strategy not evaluated" (first-match-wins
    short-circuit) is directly observable as an absent call, not inferred."""
    calls: list[tuple[str, str, int]] = []

    def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        calls.append((symbol, timeframe, lookback_days))
        return series_by_key[(symbol, timeframe)]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    return calls


def _install_strategies(monkeypatch: pytest.MonkeyPatch, strategies: tuple[Any, ...]) -> None:
    """ASSUMPTION-FLAG 1 seam: swap the registry `STRATEGIES` walks. Patches
    both bindings so the substitution takes regardless of which the
    eventual implementation reads at call time."""
    import tradekit.mae as mae_pkg
    import tradekit.mae._strategies as strategies_mod

    monkeypatch.setattr(mae_pkg, "STRATEGIES", strategies)
    monkeypatch.setattr(strategies_mod, "STRATEGIES", strategies)


def _regime(recommended: list[str]) -> Any:
    """Fake `_regime.compute_regime` -- accepts ANY call convention
    (established round-16/17 precedent: scan_markets/scan_confluence call
    it with different positional/keyword shapes)."""

    def _fake(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "current_state": "fake_state",
            "confidence": 0.9,
            "recommended_strategies": list(recommended),
        }

    return _fake


_PERMISSIVE_REGIME = _regime(["momentum", "breakout", "mean_reversion"])
_BREAKOUT_ONLY_REGIME = _regime(["breakout"])
_MOMENTUM_ONLY_REGIME = _regime(["momentum"])
_MEAN_REVERSION_ONLY_REGIME = _regime(["mean_reversion"])


def _make_strategy_def(
    *,
    key: str,
    timeframe: str,
    filters: dict[str, Any],
    min_tags: int,
    regime_families: tuple[str, ...],
    side: str = "buy",
) -> Any:
    from tradekit.mae import StrategyDef

    return StrategyDef(
        key=key,
        side=side,  # type: ignore[arg-type]
        legs=({"timeframe": timeframe, "filters": filters, "min_tags": min_tags},),
        regime_families=regime_families,
        size_scale=Decimal("1"),
        r_multiple_override=None,
        tag=key,
    )


# Single-condition volume-spike synthetic defs, one leg each, at DISTINCT
# timeframes so per-symbol firing is independently controllable via
# `_install_bars_by_key` without any macd/rsi/bb derivation. `volume_spike`
# hit -> tag "volume_spike" -> family "breakout"
# (_scanner.py module docstring's Signal-tag/strategy-family table).
_PROTO_A = _make_strategy_def(
    key="proto_a",
    timeframe="1h",
    filters={"volume_spike": 1.5},
    min_tags=1,
    regime_families=("breakout",),
)
_PROTO_B = _make_strategy_def(
    key="proto_b",
    timeframe="4h",
    filters={"volume_spike": 1.5},
    min_tags=1,
    regime_families=("breakout",),
)

_FLAT_VOLUMES_NO_SPIKE = [100.0] * 25
_SPIKE_VOLUMES = [100.0] * 24 + [1000.0]
_FLAT_CLOSES = [100.0] * 25


def _volume_series(symbol: str, timeframe: str, *, spike: bool) -> BarSeries:
    volumes = _SPIKE_VOLUMES if spike else _FLAT_VOLUMES_NO_SPIKE
    return _series(_FLAT_CLOSES, volumes, symbol=symbol, timeframe=timeframe)


# ---------------------------------------------------------------------------
# 0. CONTRACT: _SetupResult gains strategy_key: str.
# ---------------------------------------------------------------------------


def test_setup_result_dataclass_gains_strategy_key_field() -> None:
    """CONTRACT: MTF-SCAN.md T-MTF-4 pin -- "`_SetupResult` gains
    `strategy_key: str`"."""
    import tradekit.hud._build as hud_build

    field_names = {f.name for f in dataclasses.fields(hud_build._SetupResult)}
    assert "strategy_key" in field_names


# ---------------------------------------------------------------------------
# 1. Walk semantics: first-match-wins, per-symbol, in STRATEGIES order.
# ---------------------------------------------------------------------------


class TestWalkFirstMatchWins:
    def test_first_matching_strategy_in_order_claims_the_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: with STRATEGIES=(proto_a, proto_b) and a symbol whose
        1h leg (proto_a) fires while 4h (proto_b) does not, the walk claims
        proto_a -- `_SetupResult.strategy_key == "proto_a"` and
        `signal_tags` is non-empty."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        _install_strategies(monkeypatch, (_PROTO_A, _PROTO_B))
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {
                ("SYM1", "1h"): _volume_series("SYM1", "1h", spike=True),
                ("SYM1", "4h"): _volume_series("SYM1", "4h", spike=False),
            },
        )

        result = hud_build._default_scan_setup("SYM1")

        assert result.signal_tags != []
        assert result.strategy_key == "proto_a"

    def test_symbol_matching_no_strategy_is_absent_ie_wait(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: neither proto_a nor proto_b's leg fires for this
        symbol -- `signal_tags == []` and `strategy_key` is falsy (no def
        armed), same "wait" contract as today's empty-tags case
        (hud/_build.py:434)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        _install_strategies(monkeypatch, (_PROTO_A, _PROTO_B))
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {
                ("SYM2", "1h"): _volume_series("SYM2", "1h", spike=False),
                ("SYM2", "4h"): _volume_series("SYM2", "4h", spike=False),
            },
        )

        result = hud_build._default_scan_setup("SYM2")

        assert result.signal_tags == []
        assert not result.strategy_key

    def test_later_strategy_in_order_not_evaluated_once_earlier_one_claims(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: MTF-SCAN.md "first-match-wins ... later defs not
        evaluated for it" -- with BOTH proto_a (1h) and proto_b (4h) firing
        for the same symbol, proto_a (earlier in STRATEGIES order) claims
        it and proto_b's 4h leg is NEVER fetched -- observable directly as
        an absent call, not inferred from the result alone."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        _install_strategies(monkeypatch, (_PROTO_A, _PROTO_B))
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        calls = _install_bars_by_key(
            monkeypatch,
            {
                ("SYM3", "1h"): _volume_series("SYM3", "1h", spike=True),
                ("SYM3", "4h"): _volume_series("SYM3", "4h", spike=True),
            },
        )

        result = hud_build._default_scan_setup("SYM3")

        assert result.strategy_key == "proto_a"
        assert not any(call[0] == "SYM3" and call[1] == "4h" for call in calls), (
            "proto_b's 4h leg must never be fetched once proto_a already claimed SYM3 "
            "(first-match-wins: later defs are not evaluated)"
        )


# ---------------------------------------------------------------------------
# 3. Empty-tag guard (ASSUMPTIONS 173.4, T-MTF-4 PIN).
# ---------------------------------------------------------------------------


class TestEmptyTagGuard:
    def test_empty_tag_confluence_match_does_not_arm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: ASSUMPTIONS 173.4 -- "a StrategyDef 'passes' for
        first-match-wins ONLY with non-empty surviving tags on every leg;
        an empty-tag confluence match must not arm anything." A def with an
        unconditional leg (`filters={}`, `min_tags=0`) DOES satisfy
        `scan_confluence`'s own `len(pruned_tags) < min_tags` check (0 < 0
        is False -- see `_confluence.py` docstring point "min_tags=0 makes
        a leg unconditional", ASSUMPTIONS 172.4) and so WOULD be reported
        as `confluence: True` with `signal_tags: []` by `scan_confluence`
        itself. The walk-level guard must still refuse to arm on that empty
        result -- this is the walk's OWN extra check, not something
        `scan_confluence` enforces for it."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        empty_leg_def = _make_strategy_def(
            key="empty_tag_probe",
            timeframe="1h",
            filters={},
            min_tags=0,
            regime_families=("breakout",),
        )
        _install_strategies(monkeypatch, (empty_leg_def,))
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {("SYM4", "1h"): _volume_series("SYM4", "1h", spike=False)},
        )

        result = hud_build._default_scan_setup("SYM4")

        assert result.signal_tags == []
        assert not result.strategy_key, (
            "an empty-tag confluence match must not arm the def (ASSUMPTIONS 173.4) "
            "even though scan_confluence's own min_tags=0 check would let it through"
        )


# ---------------------------------------------------------------------------
# 6. regime_families consumption (ASSUMPTIONS 174.5 resolves here).
# ---------------------------------------------------------------------------


class TestRegimeFamiliesGating:
    def test_regime_family_mismatch_skips_the_def_even_though_its_leg_would_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: MTF-SCAN.md T-MTF-4 pin -- "arm a def only if
        regime_families matches the symbol's regime". proto_a's leg WOULD
        fire (volume spike present) but the regime recommends ONLY
        "momentum" while proto_a's `regime_families == ("breakout",)` --
        no overlap -- so proto_a must not arm despite its leg passing.
        With no other candidate in STRATEGIES, the symbol ends up wait
        (empty tags, falsy strategy_key)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        _install_strategies(monkeypatch, (_PROTO_A,))
        monkeypatch.setattr(_regime_mod, "compute_regime", _MOMENTUM_ONLY_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {("SYM5", "1h"): _volume_series("SYM5", "1h", spike=True)},
        )

        result = hud_build._default_scan_setup("SYM5")

        assert not result.strategy_key
        assert result.signal_tags == []

    def test_regime_family_match_lets_the_def_arm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """BEHAVIOR: the positive control for the test above -- same
        proto_a def, same firing leg, but the regime now recommends
        exactly `["breakout"]` (matches proto_a's `regime_families`) -- the
        def arms."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        _install_strategies(monkeypatch, (_PROTO_A,))
        monkeypatch.setattr(_regime_mod, "compute_regime", _BREAKOUT_ONLY_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {("SYM6", "1h"): _volume_series("SYM6", "1h", spike=True)},
        )

        result = hud_build._default_scan_setup("SYM6")

        assert result.strategy_key == "proto_a"
        assert result.signal_tags != []


# ---------------------------------------------------------------------------
# 4. S1 regression: real registry, behavior-identical to today.
# ---------------------------------------------------------------------------

# S1 fixture reused VERBATIM (provenance:
# tests/contract/test_scan_setup_vocabulary_contract.py's
# `_MACD_BULLISH_CLOSES`/`_VOLUMES` -- the fixture that proved
# `_default_scan_setup` produces non-empty signal_tags for a bullish +
# volume-confirmed symbol, independently derived there from
# test_scan_markets_verb.py's own MACD derivation).
_S1_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_S1_VOLUMES = [100.0] * (len(_S1_MACD_BULLISH_CLOSES) - 1) + [1000.0]


def _s1_fixture_bars(symbol: str) -> BarSeries:
    return _series(_S1_MACD_BULLISH_CLOSES, _S1_VOLUMES, symbol=symbol, timeframe="4h")


_S1_MOMENTUM_REGIME = _regime(["momentum"])


class TestS1RegressionThroughRealRegistry:
    def test_s1_only_fixture_still_produces_nonempty_tags_and_claims_s1_momentum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR/GOLDEN(regression): the real STRATEGIES registry (S1,
        S2, S4 -- unmodified by this test) walked against the exact fixture
        that test_scan_setup_vocabulary_contract.py pins for S1's
        behavior-identical migration must still produce non-empty
        signal_tags (the same regression that file guards) AND now also
        report `strategy_key == "s1_momentum"` (T-MTF-4's new naming pin).
        S1 is first in STRATEGIES order and is the ONLY def whose 4h leg
        this fixture can satisfy (S2 needs an additional 1h leg this
        fixture never supplies bars for; if the walk tried S2 before S1 it
        would KeyError here rather than silently passing)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        monkeypatch.setattr(_regime_mod, "compute_regime", _S1_MOMENTUM_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch, {("LINK/USD", "4h"): _s1_fixture_bars("LINK/USD")}
        )

        result = hud_build._default_scan_setup("LINK/USD")

        assert result.signal_tags != []
        assert result.strategy_key == "s1_momentum"

    def test_nothing_fires_produces_empty_tags_and_no_strategy_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: real registry, flat 4h AND 1h bars that satisfy no
        def's leg(s) at all -- "empty STRATEGIES / no def arms -> scan_setup
        returns empty tags -> wait (existing path)" (MTF-SCAN.md error
        map). `strategy_key` is falsy. Both S1's and S2's 4h leg fail
        outright on flat bars (AND-composition short-circuits before S2's
        1h leg is ever fetched), so the walk genuinely reaches S4
        (1h-only) as the last candidate -- reaching S4 here is CORRECT walk
        behavior, not a bug: this fixture supplies flat 1h bars too (RSI
        settles near 50, comfortably above S4's `rsi_max=25`, and no close
        sits below the lower Bollinger band) so S4's leg is genuinely
        evaluated and genuinely declines, proving every registry def is
        really evaluated and really declines rather than the walk silently
        skipping S4 via a swallowed exception."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        flat_4h = _series([100.0] * 60, [100.0] * 60, symbol="FLAT/USD", timeframe="4h")
        flat_1h = _series([100.0] * 60, [100.0] * 60, symbol="FLAT/USD", timeframe="1h")
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch, {("FLAT/USD", "4h"): flat_4h, ("FLAT/USD", "1h"): flat_1h}
        )

        result = hud_build._default_scan_setup("FLAT/USD")

        assert result.signal_tags == []
        assert not result.strategy_key

    def test_no_arm_walk_names_the_real_killers_in_attrition_stages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2/ASSUMPTIONS 163b regression: a no-arm walk over the real
        registry must not collapse every setup kill into the uninformative
        "setup" gate -- `attrition_stages` must be non-empty and its
        entries must name the actual defs that declined (S1, S2, S4), not
        just an opaque pass/fail. Substring assertions per the
        fragile-exact-pin doctrine (ASSUMPTIONS 175.4) -- the exact stage
        count/order is an implementation detail, not a pinned contract."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        flat_4h = _series([100.0] * 60, [100.0] * 60, symbol="FLAT/USD", timeframe="4h")
        flat_1h = _series([100.0] * 60, [100.0] * 60, symbol="FLAT/USD", timeframe="1h")
        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch, {("FLAT/USD", "4h"): flat_4h, ("FLAT/USD", "1h"): flat_1h}
        )

        result = hud_build._default_scan_setup("FLAT/USD")

        assert result.attrition_stages != []
        stage_names = " | ".join(stage["name"] for stage in result.attrition_stages)
        assert "s1_momentum" in stage_names
        assert "s4_reversion" in stage_names
        assert all(stage["outcome"] == "fail" for stage in result.attrition_stages)


# ---------------------------------------------------------------------------
# 5. Multi-strategy: real registry, S4-only and S1-beats-S4 first-match.
# ---------------------------------------------------------------------------

# S4's "both conditions fire" 1h fixture reused VERBATIM (provenance:
# tests/unit/mae/test_s4_reversion_strategy.py's `_s4_both_fire_closes` --
# independently checked there via momentum.rsi/volatility.bollinger as an
# oracle: last RSI(14) ~= 7.05 <= 25 -> "oversold"; last close 70.0 below
# the lower band -> "below_lower" -> "at_support"; both S4 leg tags fire).
def _s4_both_fire_closes() -> list[float]:
    import random

    rng = random.Random(20260716)
    return [100.0 + rng.uniform(-0.5, 0.5) for _ in range(24)] + [70.0]


_S4_BOTH_FIRE_CLOSES = _s4_both_fire_closes()


def _s4_fixture_bars(symbol: str) -> BarSeries:
    return _series(_S4_BOTH_FIRE_CLOSES, symbol=symbol, timeframe="1h")


# S1-killing 4h fixture: flat closes/volumes fail BOTH S1's macd_signal
# (macd_hist == 0.0, not > 0.0) and S2's ema_above (close == ema exactly,
# strictly > required per ASSUMPTIONS 174.1) -- so S1 and S2's 4h leg (the
# FIRST leg in S2's tuple; AND-composition short-circuits before S2's 1h
# leg is ever fetched, per _confluence.py's own short-circuit doc) both
# fail outright, leaving S4 (1h-only) as the sole candidate that can claim.
_S1_S2_KILLER_4H_CLOSES = [100.0] * 60
_S1_S2_KILLER_4H_VOLUMES = [100.0] * 60


def _s1_s2_killer_4h_bars(symbol: str) -> BarSeries:
    return _series(
        _S1_S2_KILLER_4H_CLOSES, _S1_S2_KILLER_4H_VOLUMES, symbol=symbol, timeframe="4h"
    )


class TestMultiStrategyRealRegistry:
    def test_only_s4_fires_claims_s4_reversion_with_its_tag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: real registry (S1, S2, S4 order). S1's and S2's 4h leg
        both fail outright on flat bars; S4's 1h leg fires. A regime
        recommending all three families (momentum, breakout,
        mean_reversion) isolates the leg-firing behavior from the
        regime_families gate (tested separately above)."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        _install_bars_by_key(
            monkeypatch,
            {
                ("S4ONLY/USD", "4h"): _s1_s2_killer_4h_bars("S4ONLY/USD"),
                ("S4ONLY/USD", "1h"): _s4_fixture_bars("S4ONLY/USD"),
            },
        )

        result = hud_build._default_scan_setup("S4ONLY/USD")

        assert result.strategy_key == "s4_reversion"
        assert result.signal_tags != []

    def test_s1_and_s4_would_both_fire_s1_wins_first_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: MTF-SCAN.md area-5 pin -- "bars where S1 AND S4 both
        would fire -> S1 claims (first match wins), S4 not consulted". S1's
        4h leg fires (bullish MACD + volume spike); S4's 1h leg would ALSO
        fire (reused S4 fixture) but must never be reached -- observable
        as an absent (symbol, "1h") fetch."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod

        monkeypatch.setattr(_regime_mod, "compute_regime", _PERMISSIVE_REGIME)
        _install_fixed_clock(monkeypatch, datetime(2026, 7, 30, tzinfo=UTC))
        calls = _install_bars_by_key(
            monkeypatch,
            {
                ("BOTH/USD", "4h"): _s1_fixture_bars("BOTH/USD"),
                ("BOTH/USD", "1h"): _s4_fixture_bars("BOTH/USD"),
            },
        )

        result = hud_build._default_scan_setup("BOTH/USD")

        assert result.strategy_key == "s1_momentum"
        assert not any(call[0] == "BOTH/USD" and call[1] == "1h" for call in calls), (
            "S4's 1h leg must never be fetched once S1 already claimed BOTH/USD "
            "(first-match-wins: later defs are not consulted)"
        )


# ---------------------------------------------------------------------------
# 2/8. Report naming: build_state's setup gate rationale names the claiming
#      strategy_key (pinned at the report-dict level, not HTML).
# ---------------------------------------------------------------------------


class TestReportNamesClaimingStrategy:
    def test_setup_gate_names_the_claiming_strategy_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: MTF-SCAN.md T-MTF-4 pin -- "the report's setup gate
        rationale names it". `scan_setup` left REAL (default, un-monkeypatched)
        so `build_state` drives the actual registry walk; `evaluate_policy`/
        `open_position_symbols`/`sizing_info` are seamed per the established
        `build_state` test convention (test_build_state.py) so the funnel
        reaches the "setup" gate deterministically. ASSUMPTION-FLAG 5: exact
        format not pinned -- asserted as a SUBSTRING of either `.observed`
        or `.rationale` on the "setup" GateResult, not exact equality."""
        import tradekit.hud._build as hud_build
        import tradekit.mae._regime as _regime_mod
        from tradekit.hud import build_state

        monkeypatch.setattr(_regime_mod, "compute_regime", _S1_MOMENTUM_REGIME)
        captured_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
        monkeypatch.setattr("tradekit.mae._runtime.clock", lambda: captured_at)
        # build_state's OWN data_integrity gate fetches "1h" bars
        # (hud/_build.py `_TIMEFRAME`/`_LOOKBACK_DAYS`) independently of the
        # setup walk's "4h" leg -- both keys must be seamed or the symbol
        # degrades to a failed data_integrity gate before "setup" is ever
        # reached (same two-fetch shape test_build_state.py's
        # `_patch_setup_sufficient` handles by ignoring the timeframe arg).
        _install_bars_by_key(
            monkeypatch,
            {
                ("LINK/USD", "4h"): _s1_fixture_bars("LINK/USD"),
                ("LINK/USD", "1h"): _s1_fixture_bars("LINK/USD"),
            },
        )
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = build_state(
            ["LINK/USD"], captured_at=captured_at, equity_usd=Decimal("5000")
        )

        entry = next(e for e in state.report if e.symbol == "LINK/USD")
        setup_gate = next(g for g in entry.gates if g.name == "setup")
        assert setup_gate.passed is True
        assert "s1_momentum" in setup_gate.observed or "s1_momentum" in setup_gate.rationale, (
            f"setup gate must name the claiming strategy_key somewhere; got "
            f"observed={setup_gate.observed!r} rationale={setup_gate.rationale!r}"
        )
