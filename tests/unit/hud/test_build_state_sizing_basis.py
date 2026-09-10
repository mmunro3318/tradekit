"""RED (SPEC-sizing-cap.md batch RED-B, T3): `hud.build_state`'s scan-time
preview against the REAL `mae.size_position` call (`sizing_info` seam LEFT
AT ITS DEFAULT in every test here — the whole point, per SPEC-sizing-cap.md
section "hud.build_state preview (P3) — sizing_info seam LEFT REAL"). Today
`_default_sizing_info` calls `mae.size_position(symbol,
account_equity_usd=equity_usd)` with NO `price=`/`max_position_usd=` kwargs
at all — the ticket's own 1h limit price is silently ignored for sizing
purposes (P3's defect) and nothing ever clips to the $50 paper cap (T1's
defect). AC-9/AC-11(paper case) fail today for exactly those reasons.

Seams used (sanctioned, per SPEC-sizing-cap.md P3 + ASSUMPTIONS 157a/158/
159): `mae._runtime.get_daily_bars`/`get_closed_bars`/`clock` (module-
attribute patch, mirroring `test_build_state_preview_policy.py`'s own `_bars`
convention), `hud._build.scan_setup` (trivially passing), `hud._build.
open_position_symbols`. `evaluate_policy` AND `sizing_info` both stay at
their real defaults throughout this file — `sizing_info` is the surface
under test, never mocked (banned per SPEC-sizing-cap.md section 4).

ONE bars fake per test serves BOTH timeframes `mae.size_position`/`hud._build`
need: `get_daily_bars`/`get_closed_bars(..., "1d", ...)` return the F-TIGHT/
F-WIDE 30-bar daily fixture (`mae.size_position`'s own ATR(14) source);
`get_closed_bars(..., "1h", ...)` returns a >= 20-bar flat series whose close
IS the ticket's limit price (`build_state`'s own `limit_price = bars.bars[-1
].close`, hud/_build.py:533) — F-TIGHT/F-WIDE test daily != 1h close on
purpose (T2 shape) except AC-9/AC-16 where they deliberately coincide (T1
shape, per SPEC-sizing-cap.md fixture table).

`TK_DATA_DIR` isolation is the autouse `tests/conftest.py::
_tk_data_dir_isolation` fixture. `PolicyDials.load()` is left at its real
file/code defaults (`default_account_ref="paper:alpha"`,
`paper_starting_equity_usd=500`, `max_position_pct_paper=0.10` ->
`paper_max_position_usd=$50`) for AC-9/AC-10; AC-11 patches `PolicyDials.
load` directly (mirroring `test_run_once.py::_patch_dials`), never the rule
engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from tradekit import broker
from tradekit.contracts import AccountConfig, AssetRef, Bar, BarSeries
from tradekit.hud import build_state
from tradekit.policy._dials import PolicyDials

_SYMBOL = "ETH/USD"
_CAPTURED_AT = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
_MIN_HOURLY_BARS = 20  # hud._build._MIN_BARS
_N_DAILY_BARS = 30  # SPEC-sizing-cap.md fixture table: "30 daily bars flat"


@dataclass(frozen=True)
class _FakeSetup:
    """Duck-typed `scan_setup` return (ASSUMPTIONS 157a) — a trivially-
    passing setup so the funnel reaches the sizing/policy gates, same
    convention as `test_build_state_preview_policy.py::_FakeSetup`."""

    signal_tags: list[str] = field(default_factory=lambda: ["fake_signal"])


def _daily_bars(*, high: Decimal, low: Decimal, n: int = _N_DAILY_BARS) -> BarSeries:
    """F-TIGHT (high=101/low=99 -> ATR14=2) / F-WIDE (high=110/low=90 ->
    ATR14=20) daily fixture: flat open=close=100 (no gap) -> constant True
    Range = high-low on every bar -> Wilder ATR(14) seed = plain average of
    the first 14 TR values = high-low, and the recurrence keeps it there
    forever (same derivation as `test_submit.py`'s own fixture-freeze note)."""
    asset = AssetRef(
        symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    bars = [
        Bar(
            ts_open=_CAPTURED_AT - timedelta(days=n - i),
            open=Decimal("100"),
            high=high,
            low=low,
            close=Decimal("100"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-daily")


_F_TIGHT_DAILY = _daily_bars(high=Decimal("101"), low=Decimal("99"))
_F_WIDE_DAILY = _daily_bars(high=Decimal("110"), low=Decimal("90"))


def _hourly_bars(*, close: Decimal, n: int = _MIN_HOURLY_BARS) -> BarSeries:
    """Flat 1h series whose close IS the ticket's limit price — build_state's
    own `limit_price = bars.bars[-1].close` (hud/_build.py:533)."""
    asset = AssetRef(
        symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    bars = [
        Bar(
            ts_open=_CAPTURED_AT - timedelta(hours=n - i),
            open=close,
            high=close + Decimal("5"),
            low=close - Decimal("5"),
            close=close,
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=asset, timeframe="1h", bars=bars, source="fake-hourly")


def _install_funnel_seams(
    monkeypatch: pytest.MonkeyPatch, *, daily: BarSeries, hourly_close: Decimal
) -> None:
    """`sizing_info` and `evaluate_policy` are DELIBERATELY left at their
    real defaults — see module docstring. Only the mae bars/clock seams plus
    two of hud's own sanctioned test seams are patched."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    hourly = _hourly_bars(close=hourly_close)
    monkeypatch.setattr(mae_runtime, "get_daily_bars", lambda symbol, lookback_days: daily)
    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: daily if timeframe == "1d" else hourly,
    )
    monkeypatch.setattr(mae_runtime, "clock", lambda: _CAPTURED_AT)
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _FakeSetup())
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


def _create_default_paper_account() -> None:
    broker.create_paper_account(
        AccountConfig(
            account_ref="paper:alpha", principal_usd=Decimal("500.00"), max_trades_per_day=0
        )
    )


def _policy_verdict_gate(state: Any, symbol: str = _SYMBOL) -> Any:
    entry = next(e for e in state.report if e.symbol == symbol)
    return next(g for g in entry.gates if g.name == "policy_verdict")


def _patch_dials(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    monkeypatch.setattr(PolicyDials, "load", classmethod(lambda cls: PolicyDials(**overrides)))


# ---------------------------------------------------------------------------
# AC-9 -- T1 reproduction at preview
# ---------------------------------------------------------------------------


class TestAC9TightFixturePreviewCapApplied:
    def test_f_tight_daily_1h_close_100_yields_one_capped_ticket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-9, T1 reproduction at preview, cites SPEC-sizing-cap
        AC-9): F-TIGHT daily bars (ATR14=2, stop_distance=4) + 1h bars
        closing at 100. Uncapped sizing at equity $500 recommends $125
        notional ($100 * 1.25 units) — ABOVE the $50 paper cap — so real
        R-005 denies at preview and `build_state` returns ZERO tickets on
        `main` today (must FAIL, R-005-style deny pasted in the red run).
        Once P3 wires `_default_sizing_info` to pass
        `max_position_usd=PolicyDials.load().paper_max_position_usd` into
        `mae.size_position`, the clip lands BEFORE R-005 ever measures the
        notional: exactly one ticket, qty clipped to 0.5 ($50 exactly),
        `limit_price` the ticket's own 1h close (100), and the
        `policy_verdict` gate passes."""
        _create_default_paper_account()
        _install_funnel_seams(monkeypatch, daily=_F_TIGHT_DAILY, hourly_close=Decimal("100"))

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 1, (
            "AC-9: uncapped $125 notional must clip to the $50 paper cap, never deny outright"
        )
        ticket = state.tickets[0]
        assert ticket.quantity == Decimal("0.5")
        assert ticket.limit_price == Decimal("100")

        gate = _policy_verdict_gate(state)
        assert gate.passed is True, "AC-9: policy_verdict must pass once the preview obeys the cap"


# ---------------------------------------------------------------------------
# AC-10 -- price basis is the 1h close (non-discriminating, see docstring)
# ---------------------------------------------------------------------------


class TestAC10PriceBasisIsThe1hClose:
    def test_f_wide_daily_1h_close_105_ticket_prices_off_the_1h_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-10, price basis is the 1h close, cites SPEC-sizing-
        cap AC-10): F-WIDE daily bars (ATR14=20, stop_distance=40) + 1h bars
        closing at 105. ASSUMPTIONS-FLAG (see report): this AC is
        NON-DISCRIMINATING against `main` — `atr_position`'s `units =
        risk_usd / stop_distance` never depends on `price` (only ATR/
        equity/risk_pct do), so `sizing.qty` is 0.125 whether the internal
        sizing price is today's daily close (100) or tomorrow's 1h close
        (105); this test may PASS unchanged on `main`. Its value is pinning
        the ticket's OWN price basis (`limit_price`/`sl_price`, both built
        from the 1h close in `hud._build.py` regardless of this fix) and
        the ATR-bracket sl_price derivation, not the P3 defect itself."""
        _create_default_paper_account()
        _install_funnel_seams(monkeypatch, daily=_F_WIDE_DAILY, hourly_close=Decimal("105"))

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 1
        ticket = state.tickets[0]
        assert ticket.quantity == Decimal("0.125")
        assert ticket.limit_price == Decimal("105")
        assert ticket.sl_price == Decimal("65"), "sl_price = limit_price(105) - stop_distance(40)"


# ---------------------------------------------------------------------------
# AC-11 -- default_account_ref gates the cap (CONTRACT on the seam default)
# ---------------------------------------------------------------------------


class TestAC11DefaultAccountRefGatesTheCap:
    """CONTRACT (AC-11, cites SPEC-sizing-cap AC-11): calls the module-level
    seam `tradekit.hud._build.sizing_info` DIRECTLY at its real default
    (`_default_sizing_info`), never through `build_state`'s funnel walk, so
    only `mae.size_position`'s own bars seam and `PolicyDials.load` are
    patched — no scan_setup/open_position_symbols/account needed."""

    def test_advisory_ref_stays_uncapped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-`paper:` account_ref -> `max_position_usd=None` -> uncapped
        qty 1.25 (500*0.01/4 -> 1.25 units at $100). Passes BOTH before and
        after the P3 fix — today's `_default_sizing_info` already ignores
        the cap entirely (there IS no cap logic yet), so this pins the
        no-op case, not the defect."""
        import tradekit.hud._build as hud_build

        _patch_dials(monkeypatch, default_account_ref="advisory:kraken")
        monkeypatch.setattr(
            "tradekit.mae._runtime.get_daily_bars", lambda symbol, lookback_days: _F_TIGHT_DAILY
        )

        result = hud_build.sizing_info(_SYMBOL, Decimal("100"), Decimal("500"))

        assert result.qty == Decimal("1.25")

    def test_paper_ref_clips_to_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default `paper:alpha` account_ref -> `max_position_usd=$50` ->
        qty clips to 0.5 ($50/$100), `stop_distance_usd` unaffected by the
        clip (ATR-only, $4). Must FAIL today: `_default_sizing_info` does
        not pass a cap at all yet, so `qty` is the uncapped 1.25, same as
        the advisory case above."""
        import tradekit.hud._build as hud_build

        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        monkeypatch.setattr(
            "tradekit.mae._runtime.get_daily_bars", lambda symbol, lookback_days: _F_TIGHT_DAILY
        )

        result = hud_build.sizing_info(_SYMBOL, Decimal("100"), Decimal("500"))

        assert result.qty == Decimal("0.5"), "AC-11: the paper cap must clip qty to 0.5"
        assert result.stop_distance_usd == Decimal("4")


# ---------------------------------------------------------------------------
# AC-22 -- review round 24 M4 killer: F-TIGHT preview's exact clipped qty
# ---------------------------------------------------------------------------


class TestAC22FTightPreviewExactClippedQuantity:
    def test_f_tight_daily_1h_close_105_yields_the_exact_clipped_quantity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-22, kills mutant M4, cites SPEC-sizing-cap.md
        section 6): F-TIGHT daily bars (ATR14=2, stop_distance=4) + 1h bars
        closing at 105 -- a price where the uncapped notional ($131.25 =
        1.25 units * $105) still exceeds the $50 paper cap, but the CLIP
        (never a round number) exposes any mutant that quantizes/rounds
        instead of truncating: units = floor8dp(50/105) = 0.47619047
        (50/105 = 10/21 = 0.476190476190... repeating, ROUND_DOWN at 8dp
        truncates the trailing 6 to 0.47619047, never rounds up to
        0.47619048). One ticket; `quantity == Decimal("0.47619047")`;
        `quantity * limit_price <= 50` (never overshoots by a float/rounding
        hair); the `policy_verdict` gate passes."""
        _create_default_paper_account()
        _install_funnel_seams(monkeypatch, daily=_F_TIGHT_DAILY, hourly_close=Decimal("105"))

        state = build_state([_SYMBOL], captured_at=_CAPTURED_AT, equity_usd=Decimal("500"))

        assert len(state.tickets) == 1
        ticket = state.tickets[0]
        assert ticket.quantity == Decimal("0.47619047")
        assert ticket.quantity * ticket.limit_price <= Decimal("50")

        gate = _policy_verdict_gate(state)
        assert gate.passed is True
