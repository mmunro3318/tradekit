"""Kelly + ATR sizing math (DESIGN §9.3, TD-11). Pure; the size_position verb
wires in live ATR/price in P1C.

Purity is structural: these functions take market inputs and equity only —
no P&L history, no drawdown state, no "amount to recover" (F6). If a future
change needs those, the change is wrong.
"""

from __future__ import annotations

from decimal import Decimal


def kelly_fractions(
    *, win_rate: float, payoff_ratio: float, fraction: float = 0.25
) -> tuple[float, float]:
    """(full f*, fractional f). f* = W - (1-W)/R, clamped at 0.

    Negative edge clamps to zero — no position. Betting a negative Kelly
    (or shorting the strategy) is a hallucination, not a strategy.
    """
    if not 0.0 <= win_rate <= 1.0:
        raise ValueError(f"win_rate {win_rate} outside [0, 1]")
    if payoff_ratio <= 0.0:
        raise ValueError(f"payoff_ratio {payoff_ratio} must be positive")
    full = max(0.0, win_rate - (1.0 - win_rate) / payoff_ratio)
    return full, full * fraction


def atr_position(
    *,
    equity_usd: Decimal,
    risk_pct: float,
    atr: Decimal,
    multiplier: float,
    price: Decimal,
) -> dict[str, Decimal | float]:
    """ATR-normalized size: being stopped out loses exactly risk_usd.

    units = (equity x risk_pct) / (ATR x multiplier); size = units x price.
    """
    if atr <= 0:
        raise ValueError(f"ATR {atr} must be positive — zero ATR sizes an infinite position")
    if price <= 0 or equity_usd <= 0:
        raise ValueError("price and equity must be positive")
    if not 0.0 < risk_pct <= 0.05:
        raise ValueError(f"risk_pct {risk_pct} outside (0, 0.05] — 5%/trade is already reckless")

    risk_usd = equity_usd * Decimal(str(risk_pct))
    stop_distance = atr * Decimal(str(multiplier))
    units = risk_usd / stop_distance
    return {
        "risk_usd": risk_usd,
        "stop_distance": stop_distance,
        "stop_pct": float(stop_distance / price),
        "units": units,
        "size_usd": units * price,
    }
