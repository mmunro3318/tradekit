"""tests for the PUBLIC tradekit.mae.size_position verb (SPRINT-P1C story 1,
"Sizing wiring pins").

Wiring pins exercised here (addendum):
  - price = close of the LAST CLOSED daily bar (via `_runtime.get_daily_bars`)
  - ATR = `_indicators.volatility.atr(period=14)` on the same closed dailies,
    last non-None value
  - both feed `_sizing`'s existing, frozen math (tests/unit/mae/test_sizing.py)
    untouched
  - kelly_win_rate/kelly_payoff_ratio both None -> ATR-only sizing +
    `kelly_inputs_missing` warning; exactly one None -> ValueError

Runtime bars are faked by monkeypatching `"tradekit.mae._runtime.get_daily_bars"`
by dotted STRING path — this does not import `tradekit.mae._runtime` (no
`import`/`from...import` statement), so it needs no ASSUMPTIONS internal-
import exception; only tests/unit/mae/test_runtime.py does.

Status: `size_position` is a P1C batch A STUB (raises NotImplementedError
unconditionally) — every test below currently fails with NotImplementedError,
the expected red state for this batch. Assertions describe the REAL output
the dev agent implements next, per canonical §3's size_position schema.

ATR/price fixture derivation (fixture-freeze rule, executed not mental):
16 daily bars, each with high=101, low=99, open=close=100 (True Range is
therefore high-low=2.0 on every bar, no gap since the previous close=100
always sits inside [low, high]). Wilder ATR(14) seed = average of the first
14 TR values = 2.0 exactly; the recurrence atr[i] = (atr[i-1]*13 + TR[i])/14
with TR[i]=2.0 for all i keeps atr at 2.0 forever — verified by
`derive_p1c_batchA.py` (scratchpad), section "ATR(14) hand check with
constant TR=2.0": seed=2.0, atr after recurrence through index 19 = 2.0.
Last closed bar's close = 100 (all closes are 100). This reproduces the
existing `test_sizing.py::test_atr_position_golden_vector` fixture
(equity=1000, risk_pct=0.01, atr=2.0, mult=2.0, price=100 -> stop_distance
4.0, atr_units 2.5, atr_size_usd 250) through the verb instead of calling
`_sizing.atr_position` directly.

Combined kelly+ATR goldens (equity=1000, same ATR/price fixture; computed
by `derive_p1c_batchA.py`, section 1, using exact Fractions):
  - W=.574, R=1.572 (existing test_sizing.py golden) ->
    kelly_full_f = 19847/65500 = 0.30300763358778626
    kelly_quarter_f = 19847/262000 = 0.07575190839694657
    kelly_position_size_usd = quarter_f * equity = 19847/262 = 75.75190839694656
    atr_position_size_usd = 250.0
    recommended_size_usd = min(250.0, 75.7519...) = 75.75190839694656
  - W=.40, R=1.0 (existing test_sizing.py negative-kelly golden) ->
    raw f* = -1/5, clamped to kelly_full_f = kelly_quarter_f = 0.0
    kelly_position_size_usd = 0.0
    recommended_size_usd = min(250.0, 0.0) = 0.0
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import size_position

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))


def _flat_atr2_price100_bars(n: int = 16) -> BarSeries:
    start = datetime(2026, 6, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_get_daily_bars(symbol: str, lookback_days: int) -> BarSeries:
    return _flat_atr2_price100_bars()


def test_kelly_golden_vector_via_verb(monkeypatch) -> None:
    """W=.574, R=1.572 — the same golden as test_sizing.py's
    test_kelly_golden_vector, re-expressed through the public verb."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    result = size_position(
        symbol="BTC/USD",
        account_equity_usd=Decimal("1000"),
        risk_pct_per_trade=0.01,
        atr_multiplier=2.0,
        kelly_win_rate=0.574,
        kelly_payoff_ratio=1.572,
        kelly_fraction=0.25,
    )

    assert result["symbol"] == "BTC/USD"
    assert result["current_price"] == pytest.approx(100.0)
    assert result["atr_14"] == pytest.approx(2.0)
    assert result["stop_distance_usd"] == pytest.approx(4.0)
    assert result["stop_pct"] == pytest.approx(0.04)
    assert result["atr_position_size_usd"] == pytest.approx(250.0)
    assert result["kelly_full_f"] == pytest.approx(0.30300763358778626, abs=1e-9)
    assert result["kelly_quarter_f"] == pytest.approx(0.07575190839694657, abs=1e-9)
    assert result["kelly_position_size_usd"] == pytest.approx(75.75190839694656, abs=1e-6)
    assert result["recommended_size_usd"] == pytest.approx(75.75190839694656, abs=1e-6), (
        "recommended = min(atr_size, kelly_size) — Kelly is the conservative pick here"
    )
    assert result["risk_usd"] == pytest.approx(10.0)
    assert result["r_multiple_target"] == pytest.approx(2.0)


