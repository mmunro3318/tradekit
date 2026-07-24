"""tests for SPRINT-TICKET-001 P1 (typed filter vocabulary) / P2 (loud
unknown-filter-value validation at `scan()` entry).

Pins (docs/specs/SPRINT-TICKET-001.md):
  P1 — `tradekit.mae._vocab.MacdSignal`/`BBPosition` StrEnums, re-exported
       from `tradekit.mae`.
  P2 — `_scanner.scan()` validates `macd_signal`/`bb_position` filter VALUES
       up front, BEFORE any bar fetch, raising
       `ValueError(f"scan_markets: unknown {key} value {value!r}; expected "
       f"one of {sorted(allowed)}")`. Plain canonical strings that match an
       enum value remain accepted (StrEnum equality).

Determinism seam: `tradekit.mae._runtime.get_closed_bars` monkeypatched to a
recorder that FAILS THE TEST if called — proves the raise happens before any
bar fetch, per the sanctioned-seam discipline (never mock tradekit
internals beyond `_runtime.get_closed_bars`/`_clock`).
"""

from __future__ import annotations

from enum import StrEnum

import pytest

from tradekit.mae import _scanner


def _install_recorder_that_fails_if_called(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(symbol: str, timeframe: str, lookback_days: int) -> None:
        pytest.fail(
            "scan() fetched bars before validating filter values — P2 requires "
            "the unknown-value raise to happen BEFORE any bar fetch"
        )

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fail)


# ---------------------------------------------------------------------------
# P1 — CONTRACT: typed vocabulary is importable and StrEnum-shaped.
# ---------------------------------------------------------------------------


class TestP1VocabularyContract:
    def test_macd_signal_and_bb_position_importable_from_tradekit_mae(self) -> None:
        """CONTRACT: `MacdSignal`/`BBPosition` are re-exported from
        `tradekit.mae` (P1 pin: "New module `src/tradekit/mae/_vocab.py`,
        re-exported from `tradekit.mae`")."""
        from tradekit.mae import BBPosition, MacdSignal

        assert issubclass(MacdSignal, StrEnum)
        assert issubclass(BBPosition, StrEnum)

    def test_macd_signal_enum_values_match_pinned_canonical_strings(self) -> None:
        """CONTRACT: the pinned literal enum values from the dispatch pin."""
        from tradekit.mae import MacdSignal

        assert MacdSignal.BULLISH_CROSS == "bullish_cross"
        assert MacdSignal.BEARISH_CROSS == "bearish_cross"

    def test_bb_position_enum_values_match_pinned_canonical_strings(self) -> None:
        """CONTRACT: the pinned literal enum values from the dispatch pin."""
        from tradekit.mae import BBPosition

        assert BBPosition.BELOW_LOWER == "below_lower"
        assert BBPosition.ABOVE_UPPER == "above_upper"
        assert BBPosition.INSIDE == "inside"


# ---------------------------------------------------------------------------
# P2 — BEHAVIOR: scan() raises loud, before any bar fetch, on unknown values.
# ---------------------------------------------------------------------------


class TestP2UnknownMacdSignalRaisesBeforeBarFetch:
    def test_unknown_macd_signal_value_raises_before_any_bar_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: this is the exact production defect (TICKET-001 §2a) —
        `hud/_build.py` shipped `"bullish"` (not the canonical
        `"bullish_cross"`) and every scan silently rejected every candidate.
        `scan()` must now raise `ValueError` matching "unknown macd_signal"
        BEFORE `_runtime.get_closed_bars` is ever called — asserted here by
        a recorder that fails the test if invoked."""
        _install_recorder_that_fails_if_called(monkeypatch)

        with pytest.raises(ValueError, match="unknown macd_signal"):
            _scanner.scan(
                asset_class="crypto",
                timeframes=["4h"],
                filters={"macd_signal": "bullish"},
                symbols=["BTC/USD"],
                regime_gate=False,
            )

    def test_unknown_bb_position_value_raises_before_any_bar_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: same guard for `bb_position` — a bogus value must raise
        `ValueError` matching "unknown bb_position" before any bar fetch."""
        _install_recorder_that_fails_if_called(monkeypatch)

        with pytest.raises(ValueError, match="unknown bb_position"):
            _scanner.scan(
                asset_class="crypto",
                timeframes=["1d"],
                filters={"bb_position": "sideways"},
                symbols=["BTC/USD"],
                regime_gate=False,
            )

    def test_error_message_names_the_bad_value_and_the_allowed_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: the exact message shape pinned by P2 —
        `f"scan_markets: unknown {key} value {value!r}; expected one of "
        f"{sorted(allowed)}"` — names both the offending repr'd value and
        the sorted allowed set, so an operator sees the fix inline."""
        _install_recorder_that_fails_if_called(monkeypatch)

        with pytest.raises(ValueError) as excinfo:
            _scanner.scan(
                asset_class="crypto",
                timeframes=["4h"],
                filters={"macd_signal": "bullish"},
                symbols=["BTC/USD"],
                regime_gate=False,
            )

        message = str(excinfo.value)
        assert "'bullish'" in message
        assert "bullish_cross" in message
        assert "bearish_cross" in message


class TestP2PlainCanonicalStringsStillAccepted:
    def test_plain_bullish_cross_string_does_not_raise_the_unknown_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR: a plain str `"bullish_cross"` (not the StrEnum member
        itself) must NOT trip the unknown-value guard — StrEnum equality
        means canonical plain strings remain accepted (P2: "Plain strings
        that match enum values remain accepted"). Bars are seamed via the
        real `_series`-shaped fixture module so this proceeds past
        validation into the (implemented) pipeline rather than raising
        NotImplementedError from an unrelated stub path."""
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        from tradekit.contracts import AssetRef, Bar, BarSeries

        start = datetime(2026, 1, 1, tzinfo=UTC)
        closes = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
        bars = [
            Bar(
                ts_open=start + timedelta(days=i),
                open=Decimal(str(c)),
                high=Decimal(str(c + 0.3)),
                low=Decimal(str(c - 0.3)),
                close=Decimal(str(c)),
                volume=Decimal("100.0"),
            )
            for i, c in enumerate(closes)
        ]
        asset = AssetRef(
            symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
        )
        series = BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")
        monkeypatch.setattr(
            "tradekit.mae._runtime.get_closed_bars",
            lambda symbol, timeframe, lookback_days: series,
        )
        monkeypatch.setattr(
            "tradekit.mae._runtime._clock", lambda: datetime(2026, 7, 16, tzinfo=UTC)
        )

        result = _scanner.scan(
            asset_class="crypto",
            timeframes=["1d"],
            filters={"macd_signal": "bullish_cross"},
            symbols=["BTC/USD"],
            regime_gate=False,
        )

        assert len(result["matches"]) == 1
