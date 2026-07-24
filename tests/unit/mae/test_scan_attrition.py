"""tests for SPRINT-TICKET-001 P3 — `_scanner.scan()` result gains
`"attrition"`: one entry per (symbol, timeframe) in input order, additive
to the existing `matches`/`warnings`/`regime_context`/`scan_ts` keys.

Pinned shape (docs/specs/SPRINT-TICKET-001.md P3):
    {"symbol": str, "timeframe": str,
     "stages": [{"name": str, "outcome": "pass"|"fail", "observed": str}],
     "killed_by": str | None}
Stage order as evaluated: "bars", then per-filter present ("rsi",
"macd_signal", "bb_position", "volume_spike", "atr_percentile"), then
"regime_gate". Stages AFTER the killer are ABSENT (not "skip"). `observed`
is human-oriented prose (ASSUMPTIONS 163) — assertions below match
substrings only, never the whole string, per that pin.

Fixture provenance: the two MACD closes series below are the SAME fixtures
already independently derived (and cited) in
tests/unit/mae/test_scan_markets_verb.py's module docstring against
`tradekit.mae._indicators.momentum.macd` directly:
    bullish: [100.0]*40 + [100.0 + i**1.3 for i in 1..20]
        -> macd(closes).histogram[-1] == 2.632866287861548   (> 0)
    bearish: [100.0]*40 + [100.0 - i**1.3 for i in 1..20]
        -> macd(closes).histogram[-1] == -2.6328662878615496  (< 0)
The survivor's volume-spike component reuses the same derivation as that
file's volume-ratio fixture (SMA(20) trailing window INCLUDING the current
bar): 19 bars of volume=100.0 + 1 spike bar of volume=1000.0 ->
volume_ratio(20)[-1] == 1000.0/145.0 == 6.896551724137931, which clears a
`volume_spike: 1.5` filter with headroom.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _scanner

_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_MACD_BEARISH_CLOSES = [100.0] * 40 + [100.0 - i**1.3 for i in range(1, 21)]

_FILTERS = {"macd_signal": "bullish_cross", "volume_spike": 1.5}


def _series_with_volumes(symbol: str, closes: list[float], volumes: list[float]) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c + 0.3)),
            low=Decimal(str(c - 0.3)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
    ]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


def _install(monkeypatch, series_by_symbol: dict[str, BarSeries]) -> None:
    def _fake(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return series_by_symbol[symbol]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake)
    monkeypatch.setattr(
        "tradekit.mae._runtime._clock", lambda: datetime(2026, 7, 24, tzinfo=UTC)
    )


class TestP3AttritionTelemetry:
    def test_killer_symbol_dies_at_macd_signal_with_stages_absent_after_killer(
        self, monkeypatch
    ) -> None:
        """BEHAVIOR: a symbol with negative MACD histogram fails at the
        `macd_signal` stage — the `volume_spike` stage (evaluated AFTER
        `macd_signal` per the pinned stage order) must be ABSENT from
        `stages` entirely, not present with a "skip" outcome (P3: "Stages
        after the killer are ABSENT (not 'skip')"). `killed_by` names the
        killing stage."""
        killer_series = _series_with_volumes(
            "NEAR/USD", _MACD_BEARISH_CLOSES, [100.0] * len(_MACD_BEARISH_CLOSES)
        )
        survivor_series = _series_with_volumes(
            "SOL/USD",
            _MACD_BULLISH_CLOSES,
            [100.0] * (len(_MACD_BULLISH_CLOSES) - 1) + [1000.0],
        )
        _install(monkeypatch, {"NEAR/USD": killer_series, "SOL/USD": survivor_series})

        result = _scanner.scan(
            asset_class="crypto",
            timeframes=["1d"],
            filters=_FILTERS,
            symbols=["NEAR/USD", "SOL/USD"],
            regime_gate=False,
        )

        attrition = {entry["symbol"]: entry for entry in result["attrition"]}
        killer = attrition["NEAR/USD"]
        assert killer["timeframe"] == "1d"
        assert killer["killed_by"] == "macd_signal"

        stage_names = [stage["name"] for stage in killer["stages"]]
        assert stage_names == ["bars", "macd_signal"], (
            "stages after the killer (volume_spike) must be ABSENT, not present-as-skip"
        )
        bars_stage, macd_stage = killer["stages"]
        assert bars_stage["outcome"] == "pass"
        assert macd_stage["outcome"] == "fail"
        assert "hist=" in macd_stage["observed"]
        assert "-2.6328662878615496"[:6] in macd_stage["observed"] or "-2.63" in macd_stage[
            "observed"
        ]

    def test_survivor_symbol_has_killed_by_none_and_all_present_stages_pass(
        self, monkeypatch
    ) -> None:
        """BEHAVIOR: a symbol clearing every filter present has
        `killed_by is None` and every evaluated stage's outcome is "pass" —
        `matches` shape is unchanged by this additive telemetry key."""
        killer_series = _series_with_volumes(
            "NEAR/USD", _MACD_BEARISH_CLOSES, [100.0] * len(_MACD_BEARISH_CLOSES)
        )
        survivor_series = _series_with_volumes(
            "SOL/USD",
            _MACD_BULLISH_CLOSES,
            [100.0] * (len(_MACD_BULLISH_CLOSES) - 1) + [1000.0],
        )
        _install(monkeypatch, {"NEAR/USD": killer_series, "SOL/USD": survivor_series})

        result = _scanner.scan(
            asset_class="crypto",
            timeframes=["1d"],
            filters=_FILTERS,
            symbols=["NEAR/USD", "SOL/USD"],
            regime_gate=False,
        )

        attrition = {entry["symbol"]: entry for entry in result["attrition"]}
        survivor = attrition["SOL/USD"]
        assert survivor["killed_by"] is None
        stage_names = [stage["name"] for stage in survivor["stages"]]
        assert stage_names == ["bars", "macd_signal", "volume_spike"]
        assert all(stage["outcome"] == "pass" for stage in survivor["stages"])

        # matches shape unchanged by the additive attrition key (P3: "existing
        # keys unchanged — additive only").
        matches = result["matches"]
        assert len(matches) == 1
        assert matches[0]["symbol"] == "SOL/USD"
        assert set(matches[0].keys()) == {
            "symbol",
            "timeframe",
            "price",
            "rsi",
            "macd_hist",
            "atr",
            "atr_pct_of_price",
            "volume_ratio",
            "signal_tags",
        }

    def test_attrition_entries_in_input_symbol_order(self, monkeypatch) -> None:
        """BEHAVIOR: `attrition` carries one entry per (symbol, timeframe)
        in INPUT order (P3: "one entry per (symbol, timeframe) in input
        order") — independent of who survives or dies."""
        killer_series = _series_with_volumes(
            "NEAR/USD", _MACD_BEARISH_CLOSES, [100.0] * len(_MACD_BEARISH_CLOSES)
        )
        survivor_series = _series_with_volumes(
            "SOL/USD",
            _MACD_BULLISH_CLOSES,
            [100.0] * (len(_MACD_BULLISH_CLOSES) - 1) + [1000.0],
        )
        _install(monkeypatch, {"NEAR/USD": killer_series, "SOL/USD": survivor_series})

        result = _scanner.scan(
            asset_class="crypto",
            timeframes=["1d"],
            filters=_FILTERS,
            symbols=["SOL/USD", "NEAR/USD"],
            regime_gate=False,
        )

        assert [entry["symbol"] for entry in result["attrition"]] == ["SOL/USD", "NEAR/USD"]
