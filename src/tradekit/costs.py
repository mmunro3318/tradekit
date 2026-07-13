"""tradekit.costs — the ONE friction model (TD-8, shared leaf module).

PaperBroker fills, the backtester, and net-of-fee metrics all price through
this table, so simulations, backtests, and gates can never disagree about
costs. Numbers seeded from SME §5 (2026-07); marked provisional until P4
live fills measure reality — update the TABLE, never scatter constants.

Imports only contracts + stdlib (leaf-module rule, DESIGN §4.2).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from tradekit.contracts import Friction

# (venue, asset_class) -> (taker fee rate, modeled half-spread rate).
# WHYs: Alpaca equities are zero-commission with ~1bp large-cap half-spread;
# Alpaca crypto charges 25bp taker; Kraken spot taker is 26bp at entry tier
# (advisory pool). All rates are per-side fractions of notional.
_TABLE: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("alpaca", "equity"): (Decimal("0"), Decimal("0.0001")),
    ("alpaca", "crypto"): (Decimal("0.0025"), Decimal("0.0010")),
    ("kraken", "crypto"): (Decimal("0.0026"), Decimal("0.0010")),
}

# Slippage: zero under $100 notional (SME §5 / G5 — retail size is liquidity
# noise on large-caps and BTC/ETH); revisit before any cap raise (§8.3).
_SLIPPAGE_FREE_NOTIONAL = Decimal("100")
_SLIPPAGE_RATE = Decimal("0.0005")


def price_friction(
    venue: str,
    asset_class: str,
    notional_usd: Decimal,
    side: Literal["buy", "sell"],
) -> Friction:
    """One-side friction for a trade. Unknown venues die loudly — a venue
    without a cost table must never price as free. `side` is reserved for
    asymmetric models; the current tables are symmetric."""
    try:
        fee_rate, half_spread_rate = _TABLE[(venue, asset_class)]
    except KeyError:
        raise ValueError(
            f"no cost table for venue={venue!r} asset_class={asset_class!r} — "
            f"add it to tradekit.costs._TABLE with a WHY (TD-8), known: {sorted(_TABLE)}"
        ) from None

    fee = fee_rate * notional_usd
    half_spread = half_spread_rate * notional_usd
    slippage = (
        Decimal("0")
        if notional_usd <= _SLIPPAGE_FREE_NOTIONAL
        else _SLIPPAGE_RATE * notional_usd
    )
    return Friction(
        fee_usd=fee,
        half_spread_usd=half_spread,
        slippage_usd=slippage,
        total_usd=fee + half_spread + slippage,
    )
