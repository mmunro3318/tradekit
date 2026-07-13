"""tradekit.costs — THE shared friction model (TD-8, SME §5, G-review praise:
'the cost model singularity'). PaperBroker, backtester, and metrics all price
through this; these numbers ARE the simulated market's honesty.
"""

from decimal import Decimal

import pytest

from tradekit.costs import price_friction


def test_alpaca_crypto_ten_dollar_side() -> None:
    f = price_friction("alpaca", "crypto", Decimal("10"), "buy")
    assert f.fee_usd == Decimal("0.025"), "25bp taker on $10 (SME §5)"
    assert f.half_spread_usd == Decimal("0.010"), "10bp modeled half-spread"
    assert f.slippage_usd == Decimal("0"), "liquidity effectively infinite under $100 (G5 context)"
    assert f.total_usd == Decimal("0.035")
    # Round trip = 2 sides = $0.07 on $10 -> 0.7%: THIS is why crypto scalping
    # is dead at our size and R-008 min-notional exists.


def test_alpaca_equity_costs_near_zero() -> None:
    f = price_friction("alpaca", "equity", Decimal("25"), "buy")
    assert f.fee_usd == Decimal("0"), "zero-commission equities"
    assert f.half_spread_usd == Decimal("0.0025"), "1bp large-cap half-spread"
    assert f.total_usd == Decimal("0.0025")


def test_kraken_crypto_taker_fee() -> None:
    f = price_friction("kraken", "crypto", Decimal("100"), "sell")
    assert f.fee_usd == Decimal("0.26"), "26bp Kraken taker at entry tier (advisory pool)"


def test_unknown_venue_dies_loudly() -> None:
    with pytest.raises(ValueError, match="cost table"):
        price_friction("robinhood", "equity", Decimal("10"), "buy")
    # A venue without a cost table must NEVER price as free — silent zero
    # friction is exactly the simulation-optimism TD-8 exists to kill.


def test_symmetric_sides() -> None:
    buy = price_friction("alpaca", "crypto", Decimal("50"), "buy")
    sell = price_friction("alpaca", "crypto", Decimal("50"), "sell")
    assert buy == sell, "cost model is side-symmetric today; param reserved for asymmetry"
