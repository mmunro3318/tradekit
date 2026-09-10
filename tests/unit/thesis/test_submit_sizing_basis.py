"""RED (SPEC-sizing-cap.md batch RED-B, T4): `thesis.submit`'s binding
sizing call against the REAL `mae.size_position` (through `thesis._submit.
build_submit_payloads`, never mocked — `mae.size_position`, `thesis.submit`,
and `policy.evaluate` are all banned mock targets per SPEC-sizing-cap.md
section 4).

Today `build_submit_payloads` calls `mae.size_position(symbol,
account_equity_usd=paper_starting_equity_usd)` with NO `price=`/
`max_position_usd=` kwargs (P4's defect): the contract's own
`entry.limit_price` is silently ignored (sizing always reads the DAILY
close) and nothing ever clips to the $50 paper cap. AC-12/AC-14 fail today
for exactly those reasons; AC-13 (no `limit_price` on the entry) is the
"nothing else moved" regression pin — passes both before and after.

Runtime determinism (mirrors `tests/unit/thesis/test_submit.py`'s own
module docstring): bars are faked by monkeypatching
`"tradekit.mae._runtime.get_closed_bars"` by dotted STRING path; the clock
via `"tradekit.mae._runtime._clock"`. `get_daily_bars` (which `mae.
size_position` calls) delegates to `get_closed_bars` in the current
`_runtime.py` body (ASSUMPTIONS 56's equivalence pin), so patching
`get_closed_bars` alone makes BOTH the snapshot fetch (`build_submit_
payloads`'s own daily-close read) and `size_position`'s ATR fetch
deterministic — one bars fake, one timeframe (this file only ever asks for
"1d" bars, unlike the hud/cadence sizing-basis files which also need "1h").

Fixture-freeze arithmetic (hand math, not just asserted — mirrors
`docs/specs/SPEC-sizing-cap.md`'s own fixture table):
  - F-TIGHT: 30 flat daily bars, open=close=100, high=101, low=99 -> no gap
    -> constant True Range = 2.0 on every bar -> Wilder ATR(14) = 2.0
    exactly (seed = plain average of first 14 TR values, recurrence keeps
    it at 2.0 forever). stop_distance = ATR14 * atr_multiplier(2.0) = 4.
    At price 100: risk_usd = 500*0.01 = 5; uncapped units = 5/4 = 1.25;
    uncapped size = $125 (> the $50 cap) -> clips to units
    (50/100)=0.5, size $50 exactly.
  - F-WIDE: 30 flat daily bars, high=110, low=90 -> constant TR = 20.0 ->
    ATR(14) = 20.0 -> stop_distance = 40. At price 105: units = 5/40 =
    0.125 (price-independent — units only divides risk_usd by
    stop_distance); size = 0.125 * 105 = $13.125 (under the $50 cap, over
    the $10 floor). At price 100 (no limit_price on the entry, AC-13):
    size = 0.125 * 100 = $12.50.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import thesis
from tradekit.contracts import AssetRef, Bar, BarSeries, EventFilter
from tradekit.ledger import default_ledger

_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_BARS = 30
_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))


def _daily_bars(*, high: Decimal, low: Decimal, n: int = _N_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=high,
            low=low,
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-daily")


_F_TIGHT_BARS = _daily_bars(high=Decimal("101"), low=Decimal("99"))
_F_WIDE_BARS = _daily_bars(high=Decimal("110"), low=Decimal("90"))


def _fake_clock() -> datetime:
    return _BAR_START + timedelta(days=_N_BARS + 5)


def _install_bars_seam(monkeypatch: pytest.MonkeyPatch, bars: BarSeries) -> None:
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        lambda symbol, timeframe, lookback_days: bars,
    )
    monkeypatch.setattr("tradekit.mae._runtime._clock", _fake_clock)


def _sizing_computed(thesis_id: str) -> dict:
    events = default_ledger().query(EventFilter(types=["SizingComputed"]))
    matches = [e for e in events if e.payload.get("thesis_id") == thesis_id]
    assert matches, f"no SizingComputed event found for thesis_id={thesis_id!r}"
    return matches[-1].payload


def _market_snapshot(thesis_id: str) -> dict:
    events = default_ledger().query(EventFilter(types=["MarketSnapshotTaken"]))
    matches = [e for e in events if e.payload.get("thesis_id") == thesis_id]
    assert matches, f"no MarketSnapshotTaken event found for thesis_id={thesis_id!r}"
    return matches[-1].payload


# ---------------------------------------------------------------------------
# AC-12 -- entry.limit_price becomes the sizing reference price
# ---------------------------------------------------------------------------


class TestAC12EntryLimitPriceBecomesTheSizingReference:
    def test_f_wide_market_entry_with_limit_price_105_sizes_at_105(
        self, monkeypatch: pytest.MonkeyPatch, thesis_kwargs: dict
    ) -> None:
        """BEHAVIOR (AC-12, cites SPEC-sizing-cap AC-12): F-WIDE daily bars,
        a `paper:alpha` contract whose entry carries `limit_price="105"` on
        a market order (P5's own shape: cadence's confirm chain keeps the
        ticket's limit price on a market entry). Must FAIL today: today's
        `build_submit_payloads` never reads `entry.get("limit_price")` at
        all, so `current_price` stays the daily close (100.0), not 105.0."""
        _install_bars_seam(monkeypatch, _F_WIDE_BARS)
        contract = dict(thesis_kwargs)
        contract["account_ref"] = "paper:alpha"
        contract["entry"] = {
            "order_type": "market",
            "limit_price": "105",
            "valid_until": "2026-01-20T00:00:00Z",
        }

        thesis_id = thesis.draft(contract)
        thesis.submit(thesis_id)

        sizing = _sizing_computed(thesis_id)
        assert sizing["sizing"]["current_price"] == 105.0
        assert sizing["sizing"]["recommended_size_usd"] == pytest.approx(13.125)
        assert sizing["sizing"]["max_position_usd"] == 50.0
        assert Decimal(str(sizing["account_equity_usd"])) == Decimal("500")

        snapshot = _market_snapshot(thesis_id)
        assert Decimal(str(snapshot["last_close"])) == Decimal("100"), (
            "AC-12: MarketSnapshotTaken.last_close stays the DAILY close (100) — "
            "snapshot semantics are unchanged by this fix, only the sizing reference moves"
        )


# ---------------------------------------------------------------------------
# AC-13 -- no limit_price on the entry -> today's behavior, unchanged
# ---------------------------------------------------------------------------


class TestAC13NoLimitPriceIsTheRegressionPin:
    def test_f_wide_market_entry_without_limit_price_sizes_at_the_daily_close(
        self, monkeypatch: pytest.MonkeyPatch, thesis_kwargs: dict
    ) -> None:
        """BEHAVIOR (AC-13, regression pin, cites SPEC-sizing-cap AC-13): the
        SAME F-WIDE contract with NO `limit_price` on the market entry ->
        `reference_price` falls back to `last_close` (the daily close, 100)
        -> today's behavior, unchanged. Passes BOTH before and after P4 —
        the "nothing else moved" pin."""
        _install_bars_seam(monkeypatch, _F_WIDE_BARS)
        contract = dict(thesis_kwargs)
        contract["account_ref"] = "paper:alpha"
        contract["entry"] = {"order_type": "market", "valid_until": "2026-01-20T00:00:00Z"}

        thesis_id = thesis.draft(contract)
        thesis.submit(thesis_id)

        sizing = _sizing_computed(thesis_id)
        assert sizing["sizing"]["current_price"] == 100.0
        assert sizing["sizing"]["recommended_size_usd"] == pytest.approx(12.5)


# ---------------------------------------------------------------------------
# AC-14 -- F-TIGHT limit entry at 100 clips to the paper cap
# ---------------------------------------------------------------------------


class TestAC14LimitEntryClipsToThePaperCap:
    def test_f_tight_limit_entry_at_100_clips_to_50(
        self, monkeypatch: pytest.MonkeyPatch, thesis_kwargs: dict
    ) -> None:
        """BEHAVIOR (AC-14, cites SPEC-sizing-cap AC-14): F-TIGHT daily bars,
        a `paper:alpha` limit entry at 100 -> uncapped size would be $125
        (> the $50 paper cap) -> clips to $50 exactly, 0.5 units, and the
        raw `mae.size_position` output carries the audit warning. Must FAIL
        today: no cap is passed at all yet, so `recommended_size_usd` stays
        the uncapped 125.0."""
        _install_bars_seam(monkeypatch, _F_TIGHT_BARS)
        contract = dict(thesis_kwargs)
        contract["account_ref"] = "paper:alpha"
        contract["entry"] = {
            "order_type": "limit",
            "limit_price": "100",
            "valid_until": "2026-01-20T00:00:00Z",
        }

        thesis_id = thesis.draft(contract)
        thesis.submit(thesis_id)

        sizing = _sizing_computed(thesis_id)
        assert sizing["sizing"]["recommended_size_usd"] == 50.0
        assert sizing["sizing"]["recommended_units"] == 0.5
        assert "capped_by_max_position" in sizing["sizing"]["warnings"], (
            "AC-14: the audit trail must record the clip"
        )
