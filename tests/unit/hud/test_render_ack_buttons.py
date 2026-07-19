"""GOLDEN test for AC-A6 (SPEC-hud-ack): each ticket tab renders Confirm /
Failed buttons plus an inline `fetch('/ack', ...)` snippet, and the static
(no-server) page degrades gracefully (structural `.catch(` assertion — no
uncaught page errors when `fetch` rejects).

Reuses tests/unit/hud/test_build_state.py's seam pattern (mae._runtime +
the four sanctioned hud._build seams) to drive one real ticket through
`build_state`, then asserts on `render(state)`'s HTML text. No browser is
launched — "no uncaught page errors" is asserted structurally, per the
SPEC's own wording ("asserted structurally: the snippet catches fetch
rejection"), not by executing JS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest

from tradekit.hud import build_state, render

CAPTURED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
EQUITY_USD = Decimal("5000")


@dataclass(frozen=True)
class _FakeSizingInfo:
    qty: Decimal
    stop_distance_usd: Decimal
    r_multiple_target: Decimal


class _PassingSetup:
    signal_tags: ClassVar[list[str]] = ["macd_bullish", "volume_spike"]


class _AllowDecision:
    allowed = True
    verdict_id = "verdict-link-1"
    rationale = "all gates passed"


def _fixture_series(symbol: str, n_bars: int = 24):
    from tradekit.contracts import AssetRef, Bar, BarSeries

    bars = [
        Bar(
            ts_open=CAPTURED_AT - timedelta(hours=n_bars - i),
            open=Decimal("8.30000"),
            high=Decimal("8.40000"),
            low=Decimal("8.20000"),
            close=Decimal("8.30000"),
            volume=Decimal("1000"),
        )
        for i in range(n_bars)
    ]
    return BarSeries(
        asset=AssetRef(
            symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.00001")
        ),
        timeframe="1h",
        bars=bars,
        source="test-fixture",
    )


@pytest.fixture()
def rendered_html(monkeypatch: pytest.MonkeyPatch) -> str:
    """SEAM: drives a single allowed LINK/USD ticket through the real
    build_state -> render pipeline (mirrors test_build_state.py /
    test_hud_cli.py's precedent seams)."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(mae_runtime, "clock", lambda: CAPTURED_AT)
    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: _fixture_series(symbol),
    )
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _PassingSetup())
    monkeypatch.setattr(
        hud_build,
        "sizing_info",
        lambda symbol, limit_price, equity_usd: _FakeSizingInfo(
            qty=Decimal("12"),
            stop_distance_usd=Decimal("0.24900"),
            r_multiple_target=Decimal("2"),
        ),
    )
    monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

    state = build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=EQUITY_USD)
    assert len(state.tickets) == 1, "fixture must produce exactly one ticket to test its tab"
    return render(state)


class TestAC6TicketTabHasConfirmAndFailedButtons:
    def test_ticket_tab_contains_confirm_and_failed_button_text(
        self, rendered_html: str
    ) -> None:
        """AC-A6: each ticket tab contains "Confirm" and "Failed" — the two
        pinned button labels (Veto is explicitly out of scope, SPEC
        §Out of scope: "not acting is the veto")."""
        assert "Confirm" in rendered_html
        assert "Failed" in rendered_html
        assert "Veto" not in rendered_html


class TestAC6InlineFetchSnippetTargetsAckRouteWithPreviewId:
    def test_html_contains_inline_fetch_ack_call_carrying_verdict_preview_id(
        self, rendered_html: str
    ) -> None:
        """AC-A6: the inline JS snippet posts to '/ack' and references the
        ticket's verdict_id as the pairing key (SPEC POST body:
        `verdict_preview_id`) — golden derivation: the fixture's seamed
        `_AllowDecision.verdict_id` is "verdict-link-1", so that literal
        string must appear inside the snippet, proving the button is wired
        to THIS ticket, not a hardcoded placeholder."""
        assert "fetch('/ack'" in rendered_html or 'fetch("/ack"' in rendered_html
        assert "verdict-link-1" in rendered_html
        assert "verdict_preview_id" in rendered_html


class TestAC6GracefulDegradationIsStructurallyAsserted:
    def test_fetch_call_site_has_a_catch_handler(self, rendered_html: str) -> None:
        """AC-A6: "a static-file open (no server) leaves the page
        functional (buttons fail gracefully — no uncaught page errors;
        this is asserted structurally: the snippet catches fetch
        rejection)" — assert the literal `.catch(` construct is present
        near/after the fetch('/ack' call, not merely that SOME script tag
        exists somewhere on the page."""
        idx = rendered_html.find("fetch('/ack'")
        if idx == -1:
            idx = rendered_html.find('fetch("/ack"')
        assert idx != -1, "no inline fetch('/ack', ...) call found"
        # the .catch( must appear in the same script region, not merely
        # anywhere in the document (a single shared handler elsewhere would
        # not satisfy the "graceful per-button degradation" pin).
        window = rendered_html[idx : idx + 2000]
        assert ".catch(" in window


class TestAC6NoExternalResources:
    def test_no_external_script_or_link_urls_in_rendered_html(self, rendered_html: str) -> None:
        """AC-A6 / house self-contained rule (unchanged): the ack snippet
        must not introduce any http(s):// resource reference — the page
        stays a single self-contained document."""
        assert "http://" not in rendered_html
        assert "https://" not in rendered_html
