"""AC-5: panel text parser golden table (SPEC-bridge-read, T3). GOLDEN —
every expected value hand-derived below (no code under test used to
produce it); the table is VERBATIM from the spec's AC-5 bullet.

Hand derivation:
    "$5,000.00" -> strip "$", strip "," -> "5000.00" -> Decimal("5000.00")
    "-$12.34"   -> strip leading "-", strip "$" -> "12.34", reapply sign
                   -> Decimal("-12.34")
    "-12.34"    -> already bare -> Decimal("-12.34")
    "(12.34)"   -> parenthesized negative is NOT in the pinned grammar
                   (grammar: optional $, thousands commas, optional
                   leading -, optional trailing % for money) -> PanelParseError
    ""          -> empty string is explicitly excluded -> PanelParseError
    "5 000,00"  -> space thousands-sep + comma decimal (EU format) is not
                   the pinned grammar (grammar requires comma as
                   thousands-sep, "." as decimal) -> PanelParseError
    "5.00%"     -> trailing "%" is pinned REJECTED for money fields
                   -> PanelParseError

NOTE (flag for CTO, not written to tests/ASSUMPTIONS.md by this agent):
the pin only names `parse_money`; a `parse_qty` surface is NOT added here
since AC-5's golden table only covers money fields and T3's task scope
(TASKS-bridge-read) satisfies AC-5 only — qty parsing is left for T4 to
define (may differ: no cent-quantization, may accept trailing % never).
See report for ratification request.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tradekit.bridge._errors import PanelParseError
from tradekit.bridge._parse import parse_money


class TestParseMoneyGoldenTable:
    def test_dollar_sign_and_thousands_comma(self) -> None:
        assert parse_money("BALANCE", "$5,000.00") == Decimal("5000.00")

    def test_negative_with_dollar_sign(self) -> None:
        assert parse_money("BALANCE", "-$12.34") == Decimal("-12.34")

    def test_negative_bare(self) -> None:
        assert parse_money("BALANCE", "-12.34") == Decimal("-12.34")

    def test_parenthesized_negative_rejected(self) -> None:
        with pytest.raises(PanelParseError) as exc_info:
            parse_money("BALANCE", "(12.34)")
        assert exc_info.value.field == "BALANCE"
        assert exc_info.value.raw_text == "(12.34)"

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(PanelParseError) as exc_info:
            parse_money("BALANCE", "")
        assert exc_info.value.field == "BALANCE"
        assert exc_info.value.raw_text == ""

    def test_eu_thousands_and_decimal_format_rejected(self) -> None:
        with pytest.raises(PanelParseError) as exc_info:
            parse_money("BALANCE", "5 000,00")
        assert exc_info.value.field == "BALANCE"
        assert exc_info.value.raw_text == "5 000,00"

    def test_trailing_percent_rejected_for_money(self) -> None:
        """Pin: trailing % is legal grammar in general but REJECTED
        specifically for money fields."""
        with pytest.raises(PanelParseError) as exc_info:
            parse_money("MDL_REMAINING", "5.00%")
        assert exc_info.value.field == "MDL_REMAINING"
        assert exc_info.value.raw_text == "5.00%"

    def test_result_is_cent_quantized_decimal(self) -> None:
        """Pin: Decimal via contracts.quantize (cent quantization for
        *_usd fields); a whole-dollar input must still carry 2 decimal
        places in the result exponent."""
        result = parse_money("BALANCE", "$5,000")
        assert result == Decimal("5000.00")
        assert result.as_tuple().exponent == -2
