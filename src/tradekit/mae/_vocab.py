"""Typed filter vocabulary for `_scanner.scan` (SPRINT-TICKET-001 P1;
D4 first line of defense — a closed-vocabulary scan filter is a StrEnum,
not a bare string, so an unknown value is a type/validation-time concern,
not a silent runtime drop). Re-exported from `tradekit.mae`.
"""

from __future__ import annotations

from enum import StrEnum


class MacdSignal(StrEnum):
    BULLISH_CROSS = "bullish_cross"
    BEARISH_CROSS = "bearish_cross"


class BBPosition(StrEnum):
    BELOW_LOWER = "below_lower"
    ABOVE_UPPER = "above_upper"
    INSIDE = "inside"


__all__ = ["BBPosition", "MacdSignal"]
