"""CONTRACT test (test-audit item 1; SPRINT-TICKET-001 P1-P3 fences: "the
contract test IS in scope"): `tradekit.hud._build._default_scan_setup`
against the REAL, UN-MOCKED `_scanner.scan` pipeline — only
`mae._runtime.get_closed_bars` is seamed (bars) and
`tradekit.mae._regime.compute_regime` is seamed by dotted string path (the
scanner's own documented test convention for plumbing the regime gate,
`_scanner.py` module docstring's "Regime gate" section — this is NOT a
mock-of-tradekit-internals violation, it is the sanctioned seam the scanner
itself is built to be tested through).

THIS is the test that would have been RED for S1's whole life
(TICKET-001 §2a): `hud/_build.py`'s `_SETUP_FILTERS` shipped
`{"macd_signal": "bullish", ...}` — the WRONG string, one that the real
scanner's own vocabulary rejects. Every previous test of
`_default_scan_setup` mocked `scan_setup` itself (the seam), so the
mismatch between `_SETUP_FILTERS`'s spelling and the scanner's actual
accepted vocabulary was never exercised end-to-end. This test wires
`_default_scan_setup` -> `mae.scan_markets` -> `_scanner.scan` for real, so
a mismatch between hud's filter dict and the scanner's vocabulary shows up
as a hard failure here, not as a silent zero-tickets HUD.

Bar fixture provenance: same MACD-bullish-cross closes independently
derived in tests/unit/mae/test_scan_markets_verb.py's module docstring
(`macd(closes).histogram[-1] == 2.632866287861548 > 0`), combined with a
volume-spike tail (19 bars @ 100.0 + 1 spike bar @ 1000.0 ->
`volume_ratio(20)[-1] == 1000.0/145.0 == 6.896551724137931 >= 1.5`) so the
fixture clears BOTH of `_SETUP_FILTERS`'s filters once the vocabulary bug
is fixed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries

_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_VOLUMES = [100.0] * (len(_MACD_BULLISH_CLOSES) - 1) + [1000.0]


def _momentum_friendly_bars(symbol: str) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(hours=4 * i),
            open=Decimal(str(c)),
            high=Decimal(str(c + 0.3)),
            low=Decimal(str(c - 0.3)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
        for i, (c, v) in enumerate(zip(_MACD_BULLISH_CLOSES, _VOLUMES, strict=True))
    ]
    asset = AssetRef(
        symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.00001")
    )
    return BarSeries(asset=asset, timeframe="4h", bars=bars, source="fake-kraken")


def _momentum_friendly_regime(symbol: str, lookback_days: int, n_states: int) -> dict:
    """Fake `_regime.compute_regime` (dotted-path seam, per the scanner's
    own documented test convention) returning a state whose
    `recommended_strategies` includes "momentum" — so the real regime gate
    does NOT strip the `macd_bullish` tag (`_TAG_STRATEGY["macd_bullish"] ==
    "momentum"`, per `_scanner.py`'s Signal tag / strategy-family mapping)."""
    return {
        "symbol": symbol,
        "current_state": "low_vol_trend",
        "confidence": 0.9,
        "recommended_strategies": ["momentum"],
        "avoid_strategies": [],
    }


class TestDefaultScanSetupRealScannerContract:
    def test_real_scanner_produces_nonempty_signal_tags_for_a_bullish_volume_confirmed_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT: with the ONLY sanctioned seams installed
        (`get_closed_bars`, `_regime.compute_regime`), calling the real
        `hud._build._default_scan_setup("LINK/USD")` against a bullish +
        volume-confirmed fixture must return non-empty `signal_tags`. This
        is the exact end-to-end path that was silently broken for S1's
        entire life — `_SETUP_FILTERS`'s `"bullish"` spelling never matched
        the scanner's `"bullish_cross"` vocabulary, so this call always
        returned `signal_tags=[]` in production."""
        import tradekit.hud._build as hud_build

        monkeypatch.setattr(
            "tradekit.mae._runtime.get_closed_bars",
            lambda symbol, timeframe, lookback_days: _momentum_friendly_bars(symbol),
        )
        monkeypatch.setattr(
            "tradekit.mae._regime.compute_regime", _momentum_friendly_regime
        )

        result = hud_build._default_scan_setup("LINK/USD")

        assert result.signal_tags != [], (
            "the real scanner, given a bullish-cross + volume-spike fixture and a "
            "momentum-friendly regime, must surface non-empty signal_tags — an "
            "empty result here means hud's filter vocabulary still doesn't match "
            "the scanner's, i.e. S1 is still structurally silent"
        )
