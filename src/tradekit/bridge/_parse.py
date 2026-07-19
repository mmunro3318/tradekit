"""Panel text parser (SPEC-bridge-read Interface pins, T3). Numeric text
parse rule (pinned): optional ``$``, thousands commas, optional leading
``-``, optional trailing ``%`` (rejected for money fields); anything else
— parentheses negatives, suffixed units, empty string — raises
PanelParseError(field, raw_text). Decimal via contracts.quantize (cent
quantization for *_usd fields); never float.

RED stub for T3 — real body lands in T4 (read verbs consume it).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from tradekit.bridge._errors import PanelParseError
from tradekit.contracts import quantize

_CENT = Decimal("0.01")

# optional leading "-", optional "$", digits with optional thousands
# commas, optional ".dd" fraction — no trailing "%" (rejected for money).
_MONEY_RE = re.compile(r"^-?\$?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\$?\d+(\.\d+)?$")


def parse_money(field: str, raw: str) -> Decimal:
    """Parse a money-field raw panel string into a cent-quantized Decimal
    per the pinned numeric parse rule."""
    if not _MONEY_RE.match(raw):
        raise PanelParseError(field, raw)
    stripped = raw.replace("$", "").replace(",", "")
    try:
        value = Decimal(stripped)
    except InvalidOperation as exc:
        raise PanelParseError(field, raw) from exc
    return quantize(value, _CENT)


__all__ = ["parse_money"]
