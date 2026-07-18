"""P3 done-gate (SPRINT-P3-P4-paper-to-live.md story 3.7, DESIGN §16 ring
3): ONE full journey through every REAL verb this sprint built — scan ->
thesis -> review (fake adapter) -> gates -> order -> paper fill -> grade ->
memo/brief, reproducible from the event log.

Deterministic throughout: no sleeps, no network, no real clock — every
clock/bars/regime seam is monkeypatched via the sanctioned dotted-string
module-attribute pattern this codebase uses everywhere (`tradekit.mae.
_runtime._clock`/`get_closed_bars`, `tradekit.review._adapters.
SubprocessReviewerAdapter.from_dials`).

Status (SPRINT P3 batch E, TDD red phase): everything through GRADING is
already REAL and green (every verb it drives — `mae.scan_markets`,
`thesis.draft/submit/approve`, `review.run_review`, `broker.execute_order`,
`thesis.grade`, `ledger.rebuild`/`verify_chain` — landed in earlier P3
batches). The REPLAY assertion (rebuild -> byte-identical projection
snapshot) is therefore also real and passes TODAY. The scenario only turns
red at its FINAL two steps — `memory.brief()`/`report.daily_memo()`, both
unconditional `NotImplementedError` stubs this batch — which is exactly
where this file's assertions describe DESIGN §11/§12.3's own requirement
("brief render containing the grade") rather than being wrapped in
`pytest.raises(NotImplementedError)`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit import broker, memory, report, thesis
from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.ledger import default_ledger
from tradekit.mae import scan_markets

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))

# --- scan_markets fixture: a planted RSI-oversold setup (pure-loss run
# pins RSI to 0.0, per the frozen `mae._indicators.momentum.rsi` zero-guard
# — same fixture shape `tests/unit/mae/test_scan_markets_verb.py` derives
# in its own module docstring) -------------------------------------------
_SCAN_START = datetime(2025, 12, 1, tzinfo=UTC)


def _scan_bars() -> BarSeries:
    closes = [120.0 - i for i in range(20)]  # steadily falling -> RSI pins to 0.0
    bars = [
        Bar(
            ts_open=_SCAN_START + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c + 0.3)),
            low=Decimal(str(c - 0.3)),
            close=Decimal(str(c)),
            volume=Decimal("100"),
        )
        for i, c in enumerate(closes)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


# --- submit-phase fixture: flat ATR(14)=10 bars, sized to recommend
# exactly 25.00 (mirrors tests/unit/broker/test_pipeline.py's own proven
# fixture, same docstring rationale) ---------------------------------------
_SUBMIT_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_SUBMIT_BARS = 20


def _submit_bars() -> BarSeries:
    bars = [
        Bar(
            ts_open=_SUBMIT_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(_N_SUBMIT_BARS)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


_ACTIVATION_TS = _SUBMIT_START + timedelta(days=_N_SUBMIT_BARS + 5)  # 2026-01-26

# --- grading-phase fixture: high touches the conftest thesis_kwargs'
# default target (66000.00) -> PASS -------------------------------------
_PASS_BARS = [
    Bar(ts_open=_ACTIVATION_TS + timedelta(hours=1), open=Decimal("60000"),
        high=Decimal("61000"), low=Decimal("59000"), close=Decimal("60500"),
        volume=Decimal("10")),
    Bar(ts_open=_ACTIVATION_TS + timedelta(hours=2), open=Decimal("61000"),
        high=Decimal("67000"), low=Decimal("60500"), close=Decimal("66500"),
        volume=Decimal("10")),  # high 67000 >= target 66000 -> PASS
]

_ALL_RESOLVED_EXCHANGE = [
    {
        "attack": "p_win=0.55 with no base-rate citation.",
        "category": "ev_arithmetic",
        "severity": 2,
        "defense": "Base rate drawn from the strategy_tag's last 40 trades (wiki-cited).",
        "resolved": True,
    }
]


class _FakeReviewerAdapter:
    """In-process `LLMReviewerPort` fake — canned all-resolved JSON,
    never a real subprocess (same pattern `tests/unit/review/
    test_run_review.py::_RecordingFakeAdapter` establishes)."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.calls: list[str] = []

    def review(self, prompt: str, *, timeout_s: int, max_output_bytes: int) -> str:
        self.calls.append(prompt)
        return self._response


