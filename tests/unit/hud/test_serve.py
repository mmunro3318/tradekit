"""SEAM/BEHAVIOR tests for `tk hud --serve` (SPEC-hud-ack.md AC-A1..A7).

Server harness (ASSUMPTIONS flag #2, see report): the pinned signature
``hud.serve(*, equity_usd, host="127.0.0.1", port=7333) -> None`` blocks
ephemeral-port testing (it neither returns the bound server nor exposes the
resolved port before blocking on ``serve_forever``). Per the dispatch's own
fallback, these tests pin an ADDITIONAL seam,
``tradekit.hud._serve._make_server(*, host, port, equity_usd) ->
http.server.HTTPServer``, and drive it directly: construct with port=0
(OS-assigned ephemeral port), read ``.server_address[1]`` for the real
port, run ``.serve_forever`` in a daemon thread, and issue requests via
``http.client``. ``hud.serve`` itself is assumed to be a thin
``_make_server(...).serve_forever()`` wrapper (this is exactly the shape
that lets AC-A7's KeyboardInterrupt test drive the real ``serve()`` entry
point without needing a live ephemeral-port dance there).

Isolation: TK_DATA_DIR -> tmp_path (existing conformance pattern, see
tests/conftest.py's `isolated_ledger` fixture and every `tests/unit/broker`
temp-ledger test) set via monkeypatch BEFORE any ledger touch. Determinism:
mae._runtime.clock frozen; mae._runtime.get_closed_bars + the four
tradekit.hud._build seams (evaluate_policy, open_position_symbols,
sizing_info, scan_setup) drive GET / (AC-A1) reproducibly. The confirm-time
policy call is a SEPARATE seam, `tradekit.hud._serve.evaluate_policy_binding`
(ASSUMPTIONS flag #1, see report) — SPEC's confirm chain (draft -> submit ->
approve -> policy.evaluate) is exercised for real up through the ledgered
thesis lifecycle events; only the FINAL policy.evaluate call is seamed, so
AC-A3/A4 can deterministically control allow vs refuse without depending on
PolicyDials' live rule set.
"""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

CAPTURED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
EQUITY_USD = Decimal("5000")

TICKET_BODY = {
    "pair": "LINK/USD",
    "side": "buy",
    "limit_price": "8.30000",
    "quantity": "12",
    "tp_price": "8.79800",
    "sl_price": "8.05100",
}


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


def _patch_get_funnel(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM (GET / determinism, AC-A1): mirrors test_hud_cli.py's
    _patch_allow_all — frozen clock, real bars, passing setup/sizing,
    allowed policy, no open positions."""
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


@pytest.fixture()
def isolated_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """TK_DATA_DIR isolation, set BEFORE any ledger touch (SPEC test plan:
    "BEHAVIOR against a temp ledger (TK_DATA_DIR to tmp_path — the existing
    conformance pattern)")."""
    monkeypatch.setenv("TK_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def running_server(
    isolated_ledger: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, int]]:
    """SEAM: `hud._serve._make_server(host="127.0.0.1", port=0,
    equity_usd=...)` on an OS-assigned ephemeral port, served on a daemon
    thread; yields (host, port). Cleaned up via server.shutdown()."""
    _patch_get_funnel(monkeypatch)
    from tradekit.hud import _serve

    server = _serve._make_server(host="127.0.0.1", port=0, equity_usd=EQUITY_USD)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield ("127.0.0.1", server.server_address[1])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _query_events(types: list[str] | None = None) -> list[Any]:
    from tradekit.contracts import EventFilter
    from tradekit.ledger import default_ledger

    return default_ledger().query(EventFilter(types=types))


class TestAC1GetReturnsFreshRenderOfBuildState:
    def test_get_root_returns_200_html_with_key_content_from_seamed_state(
        self, running_server: tuple[str, int]
    ) -> None:
        """AC-A1: GET / -> 200, text/html, body contains key content that
        render(build_state(...)) produces at this instant (the seamed
        pair label LINK/USD, driven through the same seams AC-9 in
        test_hud_cli.py uses)."""
        host, port = running_server
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
        finally:
            conn.close()

        assert resp.status == 200
        assert "text/html" in resp.getheader("Content-Type", "")
        assert "LINK/USD" in body


