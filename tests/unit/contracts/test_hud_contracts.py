"""CONTRACT tests for the hud-orderbook payload models (SPEC-hud-orderbook
T1: GateResult, ScanReportEntry, AdvisoryTicket, HudState). Pins: frozen,
Literal domains, Decimal round-trip. No behavior under test — engine/
render logic lives in tests/unit/hud/.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import AdvisoryTicket, GateResult, HudState, ScanReportEntry


def _gate(name: str = "data_integrity", passed: bool = True) -> GateResult:
    return GateResult(
        name=name,
        passed=passed,
        observed="DSR=0.61",
        threshold=">= 0.5",
        rationale="sufficient sample",
    )


def _report_entry(grade: str = "buy") -> ScanReportEntry:
    return ScanReportEntry(
        symbol="LINK/USD",
        timeframe="1h",
        indicators=(("DSR", "0.61"), ("ATR", "0.05")),
        gates=(_gate(),),
        grade=grade,
        grade_rationale="all gates passed",
    )


def _ticket(**overrides: object) -> AdvisoryTicket:
    fields: dict[str, object] = dict(
        pair="LINK/USD",
        side="buy",
        mode="spot",
        order_type="limit",
        limit_price=Decimal("8.30000"),
        quantity=Decimal("12"),
        est_total_usd=Decimal("99.60"),
        oso="bracket",
        tp_price=Decimal("8.71500"),
        tp_distance_pct=Decimal("5.00"),
        sl_price=Decimal("8.05100"),
        sl_distance_pct=Decimal("-3.00"),
        est_pnl_tp_usd=Decimal("4.90"),
        est_pnl_sl_usd=Decimal("-3.07"),
        est_fee_usd=Decimal("0.04"),
        trigger_signal="last",
        post_only=False,
        tif="gtc",
        warnings=(),
        thesis_id="thesis-1",
        verdict_id="verdict-1",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )
    fields.update(overrides)
    return AdvisoryTicket(**fields)  # type: ignore[arg-type]


class TestGateResultContract:
    def test_frozen(self) -> None:
        """CONTRACT: GateResult is immutable (DESIGN §5, replay determinism)."""
        gate = _gate()
        with pytest.raises(ValidationError):
            gate.passed = False  # type: ignore[misc]

    def test_required_fields(self) -> None:
        """CONTRACT: all five pinned fields are required, no silent defaults."""
        gate = _gate(name="policy_verdict", passed=False)
        assert gate.name == "policy_verdict"
        assert gate.passed is False
        assert gate.observed == "DSR=0.61"
        assert gate.threshold == ">= 0.5"
        assert gate.rationale == "sufficient sample"


class TestScanReportEntryContract:
    def test_frozen(self) -> None:
        """CONTRACT: ScanReportEntry is immutable."""
        entry = _report_entry()
        with pytest.raises(ValidationError):
            entry.grade = "hold"  # type: ignore[misc]

    @pytest.mark.parametrize("bad_grade", ["strong_buy", "BUY", "", "buys"])
    def test_grade_literal_domain_rejects_out_of_domain(self, bad_grade: str) -> None:
        """CONTRACT: grade is Literal["buy","sell","hold","wait"] only —
        anything else must raise ValidationError, not silently coerce."""
        with pytest.raises(ValidationError):
            ScanReportEntry(
                symbol="LINK/USD",
                timeframe="1h",
                indicators=(),
                gates=(),
                grade=bad_grade,  # type: ignore[arg-type]
                grade_rationale="x",
            )

    def test_indicators_are_tuple_of_name_value_pairs(self) -> None:
        """CONTRACT: indicators is tuple[tuple[str,str],...] — round-trips
        the rendered value string verbatim (no numeric coercion)."""
        entry = _report_entry()
        assert entry.indicators == (("DSR", "0.61"), ("ATR", "0.05"))

    def test_gates_hold_gate_result_instances(self) -> None:
        """CONTRACT: gates is tuple[GateResult,...]."""
        entry = _report_entry()
        assert len(entry.gates) == 1
        assert isinstance(entry.gates[0], GateResult)


class TestAdvisoryTicketContract:
    def test_frozen(self) -> None:
        """CONTRACT: AdvisoryTicket is immutable — a ticket is a projection,
        never mutated after construction."""
        ticket = _ticket()
        with pytest.raises(ValidationError):
            ticket.quantity = Decimal("99")  # type: ignore[misc]

    def test_mode_literal_rejects_margin(self) -> None:
        """CONTRACT: mode is Literal["spot"] only — margin is explicitly
        out of scope (SPEC §Out of scope); "margin" must raise, not pass
        through as an untyped string."""
        with pytest.raises(ValidationError):
            _ticket(mode="margin")

    def test_order_type_literal_rejects_market(self) -> None:
        """CONTRACT: order_type is Literal["limit"] only (spot+limit+bracket
        only per SPEC §Out of scope)."""
        with pytest.raises(ValidationError):
            _ticket(order_type="market")

    def test_oso_literal_rejects_non_bracket(self) -> None:
        """CONTRACT: oso is Literal["bracket"] only — non-bracket OSO is
        out of scope."""
        with pytest.raises(ValidationError):
            _ticket(oso="oco")

    def test_side_literal_rejects_out_of_domain(self) -> None:
        """CONTRACT: side is Literal["buy","sell"] only."""
        with pytest.raises(ValidationError):
            _ticket(side="short")

    def test_trigger_signal_literal_rejects_out_of_domain(self) -> None:
        """CONTRACT: trigger_signal is Literal["last"] only (transcription
        §element 13 pins "Last price" as the only conditional trigger)."""
        with pytest.raises(ValidationError):
            _ticket(trigger_signal="mark")

    def test_tif_literal_rejects_out_of_domain(self) -> None:
        """CONTRACT: tif is Literal["gtc"] only (transcription §element 14
        pins "Good till canceled")."""
        with pytest.raises(ValidationError):
            _ticket(tif="ioc")

    def test_decimal_fields_round_trip_exact_string_precision(self) -> None:
        """CONTRACT: Decimal("8.30000") preserves trailing zeros — AC-2
        requires the exact Decimal string ("8.30000", never "8.3") reach
        render() untouched, so the contract itself must not normalize."""
        ticket = _ticket(limit_price=Decimal("8.30000"))
        assert ticket.limit_price == Decimal("8.30000")
        assert str(ticket.limit_price) == "8.30000"

    def test_warnings_is_tuple_of_str(self) -> None:
        """CONTRACT: warnings is tuple[str,...] — immutable, unlike a list."""
        ticket = _ticket(warnings=("no available balance",))
        assert ticket.warnings == ("no available balance",)

    def test_created_at_requires_timezone_aware_datetime(self) -> None:
        """CONTRACT: created_at is AwareDatetime — a naive datetime must be
        rejected (replay determinism across timezones, DESIGN §5 lineage)."""
        with pytest.raises(ValidationError):
            _ticket(created_at=datetime(2026, 7, 20, 12, 0))  # naive


class TestHudStateContract:
    def test_frozen(self) -> None:
        """CONTRACT: HudState is immutable."""
        state = HudState(
            generated_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            tickets=(),
            report=(),
        )
        with pytest.raises(ValidationError):
            state.tickets = (_ticket(),)  # type: ignore[misc]

    def test_holds_tickets_and_report_tuples(self) -> None:
        """CONTRACT: HudState.tickets is tuple[AdvisoryTicket,...] and
        .report is tuple[ScanReportEntry,...] — the shared secret between
        build_state and render (DESIGN §Module table)."""
        ticket = _ticket()
        entry = _report_entry()
        state = HudState(
            generated_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            tickets=(ticket,),
            report=(entry,),
        )
        assert state.tickets == (ticket,)
        assert state.report == (entry,)

    def test_generated_at_requires_timezone_aware_datetime(self) -> None:
        """CONTRACT: generated_at is AwareDatetime (AC-8 determinism: no
        wall-clock reads, generated_at == captured_at, both must be aware)."""
        with pytest.raises(ValidationError):
            HudState(
                generated_at=datetime(2026, 7, 20, 12, 0),  # naive
                tickets=(),
                report=(),
            )