def _patch_reviewer(monkeypatch) -> _FakeReviewerAdapter:
    import json

    adapter = _FakeReviewerAdapter(json.dumps(_ALL_RESOLVED_EXCHANGE))
    monkeypatch.setattr(
        "tradekit.review._adapters.SubprocessReviewerAdapter.from_dials",
        classmethod(lambda cls, dials=None: adapter),
    )
    return adapter


def _market_entry_kwargs(thesis_kwargs: dict) -> dict:
    kw = dict(thesis_kwargs)
    kw["entry"] = {"order_type": "market", "valid_until": "2026-02-01T00:00:00Z"}
    return kw


def test_p3_end_to_end_done_gate(thesis_kwargs, monkeypatch, read_model_snapshot) -> None:
    # --- 1. scan_markets finds the planted setup (regime gate off — the
    # scanner's own plumbing, not regime correctness, is what this
    # done-gate exercises) ------------------------------------------------
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", lambda *a, **k: _scan_bars())
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _SCAN_START + timedelta(days=25))
    scan = scan_markets(
        asset_class="crypto", timeframes=["1d"], filters={"rsi_max": 50},
        symbols=["BTC/USD"], regime_gate=False,
    )
    assert any(m["symbol"] == "BTC/USD" for m in scan["matches"]), (
        "scan_markets must surface the planted oversold BTC/USD setup"
    )

    # --- 2. draft + submit (real verbs) ----------------------------------
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", lambda *a, **k: _submit_bars())
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _ACTIVATION_TS)
    kw = _market_entry_kwargs(thesis_kwargs)
    thesis_id = thesis.draft(kw)
    thesis.submit(thesis_id)

    # --- 3. run_review with a fake adapter (real pipeline, canned JSON) --
    adapter = _patch_reviewer(monkeypatch)
    from tradekit import review as review_module

    review_result = review_module.run_review(thesis_id)
    assert review_result["passed"] is True, (
        f"the fake adapter's all-resolved exchange must clear review: {review_result}"
    )
    assert len(adapter.calls) == 1, "run_review must call the reviewer adapter exactly once"

    # --- 4. approve -> execute_order (real two-phase pipeline, paper fill,
    # thesis activation) ---------------------------------------------------
    thesis.approve(thesis_id)
    ack = broker.execute_order(thesis_id)
    assert ack.status == "accepted"
    assert thesis._machine.derive_state(default_ledger(), thesis_id) == "active"

    # --- 5. grade -> PASS with pnl ----------------------------------------
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        lambda symbol, timeframe, lookback_days: BarSeries(
            asset=_ASSET, timeframe=timeframe, bars=_PASS_BARS, source="fake-kraken"
        ),
    )
    monkeypatch.setattr(
        "tradekit.mae._runtime._clock", lambda: _ACTIVATION_TS + timedelta(hours=3)
    )
    graded = thesis.grade(thesis_id)
    assert graded["outcome"] == "PASS"
    assert graded["pnl_usd"] is not None, "a PASS grade with a real fill must carry a numeric pnl"

    # --- 6. REPLAY: rebuild projections from the event log; the snapshot
    # must be byte-identical to a second rebuild (already real + green) ---
    default_ledger().rebuild()
    first_snapshot = read_model_snapshot()
    default_ledger().rebuild()
    assert read_model_snapshot() == first_snapshot, (
        "rebuild() must be a pure function of the event log — two rebuilds of the SAME "
        "history must produce byte-identical projections (reproducible from the event log)"
    )
    assert default_ledger().verify_chain().ok, "the full journey's hash chain must verify"

    # --- 7. memory.brief() / report.daily_memo() must surface the grade --
    # RED from here: both are NotImplementedError stubs this batch.
    brief_text = memory.brief()
    assert thesis_id in brief_text or "PASS" in brief_text, (
        "tk brief's 'last 10 grades' section (DESIGN §11) must reflect this journey's grade"
    )

    memo_text = report.daily_memo(thesis_id)
    assert "PASS" in memo_text, "the daily memo's gate-status section must show the real outcome"
