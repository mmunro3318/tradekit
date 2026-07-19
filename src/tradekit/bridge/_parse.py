"""Panel text parser (SPEC-bridge-read Interface pins, T3). Numeric text
parse rule (pinned): optional ``$``, thousands commas, optional leading
``-``, optional trailing ``%`` (rejected for money fields); anything else
— parentheses negatives, suffixed units, empty string — raises
PanelParseError(field, raw_text). Decimal via contracts.quantize (cent
quantization for *_usd fields); never float.

RED stub for T3 — real body lands in T4 (read verbs consume it).
"""

from __future__ import annotations

from decimal import Decimal


def parse_money(field: str, raw: str) -> Decimal:
    """Parse a money-field raw panel string into a cent-quantized Decimal
    per the pinned numeric parse rule. RED stub."""
    raise NotImplementedError


__all__ = ["parse_money"]
