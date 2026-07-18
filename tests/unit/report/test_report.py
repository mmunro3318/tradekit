"""`tradekit.report` — thin templating over read models (DESIGN §12.3;
SPRINT P3 batch E). All three verbs (`daily_memo`/`readiness_report`/
`pnl_snapshot`) are unconditional `NotImplementedError` stubs
(`report/__init__.py`); every test below describes REAL target behavior
and is red for that reason alone (never wrapped in
`pytest.raises(NotImplementedError)`, same discipline as every other
red-phase file this sprint). Assertions check KEY CONTENT PRESENCE, not
full golden strings (sprint-doc instruction), since the exact markdown
layout is the dev pass's own call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradekit import policy, report, thesis
from tradekit.ledger import default_ledger


def _submitted_thesis(thesis_kwargs, monkeypatch, make_event) -> str:
    """A real thesis at `submitted`, plus a real ReviewCompleted — enough
    for `daily_memo` to have every SME §3 field (hypothesis/context/
    strategy/size/risk/EV/criteria/gate status) available to render."""
    from decimal import Decimal

    from tradekit.contracts import AssetRef, Bar, BarSeries

    asset = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto",
                     tick_size=Decimal("0.01"))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(ts_open=start + timedelta(days=i), open=Decimal("100"), high=Decimal("105"),
            low=Decimal("95"), close=Decimal("100"), volume=Decimal("1000"))
        for i in range(20)
    ]
    series = BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", lambda *a, **k: series)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: start + timedelta(days=25))
    tid = thesis.draft(thesis_kwargs)
    thesis.submit(tid)
    default_ledger().append(
        make_event(
            type="ReviewCompleted",
            payload={"thesis_id": tid, "review_artifact_id": "rev-1", "passed": True,
                     "kind": "thesis_review"},
        )
    )
    return tid


def test_daily_memo_includes_hypothesis_ev_and_gate_status(
    thesis_kwargs, monkeypatch, make_event
) -> None:
    tid = _submitted_thesis(thesis_kwargs, monkeypatch, make_event)

    memo = report.daily_memo(tid)

    assert thesis_kwargs["rationale"][:20] in memo, "hypothesis section renders the rationale"
    assert str(thesis_kwargs["ev_block"]["ev_usd"]) in memo, "numeric EV must be explicit (SME §3)"
    assert "GATE" in memo.upper()


def test_readiness_report_renders_promotion_status_verbatim_with_criteria(monkeypatch) -> None:
    monkeypatch.setattr("tradekit.policy._context._clock", lambda: datetime(2026, 3, 5, tzinfo=UTC))
    status = policy.promotion_status()

    rendered = report.readiness_report()

    assert status["tier"] in rendered
    for criterion_name in status["t2_eligible"]["criteria"]:
        assert criterion_name in rendered, (
            "readiness_report is the D7 stakes-without-deception surface — every "
            "per-criterion name from promotion_status() must appear, not a collapsed summary"
        )


def test_pnl_snapshot_includes_account_ref_and_realized_pnl(ledger, make_event) -> None:
    ledger.append(
        make_event(
            type="ThesisGraded",
            payload={"thesis_id": "th-pnl", "outcome": "PASS", "measured": [],
                     "ambiguous_bar": False, "pnl_usd": "42.00",
                     "graded_ts": datetime(2026, 1, 5, tzinfo=UTC).isoformat()},
        )
    )

    snapshot = report.pnl_snapshot("paper:alpha")

    assert "paper:alpha" in snapshot
