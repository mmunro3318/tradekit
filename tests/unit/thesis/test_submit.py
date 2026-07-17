"""`thesis.submit` mechanics — event ordering, snapshot, sizing, predicate
requantization, and EV validation (DESIGN §10.1, SPRINT P2 batch A story 1
+ CTO addendum).

Status: `thesis.submit` is still an unconditional `NotImplementedError` stub
this batch — every test below is RED for that reason (batch dispatch:
"Failing tests + stubs only"). Assertions describe the REAL behavior the P2
dev pass implements next.

Runtime determinism (CTO addendum, "sanctioned bar seam"): bars are faked by
monkeypatching `"tradekit.mae._runtime.get_closed_bars"` by dotted STRING
path (no `import tradekit.mae._runtime`, needs no ASSUMPTIONS internal-
import exception — same pattern as `test_size_position_verb.py`); the clock
via `"tradekit.mae._runtime._clock"`. `get_daily_bars` (which `mae.
size_position` calls) already delegates to `get_closed_bars` in the current
`_runtime.py` body (ASSUMPTIONS 56's equivalence pin), so patching
`get_closed_bars` alone makes BOTH the snapshot fetch (however submit()
sources it) and `size_position`'s ATR fetch deterministic.

Fixture-freeze arithmetic (fixture-freeze rule — hand math shown, not just
asserted):
  - 20 flat daily bars, high=101/low=99/open=close=100 for every bar (same
    shape as P1C's `test_size_position_verb.py` ATR fixture) -> True Range
    is a constant 2.0 on every bar (no gap: prior close=100 always sits
    inside [low, high]) -> Wilder ATR(14) seed = plain average of the first
    14 TR values = 2.0 exactly, and the recurrence
    atr[i] = (atr[i-1]*13 + TR[i]) / 14 with TR[i]=2.0 keeps atr AT 2.0
    forever (same derivation as P1C's, re-verified here for equity=500
    instead of 1000). Last closed bar's close = 100 -> quantize(100, 0.01)
    = Decimal("100.00").
  - EV recompute (`thesis_kwargs`'s stock EV block, CTO addendum's own
    worked example): p_win=0.55, reward_usd=2.50, risk_usd=1.25 ->
    ev = 0.55*2.50 - 0.45*1.25 = 1.375 - 0.5625 = 0.8125 exactly (Decimal).
    Stated ev_usd=0.81 -> |0.8125 - 0.81| = 0.0025 <= 0.01 -> PASSES
    (the fixture as shipped in `tests/conftest.py::thesis_kwargs`, unchanged).
  - Boundary-exact case: stated ev_usd=0.8025 -> |0.8125 - 0.8025| = 0.0100
    exactly, which is NOT > 0.01 -> must PASS (CTO addendum: "exactly-$0.01
    boundary passes").
  - Over-tolerance case: stated ev_usd=0.50 -> |0.8125 - 0.50| = 0.3125 > 0.01
    -> must be REJECTED, with zero events appended (validate-before-append).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import mae, thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter
from tradekit.ledger import default_ledger

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_BARS = 20

# CTO addendum default dial (`paper_starting_equity_usd = 500`); PolicyDials
# itself lands batch C, so this batch's submit() implementation is expected
# to use a hardcoded module constant of the same value in the interim
# (ASSUMPTIONS, this batch — flagged, not silently assumed).
_PAPER_STARTING_EQUITY_USD = Decimal("500")


def _flat_atr2_price100_bars(n: int = _N_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _fake_get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
    return _flat_atr2_price100_bars()


def _fake_clock() -> datetime:
    return _BAR_START + timedelta(days=_N_BARS + 5)


@pytest.fixture(autouse=True)
def _deterministic_runtime(monkeypatch):
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake_get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_clock)


def _events(event_type: str):
    return default_ledger().query(EventFilter(types=[event_type]))


def _thesis_events(event_type: str, thesis_id: str):
    return [e for e in _events(event_type) if e.payload.get("thesis_id") == thesis_id]


# ---------------------------------------------------------------------------
# event ordering + snapshot + sizing + predicates
# ---------------------------------------------------------------------------


def test_submit_appends_snapshot_sizing_submitted_in_pinned_order(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    all_events = default_ledger().query(
        EventFilter(types=["MarketSnapshotTaken", "SizingComputed", "ThesisSubmitted"])
    )
    this_thesis = [e for e in all_events if e.payload.get("thesis_id") == thesis_id]
    assert [e.type for e in this_thesis] == [
        "MarketSnapshotTaken",
        "SizingComputed",
        "ThesisSubmitted",
    ], (
        "CTO addendum: submit() validates everything first, then appends IN ORDER "
        "MarketSnapshotTaken -> SizingComputed -> ThesisSubmitted (the transition marker "
        "is LAST — a crash mid-sequence leaves the thesis in draft with harmless orphan "
        "prep events, because state = marker presence)"
    )


def test_submit_snapshot_payload_fields(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    snapshot = _thesis_events("MarketSnapshotTaken", thesis_id)[0]
    assert snapshot.payload["symbol"] == thesis_kwargs["asset"]["symbol"]
    assert snapshot.payload["last_close"] == "100.00", (
        "last CLOSED daily bar's close (100), quantized to the asset's 0.01 tick "
        "(CTO addendum: 'Snapshot (MVP): last CLOSED daily bar for the asset')"
    )
    assert snapshot.payload["source"], "provider provenance must always be visible (§13)"
    assert "snapshot_id" in snapshot.payload

    submitted = _thesis_events("ThesisSubmitted", thesis_id)[0]
    assert submitted.payload["market_snapshot_id"] == snapshot.payload["snapshot_id"], (
        "CTO addendum: 'the canonical linkage is the EVENT (thesis_id + snapshot_id)' — "
        "ThesisSubmitted must reference the SAME snapshot_id MarketSnapshotTaken minted"
    )


def test_submit_sizing_payload_matches_size_position_output_verbatim(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    # Same monkeypatched bars, called directly — this is R-012's whole point:
    # SizingComputed must equal mae.size_position's REAL output, not a
    # re-derivation of it.
    expected = mae.size_position(
        thesis_kwargs["asset"]["symbol"], account_equity_usd=_PAPER_STARTING_EQUITY_USD
    )

    sizing_event = _thesis_events("SizingComputed", thesis_id)[0]
    assert sizing_event.payload["sizing"] == expected, (
        "R-012 (Sizing purity, F6) compares submitted order size against THIS recorded "
        "value — it must be size_position's output recorded VERBATIM, not re-summarized "
        "or re-typed"
    )
    assert sizing_event.payload["account_equity_usd"] == str(_PAPER_STARTING_EQUITY_USD)


def test_submit_predicate_values_requantized_in_submitted_payload(thesis_kwargs) -> None:
    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    submitted = _thesis_events("ThesisSubmitted", thesis_id)[0]
    assert submitted.payload["resolved_target_price"] == "66000.00"
    assert submitted.payload["resolved_stop_price"] == "57000.00"
    assert submitted.payload["resolved_success_criteria"][0]["value"] == "66000.00", (
        "every price-carrying predicate value is re-quantized via "
        "contracts.quantize(value, asset.tick_size) at submit (CTO addendum)"
    )
    assert submitted.payload["resolved_failure_criteria"][0]["value"] == "57000.00"


def test_submit_equity_base_case_uses_paper_starting_equity_with_no_fills(thesis_kwargs) -> None:
    """CTO addendum: equity = paper_starting_equity_usd + cumulative realized pnl
    for the account_ref from `pnl_daily` (Decimal). `pnl_daily`'s FillRecorded
    population is deferred to batch B/D (ASSUMPTIONS, this batch — the schema
    lands now, per `_projections.py`'s docstring, but nothing populates it yet)
    — this test pins ONLY the base case with zero fills: equity ==
    paper_starting_equity_usd (500)."""
    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    sizing_event = _thesis_events("SizingComputed", thesis_id)[0]
    assert sizing_event.payload["account_equity_usd"] == str(_PAPER_STARTING_EQUITY_USD)


def test_submit_equity_follows_a_config_toml_paper_starting_equity_override(
    thesis_kwargs, tmp_path, monkeypatch
) -> None:
    """SPRINT P2 batch C: `PAPER_STARTING_EQUITY_USD` is retired — submit()
    must read `PolicyDials.load().paper_starting_equity_usd` at call time, so
    a `TK_CONFIG_PATH` override changes SizingComputed's equity (this batch's
    binding pin: 'a tmp config with paper_starting_equity_usd=1000 -> equity
    1000')."""
    config = tmp_path / "override.toml"
    config.write_text('paper_starting_equity_usd = "1000"\n', encoding="utf-8")
    monkeypatch.setenv("TK_CONFIG_PATH", str(config))

    thesis_id = thesis.draft(thesis_kwargs)
    thesis.submit(thesis_id)

    sizing_event = _thesis_events("SizingComputed", thesis_id)[0]
    assert sizing_event.payload["account_equity_usd"] == "1000", (
        f"expected the config.toml override (1000) to flow through to SizingComputed's "
        f"equity, got {sizing_event.payload['account_equity_usd']!r}"
    )


# ---------------------------------------------------------------------------
# EV validation (F5)
# ---------------------------------------------------------------------------


def test_submit_ev_validation_rejects_over_tolerance_and_appends_nothing(thesis_kwargs) -> None:
    thesis_kwargs["ev_block"]["ev_usd"] = "0.50"  # |0.8125 - 0.50| = 0.3125 > 0.01
    thesis_id = thesis.draft(thesis_kwargs)

    before = len(default_ledger().query(EventFilter()))
    with pytest.raises(ValueError):
        thesis.submit(thesis_id)
    after = len(default_ledger().query(EventFilter()))

    assert after == before, (
        "CTO addendum: 'submit validates EVERYTHING first, then appends' — a rejected "
        "EV block must leave ZERO new events, not orphaned MarketSnapshotTaken/"
        "SizingComputed rows from a partially-run submit"
    )


def test_submit_ev_validation_exact_001_boundary_passes(thesis_kwargs) -> None:
    # |0.8125 - 0.8025| = 0.0100 exactly: NOT strictly greater than 0.01.
    thesis_kwargs["ev_block"]["ev_usd"] = "0.8025"
    thesis_id = thesis.draft(thesis_kwargs)

    thesis.submit(thesis_id)  # must NOT raise

    submitted = _thesis_events("ThesisSubmitted", thesis_id)
    assert len(submitted) == 1
    assert submitted[0].payload["ev_stated_usd"] == "0.8025"
    assert submitted[0].payload["ev_recomputed_usd"] == "0.8125"
