"""UIA bridge read-verb payloads (SPEC-bridge-read Interface pins). Money is
Decimal, cent-quantized via ``contracts.quantize`` at the parser boundary
(``_parse.py``, feature T3) — these models only pin shape, not derivation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime

from tradekit.contracts._base import FrozenModel


class PropPositionRow(FrozenModel):
    symbol: str
    side: Literal["long", "short"]
    qty: Decimal
    entry_price: Decimal
    unrealized_pnl_usd: Decimal


class PropPanelSnapshot(FrozenModel):
    captured_at: AwareDatetime  # supplied by caller/CLI, never wall-clocked in the driver
    account_name: str
    instrument: str
    balance_usd: Decimal
    equity_usd: Decimal | None
    mdl_remaining_usd: Decimal
    mdd_remaining_usd: Decimal
    target_remaining_usd: Decimal | None
    positions: tuple[PropPositionRow, ...]


class TicketReadback(FrozenModel):
    account_name: str
    instrument: str
    side: Literal["buy", "sell"] | None
    order_type: str
    qty: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None


__all__ = [
    "PropPanelSnapshot",
    "PropPositionRow",
    "TicketReadback",
]