def test_negative_kelly_clamps_and_warns_via_verb(monkeypatch) -> None:
    """W=.40, R=1.0 -> raw f*=-0.2, clamped to 0, negative_kelly warning,
    recommended size 0 (min(atr_size, 0)) — same golden as test_sizing.py's
    test_negative_kelly_clamps_to_zero, re-expressed through the verb."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    result = size_position(
        symbol="BTC/USD",
        account_equity_usd=Decimal("1000"),
        risk_pct_per_trade=0.01,
        atr_multiplier=2.0,
        kelly_win_rate=0.40,
        kelly_payoff_ratio=1.0,
    )

    assert result["kelly_full_f"] == 0.0
    assert result["kelly_quarter_f"] == 0.0
    assert result["kelly_position_size_usd"] == pytest.approx(0.0)
    assert result["atr_position_size_usd"] == pytest.approx(250.0)
    assert result["recommended_size_usd"] == pytest.approx(0.0)
    assert "negative_kelly" in result["warnings"], (
        "negative edge = no position, never a short-the-strategy hallucination (DESIGN §9.3)"
    )


def test_equity_1000_atr_2_price_100_via_verb(monkeypatch) -> None:
    """equity=1000, risk 1%, ATR=2.0, mult=2.0, price=100 -> atr_size_usd=250,
    same golden as test_sizing.py's test_atr_position_golden_vector,
    re-expressed through the verb with kelly inputs both None (ATR-only)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    result = size_position(
        symbol="BTC/USD",
        account_equity_usd=Decimal("1000"),
        risk_pct_per_trade=0.01,
        atr_multiplier=2.0,
        kelly_win_rate=None,
        kelly_payoff_ratio=None,
    )

    assert result["atr_position_size_usd"] == pytest.approx(250.0)
    assert result["stop_distance_usd"] == pytest.approx(4.0)
    assert result["stop_pct"] == pytest.approx(0.04)
    assert result["risk_usd"] == pytest.approx(10.0)
    assert result["recommended_size_usd"] == pytest.approx(250.0), (
        "with no Kelly inputs, sizing is ATR-only; recommended = atr_position_size_usd"
    )
    assert "kelly_inputs_missing" in result["warnings"]


def test_kelly_both_none_atr_only_with_warning(monkeypatch) -> None:
    """Duplicate-intent check of the both-None path (addendum: 'kelly_win_rate/
    kelly_payoff_ratio both None -> ATR-only sizing with a kelly_inputs_missing
    warning') with a different equity/ATR combination than the reused golden
    above, so the ATR-only path is pinned independent of that specific number."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    result = size_position(
        symbol="BTC/USD",
        account_equity_usd=Decimal("5000"),
        risk_pct_per_trade=0.02,
        atr_multiplier=2.0,
        kelly_win_rate=None,
        kelly_payoff_ratio=None,
    )

    # risk_usd = 5000*0.02 = 100; stop_distance = 2.0*2.0 = 4.0;
    # atr_units = 100/4.0 = 25; atr_size_usd = 25*100 = 2500.
    assert result["risk_usd"] == pytest.approx(100.0)
    assert result["atr_position_size_usd"] == pytest.approx(2500.0)
    assert result["recommended_size_usd"] == pytest.approx(2500.0)
    assert "kelly_inputs_missing" in result["warnings"]


@pytest.mark.parametrize(
    ("win_rate", "payoff"),
    [(0.574, None), (None, 1.572)],
)
def test_exactly_one_kelly_input_none_raises_value_error(
    monkeypatch, win_rate: float | None, payoff: float | None
) -> None:
    """Half an edge spec is a caller bug, not a degraded mode (addendum)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    with pytest.raises(ValueError):
        size_position(
            symbol="BTC/USD",
            account_equity_usd=Decimal("1000"),
            kelly_win_rate=win_rate,
            kelly_payoff_ratio=payoff,
        )


def test_output_has_every_canonical_key(monkeypatch) -> None:
    """canonical §3 size_position output keys, per the schema authority
    (docs/research/'Market Analysis Engine — Comprehensive Design
    Document.md' §3 — schema only, its example NUMBERS are known-wrong)."""
    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _fake_get_daily_bars)

    result = size_position(
        symbol="BTC/USD",
        account_equity_usd=Decimal("1000"),
        kelly_win_rate=0.574,
        kelly_payoff_ratio=1.572,
    )

    expected_keys = {
        "symbol",
        "current_price",
        "atr_14",
        "stop_distance_usd",
        "stop_pct",
        "atr_position_size_usd",
        "atr_units",
        "kelly_full_f",
        "kelly_quarter_f",
        "kelly_position_size_usd",
        "recommended_size_usd",
        "recommended_units",
        "risk_usd",
        "r_multiple_target",
    }
    assert expected_keys <= result.keys()
