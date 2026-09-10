"""BEHAVIOR (AC-26, SPEC-sizing-cap.md section 6 P8; review round 24 F2,
ASSUMPTIONS 182.6/10): `policy._context._trades_today_count` no longer
counts `ActionProposed(submit_order)` events -- every scan-time preview
(`hud.build_state`) ledgers a real one, win or lose, and so does every
DENIED binding attempt; round 24's own probe measured twenty dead previews
alone driving the count to 20, then a real submit_order evaluate reading
`R-007: 21 vs 20` and locking the paper account for the rest of the day
with zero orders ever actually submitted. The fix counts today's ENTRY
`OrderSubmitted` events instead -- a thesis's FIRST `OrderSubmitted` ever,
anywhere in the ledger. Previews never submit an order at all (zero
`OrderSubmitted` events); a real entry counts exactly once; that thesis's
exit (`broker.execute_exit`'s own second `OrderSubmitted` for the same
thesis_id) must never re-count -- R-007 must never throttle exits.
`_check_r007` (`policy/_rules.py`) is untouched; only where this count's
events come from moves.

Real ledger throughout -- `mae.size_position`, `thesis.submit`,
`policy.evaluate`, `broker.execute_order`, `broker.execute_exit` are all
banned mock targets (SPEC-sizing-cap.md section 4). The preview harness
mirrors `tests/unit/hud/test_build_state_sizing_basis.py`'s bars/scan_setup
seams; the entry/exit harness mirrors `tests/unit/broker/test_pipeline.py`'s
own `_build_approved_thesis` convention (draft/submit/harness-appended
ReviewCompleted/approve, then the real `broker.execute_order`/
`execute_exit` verbs -- no fabricated OrderSubmitted producer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit import broker, policy, thesis
from tradekit.contracts import (
    AccountConfig,
    AssetRef,
    Bar,
    BarSeries,
    EventFilter,
    OrderRequest,
    ProposedAction,
)
from tradekit.hud import build_state
from tradekit.ledger import default_ledger

_SYMBOL = "ETH/USD"
_ASSET = AssetRef(symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_BARS = 30


@dataclass(frozen=True)
class _FakeSetup:
    signal_tags: list[str] = field(default_factory=lambda: ["fake_signal"])


def _bars(n: int = _N_BARS) -> BarSeries:
    """Flat close=100, high=105/low=95 -> ATR(14)=10 -- same proven-safe
    shape as `tests/unit/broker/test_pipeline.py::_flat_atr10_price100_bars`
    (recommended size $25 at equity $500, inside every R-rule's paper cap).
    One series serves BOTH the daily ATR fetch and the 1h ticket-price
    fetch -- nothing downstream reads `.timeframe` off it."""
    bars = [
        Bar(
            ts_open=_BAR_START + timedelta(days=i),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("95"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1d", bars=bars, source="fake-kraken")


def _clock() -> datetime:
    return _BAR_START + timedelta(days=_N_BARS + 5)


def _install_preview_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_daily_bars", lambda symbol, lookback_days: _bars()
    )
    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        lambda symbol, timeframe, lookback_days: _bars(),
    )
    monkeypatch.setattr("tradekit.mae._runtime.clock", _clock)
    # `policy._context.clock()` is a SEPARATE seam (policy may import
    # neither mae nor thesis internals) -- it must tell the same simulated
    # "now" as the mae/broker clock above, or `_trades_today_count`'s own
    # UTC-date comparison drifts against real wall-clock time and the
    # entry/exit `OrderSubmitted` events this test appends never land on
    # "today" from the probe's point of view.
    monkeypatch.setattr("tradekit.policy._context._clock", _clock)

    import tradekit.hud._build as hud_build

    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _FakeSetup())
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


def _install_submit_seams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", lambda s, tf, ld: _bars())
    monkeypatch.setattr("tradekit.mae._runtime._clock", _clock)


def _r007_hit(account_ref: str = "paper:alpha") -> object:
    order = OrderRequest(
        thesis_id="ac26-probe",
        account_ref=account_ref,
        asset=_ASSET,
        side="buy",
        order_type="limit",
        qty=Decimal("0.01"),
        limit_price=Decimal("100"),
    )
    action = ProposedAction(
        kind="submit_order",
        account_ref=account_ref,
        requested_by="ac26-probe",
        thesis_id="ac26-probe",
        order=order,
    )
    verdict = policy.evaluate(action)
    return next(hit for hit in verdict.rule_hits if hit.rule_id == "R-007")


class TestAC26PreviewsNeverCountTowardR007:
    def test_twenty_previews_then_a_real_entry_and_its_same_day_exit(
        self, monkeypatch: pytest.MonkeyPatch, thesis_kwargs: dict, make_event
    ) -> None:
        broker.create_paper_account(
            AccountConfig(
                account_ref="paper:alpha", principal_usd=Decimal("500"), max_trades_per_day=0
            )
        )

        # (a) twenty real scan-time previews -- each ledgers a real
        # ActionProposed(submit_order); none of them may count.
        _install_preview_seams(monkeypatch)
        for _ in range(20):
            build_state([_SYMBOL], captured_at=_clock(), equity_usd=Decimal("500"))

        proposed = [
            e
            for e in default_ledger().query(EventFilter(types=["ActionProposed"]))
            if e.payload.get("kind") == "submit_order"
        ]
        assert len(proposed) == 20, "sanity: twenty real scan-time previews were ledgered"

        hit = _r007_hit()
        assert hit.measured == "0", "AC-26a: twenty dead previews must not count toward R-007"
        assert hit.outcome == "pass"

        # (b) one real entry through the pipeline (mirrors test_pipeline.py's
        # own _build_approved_thesis + broker.execute_order convention).
        _install_submit_seams(monkeypatch)
        kw = dict(thesis_kwargs)
        kw["asset"] = {**thesis_kwargs["asset"], "symbol": _SYMBOL, "venue": "kraken"}
        kw["account_ref"] = "paper:alpha"
        kw["entry"] = {"order_type": "market", "valid_until": "2026-02-01T00:00:00Z"}
        thesis_id = thesis.draft(kw)
        thesis.submit(thesis_id)
        default_ledger().append(
            make_event(
                type="ReviewCompleted",
                payload={"thesis_id": thesis_id, "review_artifact_id": "rev-1", "passed": True},
            )
        )
        thesis.approve(thesis_id)
        broker.execute_order(thesis_id)

        hit = _r007_hit()
        assert hit.measured == "1", "AC-26b: one real entry must count exactly once"

        # (c) that thesis's SAME-DAY exit must not count a second time.
        broker.execute_exit(thesis_id)

        hit = _r007_hit()
        assert hit.measured == "1", "AC-26c: an exit must never be throttled/counted by R-007"