class TestAC2FailedAckAppendsExactlyOneEventVerbatim:
    def test_failed_action_appends_one_advisory_ticket_acked_with_null_ids_and_204(
        self, running_server: tuple[str, int]
    ) -> None:
        """AC-A2: POST /ack action=failed -> exactly one AdvisoryTicketAcked
        appended, payload action="failed", thesis_id/verdict_id null,
        ticket snapshot verbatim; response 204."""
        host, port = running_server
        body = json.dumps(
            {"verdict_preview_id": "verdict-preview-9", "action": "failed", "ticket": TICKET_BODY}
        )
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("POST", "/ack", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()

        assert resp.status == 204

        events = _query_events(types=["AdvisoryTicketAcked"])
        assert len(events) == 1
        payload = events[0].payload
        assert payload["action"] == "failed"
        assert payload["thesis_id"] is None
        assert payload["verdict_id"] is None
        assert payload["verdict_preview_id"] == "verdict-preview-9"
        assert payload["pair"] == TICKET_BODY["pair"]
        assert payload["side"] == TICKET_BODY["side"]
        assert Decimal(payload["limit_price"]) == Decimal(TICKET_BODY["limit_price"])
        assert Decimal(payload["quantity"]) == Decimal(TICKET_BODY["quantity"])


class TestAC3ConfirmedAllowAppendsBindingChainWithMatchingIds:
    def test_confirmed_action_with_policy_allow_appends_thesis_chain_and_matching_ack(
        self, running_server: tuple[str, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-A3: POST /ack action=confirmed with the confirm-time policy
        seam returning allow -> ledger gains a ThesisDrafted event and an
        AdvisoryTicketAcked event whose thesis_id/verdict_id match the
        ledgered thesis + the seamed verdict; response 204.

        ASSUMPTIONS flag #1 (see report): this test does NOT assert the
        exact intermediate event sequence between ThesisDrafted and the
        final ThesisApproved — thesis.approve's require_state guard
        (tradekit/thesis/_machine.py) legally transitions only from
        "reviewed", which requires a prior ReviewCompleted event that
        SPEC's literal "draft -> submit -> approve" chain does not mention.
        How the implementer bridges submit -> reviewed is unresolved; the
        assertion here is on the OUTER contract (thesis exists, is
        approved, ack references it) that SPEC's AC-A3 wording pins
        ("+submit/approve events per house lifecycle" — deliberately loose).
        """
        from tradekit.hud import _serve

        monkeypatch.setattr(
            _serve, "evaluate_policy_binding", lambda action: _AllowDecision()
        )

        host, port = running_server
        body = json.dumps(
            {
                "verdict_preview_id": "verdict-preview-3",
                "action": "confirmed",
                "ticket": TICKET_BODY,
            }
        )
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("POST", "/ack", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()

        assert resp.status == 204

        drafted = _query_events(types=["ThesisDrafted"])
        approved = _query_events(types=["ThesisApproved"])
        acked = _query_events(types=["AdvisoryTicketAcked"])

        assert len(drafted) == 1
        assert len(approved) == 1
        assert drafted[0].payload["thesis_id"] == approved[0].payload["thesis_id"]

        assert len(acked) == 1
        ack_payload = acked[0].payload
        assert ack_payload["action"] == "confirmed"
        assert ack_payload["thesis_id"] == drafted[0].payload["thesis_id"]
        assert ack_payload["verdict_id"] == _AllowDecision.verdict_id
        assert ack_payload["verdict_preview_id"] == "verdict-preview-3"


class TestAC4ConfirmedRefuseReturns409AndAppendsNoAck:
    def test_confirmed_action_with_policy_refuse_returns_409_with_rationale_and_no_ack(
        self, running_server: tuple[str, int], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-A4: POST /ack action=confirmed with the confirm-time policy
        seam returning refuse -> 409 carrying the refusal rationale in the
        body; NO AdvisoryTicketAcked event is appended (safety: never let
        Mike send a stale order)."""
        from tradekit.hud import _serve

        class _Refuse:
            allowed = False
            verdict_id = None
            rationale = "R-rule breach: daily loss limit near"

        monkeypatch.setattr(_serve, "evaluate_policy_binding", lambda action: _Refuse())

        host, port = running_server
        body = json.dumps(
            {
                "verdict_preview_id": "verdict-preview-4",
                "action": "confirmed",
                "ticket": TICKET_BODY,
            }
        )
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("POST", "/ack", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp_body = resp.read().decode("utf-8")
        finally:
            conn.close()

        assert resp.status == 409
        assert "daily loss limit" in resp_body

        acked = _query_events(types=["AdvisoryTicketAcked"])
        assert acked == []


class TestAC5MalformedRequestReturns400AndLeavesLedgerUnchanged:
    def test_malformed_json_returns_400_and_ledger_event_count_unchanged(
        self, running_server: tuple[str, int]
    ) -> None:
        """AC-A5: malformed JSON body -> 400, ledger unchanged (total event
        count before == after)."""
        before = len(_query_events())

        host, port = running_server
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request(
                "POST",
                "/ack",
                body="{not valid json::",
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()

        assert resp.status == 400
        after = len(_query_events())
        assert after == before

    def test_missing_required_field_returns_400_and_ledger_event_count_unchanged(
        self, running_server: tuple[str, int]
    ) -> None:
        """AC-A5: valid JSON but missing a pinned field (here: no `action`)
        -> 400, ledger unchanged."""
        before = len(_query_events())

        host, port = running_server
        body = json.dumps({"verdict_preview_id": "verdict-preview-5", "ticket": TICKET_BODY})
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("POST", "/ack", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()

        assert resp.status == 400
        after = len(_query_events())
        assert after == before


class TestUnknownRouteReturns404:
    def test_get_unknown_path_returns_404(self, running_server: tuple[str, int]) -> None:
        """SPEC routes table: "Anything else -> 404" — a BEHAVIOR case the
        route table pins but no AC number names explicitly."""
        host, port = running_server
        conn = http.client.HTTPConnection(host, port, timeout=5)
        try:
            conn.request("GET", "/nope")
            resp = conn.getresponse()
            resp.read()
        finally:
            conn.close()

        assert resp.status == 404


class TestAC7KeyboardInterruptExitsCleanly:
    def test_serve_returns_without_raising_when_serve_forever_is_interrupted(
        self, isolated_ledger: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-A7: KeyboardInterrupt during the server loop -> clean exit
        (no exception escapes `hud.serve`) — tested at the seam
        `hud._serve._make_server`: a fake server whose `serve_forever`
        raises KeyboardInterrupt immediately stands in for Ctrl-C: `serve()`
        is pinned to catch it and return normally, which CliRunner then
        turns into exit code 0 at the CLI layer (out of scope for this
        module-level test — asserted here as "no exception escapes")."""
        import tradekit.hud._serve as hud_serve

        class _FakeServer:
            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        monkeypatch.setattr(
            hud_serve, "_make_server", lambda *, host, port, equity_usd: _FakeServer()
        )

        # Should not raise.
        hud_serve.serve(equity_usd=EQUITY_USD, host="127.0.0.1", port=7333)
