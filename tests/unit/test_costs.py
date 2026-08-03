"""tradekit.costs — THE shared friction model (TD-8, SME §5, G-review praise:
'the cost model singularity'). PaperBroker, backtester, and metrics all price
through this; these numbers ARE the simulated market's honesty.
"""

from decimal import Decimal

import pytest

from tradekit.costs import fee_rate, price_friction


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


# ---------------------------------------------------------------------------
# AC-10 (SPEC-inkind-fees) — costs.fee_rate(venue, asset_class) -> Decimal,
# a one-side accessor onto the SAME _TABLE price_friction reads from.
# ---------------------------------------------------------------------------


def test_fee_rate_alpaca_crypto_matches_the_table() -> None:
    """BEHAVIOR: `fee_rate` reads the SAME `_TABLE` cell `price_friction`
    prices off — `_TABLE[("alpaca", "crypto")]` = (fee_rate=0.0025, ...),
    the exact rate the in-kind withhold arithmetic (SPEC interface pins)
    multiplies against `qty`."""
    assert fee_rate("alpaca", "crypto") == Decimal("0.0025")


def test_fee_rate_alpaca_equity_is_zero() -> None:
    assert fee_rate("alpaca", "equity") == Decimal("0")


def test_fee_rate_kraken_crypto_matches_the_table() -> None:
    assert fee_rate("kraken", "crypto") == Decimal("0.0026")


def test_fee_rate_unknown_venue_raises_the_same_error_price_friction_raises() -> None:
    """AC-10: `fee_rate("nosuch", "crypto")` must raise the SAME loud error
    taxonomy `price_friction` raises on an unknown `(venue, asset_class)` —
    never a silent `Decimal("0")`, the exact fabrication class TD-8 exists
    to kill."""
    with pytest.raises(ValueError, match="cost table"):
        fee_rate("nosuch", "crypto")


