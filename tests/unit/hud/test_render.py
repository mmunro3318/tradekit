"""GOLDEN (key-content presence, not full-string) tests for hud.render
(SPEC-hud-orderbook T2). Derivation source: handoff transcription §elements
1-16 (docs/handoff/HANDOFF-2026-07-20-hud-commit.md) and the palette pins
in docs/design/HUD-ORDERBOOK.md Decision 2. House doctrine (report module
precedent, DESIGN §Test seams): assert key content presence, never full
golden HTML strings — render is thin templating over HudState, refactors
of markup/whitespace must not break these tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tradekit.hud import render  # isort: split

from tradekit.contracts import AdvisoryTicket, GateResult, HudState, ScanReportEntry

# The 16-element transcription's field labels that must appear per ticket,
# in top-to-bottom order (AC-2). Only the labels tied to genuine ticket
# *fields* are asserted for ordering; header/context rows (bid/ask, balance,
# side toggle, mode/order-type, conditional trigger dropdown, reset button,
# status strip) are covered by the palette/tab/content presence checks below.
FIELD_LABELS_IN_ORDER = (
    "Limit price",
    "Quantity",
    "Est. total",
    "Attach OSO",
    "Take profit",
    "Stop loss",
    "Est. P&L",
    "Post only",
    "Time in force",
    "Review & Buy",
)

PALETTE_TOKENS = ("#0b0b0c", "#161618", "#ff7a1a", "#c1581f", "#ffb25e")
FORBIDDEN_KRAKEN_BLUE = "#5741d9"


def _gate(name: str = "data_integrity", passed: bool = True) -> GateResult:
    return GateResult(
        name=name,
        passed=passed,
        observed="DSR=0.61",
        threshold=">= 0.5",
        rationale="sufficient sample",
    )


def _report_entry(symbol: str, grade: str = "buy") -> ScanReportEntry:
    return ScanReportEntry(
        symbol=symbol,
        timeframe="1h",
        indicators=(("DSR", "0.61"),),
        gates=(_gate(),),
        grade=grade,
        grade_rationale="all gates passed",
    )


def _link_ticket() -> AdvisoryTicket:
    """The AC-2 worked ticket: LINK/USD buy, limit 8.30000, qty 12,
    tp 8.71500, sl 8.05100 — Decimal strings pinned exactly as given in the
    dispatch's golden arithmetic block."""
    return AdvisoryTicket(
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
        thesis_id="thesis-link",
        verdict_id="verdict-link",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )


def _eth_ticket() -> AdvisoryTicket:
    return AdvisoryTicket(
        pair="ETH/USD",
        side="sell",
        mode="spot",
        order_type="limit",
        limit_price=Decimal("3200.00"),
        quantity=Decimal("0.5"),
        est_total_usd=Decimal("1600.00"),
        oso="bracket",
        tp_price=Decimal("3040.00"),
        tp_distance_pct=Decimal("-5.00"),
        sl_price=Decimal("3360.00"),
        sl_distance_pct=Decimal("5.00"),
        est_pnl_tp_usd=Decimal("78.72"),
        est_pnl_sl_usd=Decimal("-81.28"),
        est_fee_usd=Decimal("0.64"),
        trigger_signal="last",
        post_only=False,
        tif="gtc",
        warnings=(),
        thesis_id="thesis-eth",
        verdict_id="verdict-eth",
        created_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )


def _two_ticket_state() -> HudState:
    return HudState(
        generated_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        tickets=(_link_ticket(), _eth_ticket()),
        report=(
            _report_entry("LINK/USD", "buy"),
            _report_entry("ETH/USD", "sell"),
            _report_entry("SOL/USD", "wait"),
        ),
    )


class TestTicketTabsAndReportRows:
    def test_two_tickets_render_two_pair_tabs(self) -> None:
        """AC-1: exactly two ticket tabs labeled by pair for a two-ticket
        state."""
        html = render(_two_ticket_state())
        assert html.count('<label for="tab-') == 2
        assert html.count("LINK/USD") >= 1
        assert html.count("ETH/USD") >= 1

    def test_all_report_entries_present(self) -> None:
        """AC-1: all three report entries (including the non-ticketed
        SOL/USD wait row) appear in the rendered document."""
        html = render(_two_ticket_state())
        assert "LINK/USD" in html
        assert "ETH/USD" in html
        assert "SOL/USD" in html


class TestFieldLabelsAndDecimalFidelity:
    def test_field_labels_appear_in_ticket_order(self) -> None:
        """AC-2: the 16-element transcription's field labels appear, in
        order, within the LINK/USD ticket section."""
        html = render(_two_ticket_state())
        link_section_start = html.index("LINK/USD")
        positions = []
        search_from = link_section_start
        for label in FIELD_LABELS_IN_ORDER:
            idx = html.index(label, search_from)
            positions.append(idx)
            search_from = idx + len(label)
        assert positions == sorted(positions)

    def test_exact_decimal_strings_appear_verbatim(self) -> None:
        """AC-2: exact Decimal strings from the ticket appear verbatim —
        never float-reformatted (e.g. "8.30000" must appear, "8.3" alone
        is not sufficient evidence of correctness but the trailing zeros
        must survive)."""
        html = render(_two_ticket_state())
        for value in ("8.30000", "12", "99.60", "8.71500", "8.05100", "4.90", "-3.07"):
            assert value in html, f"expected exact Decimal string {value!r} in output"

    def test_float_reformatted_price_does_not_appear(self) -> None:
        """AC-2 negative check: "8.3" (float-truncated) must not be
        substituted for the pinned "8.30000" string anywhere a price is
        rendered — guards against str(Decimal) -> float -> str drift."""
        html = render(_two_ticket_state())
        assert "8.3 " not in html
        assert ">8.3<" not in html


class TestPalette:
    def test_pinned_palette_tokens_present(self) -> None:
        """AC-3: CSS defines the pinned palette tokens."""
        html = render(_two_ticket_state())
        for token in PALETTE_TOKENS:
            assert token in html, f"expected palette token {token!r} in document CSS"

    def test_forbidden_kraken_blue_absent(self) -> None:
        """AC-3: the forbidden Kraken-blue token never appears (DESIGN
        Decision 2: burnt orange/umber replaces Kraken blue)."""
        html = render(_two_ticket_state())
        assert FORBIDDEN_KRAKEN_BLUE not in html


class TestSelfContained:
    def test_no_external_resource_urls(self) -> None:
        """AC-1: one self-contained HTML string — no external resource
        URLs (no http:// or https:// in src/href attributes, i.e. anywhere
        in the document, since nothing legitimately needs one)."""
        html = render(_two_ticket_state())
        assert "http://" not in html
        assert "https://" not in html


class TestEmptyState:
    def test_empty_tickets_state_still_renders_report_and_placeholder(self) -> None:
        """AC-10: empty scan (no tickets) still renders the report section
        with all-wait rows and an explicit "no advisory tickets" placeholder
        — never an empty file."""
        state = HudState(
            generated_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
            tickets=(),
            report=(
                _report_entry("SOL/USD", "wait"),
                _report_entry("NEAR/USD", "wait"),
            ),
        )
        html = render(state)
        assert html.strip() != ""
        assert "SOL/USD" in html
        assert "NEAR/USD" in html
        assert "no advisory tickets" in html.lower()
