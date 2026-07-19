"""Dress rehearsal for the hud-ack loop (no money, throwaway ledger).

Simulates the full first-trade path end-to-end against a TEMP ledger:
seams force one LINK/USD advisory ticket -> start the real serve loop ->
GET / (the page Mike would see) -> POST /ack confirmed (the button click)
-> print the resulting ledger chain (thesis -> review -> approve ->
verdict -> ack) and verify_chain.

Run: uv run python scripts/rehearse_hud_ack.py
Exit 0 = the loop works; nonzero with a message = something is broken.
Safe to run anytime: TK_DATA_DIR points at a fresh temp dir; the real
ledger is never touched.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="tk-rehearsal-")
    os.environ["TK_DATA_DIR"] = tmp
    print(f"[1/6] temp ledger at {tmp}")

    # Seam the funnel to force one ticket (same sanctioned seams the tests use).
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime
    from tradekit.contracts import AssetRef, Bar, BarSeries

    captured = datetime.now(UTC).replace(microsecond=0)

    def _bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        bars = [
            Bar(
                ts_open=captured - timedelta(hours=24 - i),
                open=Decimal("8.30000"),
                high=Decimal("8.40000"),
                low=Decimal("8.20000"),
                close=Decimal("8.30000"),
                volume=Decimal("1000"),
            )
            for i in range(24)
        ]
        return BarSeries(
            asset=AssetRef(
                symbol=symbol, venue="kraken", asset_class="crypto",
                tick_size=Decimal("0.00001"),
            ),
            timeframe="1h", bars=bars, source="rehearsal-fixture",
        )

    @dataclass(frozen=True)
    class _Sizing:
        qty: Decimal
        stop_distance_usd: Decimal
        r_multiple_target: Decimal

    @dataclass(frozen=True)
    class _Setup:
        signal_tags: list[str]

    @dataclass(frozen=True)
    class _Allow:
        allowed: bool = True
        verdict_id: str = "rehearsal-preview-verdict"
        rationale: str = "rehearsal preview"

    mae_runtime.get_closed_bars = _bars  # type: ignore[assignment]
    mae_runtime.clock = lambda: captured  # type: ignore[assignment]
    hud_build.scan_setup = lambda s: _Setup(["macd_bullish", "volume_spike"])  # type: ignore[assignment]
    hud_build.sizing_info = lambda s, p, e: _Sizing(  # type: ignore[assignment]
        Decimal("12"), Decimal("0.24900"), Decimal("2")
    )
    hud_build.evaluate_policy = lambda p: _Allow()  # type: ignore[assignment]
    hud_build.open_position_symbols = lambda: set()  # type: ignore[assignment]

    import tradekit.hud._serve as hud_serve

    @dataclass(frozen=True)
    class _BindingAllow:
        allowed: bool = True
        verdict_id: str = "rehearsal-binding-verdict"
        rationale: str = "binding allow (rehearsal)"

    hud_serve.evaluate_policy_binding = lambda a: _BindingAllow()  # type: ignore[assignment]

    server = hud_serve._make_server(host="127.0.0.1", port=0, equity_usd=Decimal("5000"))
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"[2/6] serve loop up on 127.0.0.1:{port}")

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    conn.request("GET", "/")
    resp = conn.getresponse()
    page = resp.read().decode()
    assert resp.status == 200 and "LINK/USD" in page and "Confirm" in page, "GET / failed"
    print("[3/6] GET / renders the ticket with Confirm/Failed buttons")

    body = json.dumps({
        "verdict_preview_id": "rehearsal-preview-verdict",
        "action": "confirmed",
        "ticket": {
            "pair": "LINK/USD", "side": "buy", "limit_price": "8.30000",
            "quantity": "12", "tp_price": "8.79800", "sl_price": "8.05100",
        },
    })
    conn.request("POST", "/ack", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    resp.read()
    assert resp.status == 204, f"confirm POST returned {resp.status}"
    print("[4/6] Confirm click -> 204 (binding chain executed)")

    from tradekit.contracts import EventFilter
    from tradekit.ledger import default_ledger

    ledger = default_ledger()
    events = ledger.query(EventFilter())
    chain = [(e.type, e.payload.get("thesis_id", "")) for e in events]
    print("[5/6] ledger chain:")
    for t, tid in chain:
        print(f"        {t:24} {tid}")
    types = [t for t, _ in chain]
    for required in ("ThesisDrafted", "ThesisApproved", "AdvisoryTicketAcked"):
        assert required in types, f"missing {required} in ledger chain"
    acked = next(e for e in events if e.type == "AdvisoryTicketAcked")
    assert acked.payload["action"] == "confirmed"
    assert acked.payload["thesis_id"], "ack must carry the real thesis id"

    report = ledger.verify_chain()
    assert report.ok, "hash chain broken"
    server.shutdown()
    print("[6/6] verify_chain OK — REHEARSAL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
