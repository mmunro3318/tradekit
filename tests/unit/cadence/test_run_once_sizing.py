"""RED (SPEC-sizing-cap.md batch RED-B, T5): `cadence.run_once`'s entry path
end to end — real `hud.build_state`, real `thesis.draft/submit`, real
`policy.evaluate` (both preview AND binding), real `broker` — against the
T1 (R-005 cap) and T2 (R-012 sizing-basis drift) reproductions the spec
exists to fix, plus the T3 dead-account warning (P6).

Mirrors `tests/unit/cadence/test_run_once.py::TestTA5CadenceBuildStateLeftReal
::test_run_once_with_real_build_state_opens_one_paper_position` — the one
test in that file that leaves `cadence.build_state` REAL. Seams here:
`mae._runtime.get_daily_bars`/`get_closed_bars`/`_clock` (dotted-string
patch, this file's own bars/clock harness — reproduced rather than imported
cross-file, matching this repo's existing convention per that file's module
docstring), `policy._context._clock` (promotion_status's own clock seam,
same "both clocks must tell the same simulated time" fix note as
`test_run_once.py::_install_seams`), and `hud._build.scan_setup` (gated to
ONE symbol, `_SYMBOL`, out of `hud.DEFAULT_SYMBOLS`' full universe — same
narrowing technique `TestTA5CadenceBuildStateLeftReal` uses, since
`hud.DEFAULT_SYMBOLS` itself is not itself part of this spec's fix).
`sizing_info` and `evaluate_policy` are NEVER patched — this file drives the
real `mae.size_position` calls at BOTH the preview and binding sizing sites,
which is the entire point (SPEC-sizing-cap.md section "cadence.run_once
(P5, P6)").

One bars fake serves BOTH timeframes: `get_daily_bars`/`get_closed_bars(...,
"1d", ...)` return the F-TIGHT/F-WIDE 30-bar daily fixture (`mae.
size_position`'s own ATR(14) source, and `thesis._submit`'s own daily-close
snapshot source); `get_closed_bars(..., "1h", ...)` returns a flat 20-bar
series whose close is the ticket's own price — read by BOTH `hud._build`'s
funnel (the preview's limit_price) and `cadence._paper_equity_usd`'s own
mark-to-market walk.

Fixture-freeze arithmetic (hand math, identical derivation to
`test_build_state_sizing_basis.py`/`test_submit_sizing_basis.py` — repeated
here per this repo's own "each test file owns its fixtures" convention):
  - F-TIGHT: ATR14=2, stop_distance=4. At price 100, equity $500: risk_usd=5,
    uncapped units=1.25, uncapped size=$125 (> $50 cap) -> clips to 0.5
    units, $50 exactly.
  - F-WIDE: ATR14=20, stop_distance=40. At price 105: units=5/40=0.125
    (price-independent), size=$13.125. At price 100 (equity $400): risk_usd
    =4, units=4/40=0.1, size=$10.00.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tradekit import broker
from tradekit.cadence import run_once
from tradekit.contracts import AccountConfig, AssetRef, Bar, BarSeries, EventFilter
from tradekit.ledger import default_ledger
from tradekit.policy._dials import PolicyDials

_SYMBOL = "ETH/USD"
_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_DAILY_BARS = 30
_N_HOURLY_BARS = 20
_ENTRY_NOW = _BAR_START + timedelta(days=_N_DAILY_BARS + 5)

_ASSET = AssetRef(symbol=_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))


def _daily_bars(*, high: Decimal, low: Decimal, n: int = _N_DAILY_BARS) -> BarSeries:
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


_F_TIGHT_DAILY = _daily_bars(high=Decimal("101"), low=Decimal("99"))
_F_WIDE_DAILY = _daily_bars(high=Decimal("110"), low=Decimal("90"))


def _hourly_bars(*, close: Decimal, n: int = _N_HOURLY_BARS) -> BarSeries:
    bars = [
        Bar(
            ts_open=_ENTRY_NOW - timedelta(hours=n - i),
            open=close,
            high=close + Decimal("5"),
            low=close - Decimal("5"),
            close=close,
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=_ASSET, timeframe="1h", bars=bars, source="fake-hourly")


def _clock() -> datetime:
    return _ENTRY_NOW


def _install_cadence_seams(
    monkeypatch: pytest.MonkeyPatch, *, daily: BarSeries, hourly_close: Decimal
) -> None:
    hourly = _hourly_bars(close=hourly_close)

    def _get_closed_bars(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return daily if timeframe == "1d" else hourly

    def _get_daily_bars(symbol: str, lookback_days: int) -> BarSeries:
        return daily

    monkeypatch.setattr("tradekit.mae._runtime.get_daily_bars", _get_daily_bars)
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", _clock)
    monkeypatch.setattr("tradekit.policy._context._clock", _clock)

    import tradekit.hud._build as hud_build

    monkeypatch.setattr(
        hud_build,
        "scan_setup",
        lambda symbol: SimpleNamespace(
            signal_tags=["fake_signal"] if symbol == _SYMBOL else []
        ),
    )


def _fake_dials(**overrides: Any) -> PolicyDials:
    return PolicyDials(**overrides)


def _patch_dials(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    monkeypatch.setattr(PolicyDials, "load", classmethod(lambda cls: _fake_dials(**overrides)))


def _create_paper_account(principal_usd: Decimal) -> None:
    broker.create_paper_account(
        AccountConfig(account_ref="paper:alpha", principal_usd=principal_usd, max_trades_per_day=0)
    )


def _thesis_drafted_events(symbol: str | None = None) -> list:
    events = default_ledger().query(EventFilter(types=["ThesisDrafted"]))
    if symbol is None:
        return events
    return [
        e
        for e in events
        if (e.payload.get("contract") or {}).get("asset", {}).get("symbol") == symbol
    ]


def _thesis_drafted_count(symbol: str | None = None) -> int:
    return len(_thesis_drafted_events(symbol))


def _thesis_rejected_count_for(thesis_ids: set[str]) -> int:
    events = default_ledger().query(EventFilter(types=["ThesisRejected"]))
    return sum(1 for e in events if e.payload.get("thesis_id") in thesis_ids)


def _sizing_computed_for(symbol: str) -> dict:
    events = default_ledger().query(EventFilter(types=["SizingComputed"]))
    matches = [e for e in events if e.payload.get("symbol") == symbol]
    assert matches, f"no SizingComputed event found for {symbol!r}"
    return matches[-1].payload


def _digest_content(tmp_path: Path) -> str:
    digest_files = list(tmp_path.glob("DIGEST-*.md"))
    assert len(digest_files) == 1, "exactly one digest file for the UTC day of this run"
    return digest_files[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-15 -- the T2 reproduction: preview and binding must agree
# ---------------------------------------------------------------------------


class TestAC15T2ReproductionOneSymbolOpensAtBinding:
    def test_f_wide_1h_close_105_opens_one_position_with_matching_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEAM/BEHAVIOR (AC-15, the T2 reproduction, cites SPEC-sizing-cap
        AC-15): F-WIDE daily bars + 1h bars closing at 105, a fresh
        `paper:alpha` account (principal $500). Once preview
        (`hud.build_state`) and binding (`thesis.submit`) both size off
        price=105/equity=$500-dial, they agree ($13.125) and R-012 passes at
        binding — one paper position opens, zero denials. Today (`main`):
        the preview sizes off the live `_paper_equity_usd` return at the
        DAILY close (100, never 105 — P3/P5's defects), thesis.submit sizes
        off the dial equity but ALSO the daily close (no limit_price
        survives `_confirm_entry`'s current overwrite) — the resulting
        notional deviation trips R-012 at binding: `thesis.reject` fires, a
        'entry denied by policy' warning is appended, and zero positions
        open. Must FAIL today."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_WIDE_DAILY, hourly_close=Decimal("105"))
        _create_paper_account(Decimal("500"))

        run_once(digest_dir=tmp_path)

        positions = broker.get("paper:alpha").positions()
        assert [p.symbol for p in positions] == [_SYMBOL], (
            "AC-15: exactly one paper position must open for the symbol"
        )

        content = _digest_content(tmp_path)
        assert "entry denied by policy" not in content, (
            "AC-15: R-012 must not deny once preview and binding share price/equity/cap"
        )

        drafted = _thesis_drafted_events(_SYMBOL)
        assert len(drafted) == 1, "AC-15: exactly one ThesisDrafted for the symbol"
        thesis_ids = {e.payload["thesis_id"] for e in drafted}
        assert _thesis_rejected_count_for(thesis_ids) == 0, "AC-15: zero ThesisRejected"

        entry = drafted[0].payload["contract"]["entry"]
        assert set(entry.keys()) == {"order_type", "limit_price", "valid_until"}, (
            "P5: the market entry must keep carrying limit_price, never drop it"
        )
        assert entry["order_type"] == "market"
        assert entry["limit_price"] == "105"
        assert entry["valid_until"], "P5: valid_until must still be preserved verbatim"


# ---------------------------------------------------------------------------
# AC-16 -- the T1 reproduction: the cap-clipped ticket opens at cap
# ---------------------------------------------------------------------------


class TestAC16T1ReproductionPositionOpensAtCap:
    def test_f_tight_1h_close_100_opens_capped_position(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEAM/BEHAVIOR (AC-16, the T1 reproduction end-to-end, cites
        SPEC-sizing-cap AC-16): F-TIGHT daily bars + 1h close 100 ->
        uncapped preview notional is $125 (> the $50 paper cap), so R-005
        denies at PREVIEW and `build_state` never even produces a ticket on
        `main` today — zero entries, zero positions. Must FAIL today. After
        the fix, the ticket clips to qty 0.5 ($50 exactly) and a position
        opens; the EXECUTED qty is `recorded_size / entry_price` where
        `entry_price` is the snapshot's DAILY close (100, equal to the 1h
        close by this fixture's own design) -> 50/100 = 0.5 exactly, R-005
        satisfied by construction."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_TIGHT_DAILY, hourly_close=Decimal("100"))
        _create_paper_account(Decimal("500"))

        run_once(digest_dir=tmp_path)

        positions = broker.get("paper:alpha").positions()
        assert len(positions) == 1, "AC-16: the $125-uncapped ticket must clip to $50 and open"
        position = positions[0]
        assert position.symbol == _SYMBOL
        assert position.qty == Decimal("0.5")
        assert position.qty * Decimal("100") == Decimal("50")


# ---------------------------------------------------------------------------
# AC-17 -- sizing basis is the dial, not live cash
# ---------------------------------------------------------------------------


class TestAC17SizingBasisIsTheDialNotLiveCash:
    def test_f_wide_1h_105_account_400_sizes_at_dial_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-17, sizing basis is the dial, cites SPEC-sizing-cap
        AC-17): F-WIDE + 1h close 105, `paper:alpha` created with principal
        $400 (LESS than the $500 dial). Both the preview and binding sizing
        must read `PolicyDials.paper_starting_equity_usd` ($500), never the
        live $400 cash — at $400 the recommended size would be $10.50
        (risk_usd=4, units=4/40=0.1, size=0.1*105=10.50), not $13.125.
        Today: the preview sizes off the live ~$400 equity while
        thesis.submit sizes off the $500 dial regardless — a pure
        equity-basis mismatch (price agrees at 105 is irrelevant here) trips
        R-012 at binding and denies. Must FAIL today."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_WIDE_DAILY, hourly_close=Decimal("105"))
        _create_paper_account(Decimal("400"))

        run_once(digest_dir=tmp_path)

        positions = broker.get("paper:alpha").positions()
        assert [p.symbol for p in positions] == [_SYMBOL], "AC-17: the position must open"

        sizing = _sizing_computed_for(_SYMBOL)
        assert Decimal(str(sizing["account_equity_usd"])) == Decimal("500"), (
            "AC-17: sizing must read the DIAL, never the live $400 cash"
        )
        assert sizing["sizing"]["recommended_size_usd"] == pytest.approx(13.125)


# ---------------------------------------------------------------------------
# AC-18 -- T3, dead account is loud and skips entries
# ---------------------------------------------------------------------------


class TestAC18DeadAccountIsLoudAndSkipsEntries:
    def test_no_account_created_appends_loud_warning_and_skips_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-18, T3, dead account is loud and skips entries,
        cites SPEC-sizing-cap AC-18): F-WIDE + a passing setup, but NO
        `AccountCreated` for `paper:alpha` -> `_paper_equity_usd` returns
        $0 (no principal, no fills). After P6, `run_once` must append a
        digest `### Warnings` line naming the dead account (all of
        'paper:alpha', '<= 0', 'no AccountCreated', 'tk account
        create-paper') and skip `_run_entries` entirely (zero
        ThesisDrafted) while still rendering `### Drought`, without raising.
        Today: the preview instead sizes at equity 0, `atr_position` raises
        `ValueError` per symbol (contained as a failed 'sizing' gate) ->
        also zero tickets/zero ThesisDrafted, but with NONE of the pinned
        warning substrings, since the loud-account check does not exist
        yet. Must FAIL today on the missing warning line."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_WIDE_DAILY, hourly_close=Decimal("105"))
        # Deliberately no broker.create_paper_account call.

        run_once(digest_dir=tmp_path)

        content = _digest_content(tmp_path)
        sections = content.split("### Warnings", 1)
        assert len(sections) == 2, (
            "AC-18: a ### Warnings section must exist naming the dead account"
        )
        warning_text = sections[1]
        for substring in ("paper:alpha", "<= 0", "no AccountCreated", "tk account create-paper"):
            assert substring in warning_text, f"AC-18: warning text must contain {substring!r}"

        assert _thesis_drafted_count() == 0, "AC-18: zero ThesisDrafted when entries are skipped"
        assert "### Drought" in content, "AC-18: drought section must still render"


# ---------------------------------------------------------------------------
# AC-19 -- T3 regression pin: a live account never fires the dead-account warning
# ---------------------------------------------------------------------------


class TestAC19LiveAccountDoesNotTriggerDeadAccountWarning:
    def test_created_account_principal_500_has_no_dead_account_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (AC-19, T3 regression pin, cites SPEC-sizing-cap AC-19):
        a genuinely created `paper:alpha` account (principal $500) must
        never trip the T3 dead-account warning. Passes BOTH before and
        after P6 — today there is no such warning text at all; after P6
        the `equity_usd > 0` branch simply never appends it."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_WIDE_DAILY, hourly_close=Decimal("105"))
        _create_paper_account(Decimal("500"))

        run_once(digest_dir=tmp_path)

        content = _digest_content(tmp_path)
        assert "no AccountCreated" not in content


# ---------------------------------------------------------------------------
# AC-25 -- end-to-end, review round 24 F1: a claimed strategy's size_scale
# survives preview -> binding without dying at R-012.
# ---------------------------------------------------------------------------


class TestAC25ClaimedStrategyScalesEndToEnd:
    def test_s4_reversion_claim_opens_a_half_size_position(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEAM/BEHAVIOR (AC-25, cites SPEC-sizing-cap.md section 6, the
        review's own F1 test): F-TIGHT daily bars + 1h close 100,
        `scan_setup` arming `s4_reversion` (a real `mae.STRATEGY_BY_KEY` key,
        `size_scale=Decimal("0.5")`) for the one symbol under test. Uncapped
        $125 clips to $50 (AC-16's own T1 reproduction), THEN scales to
        $25/0.25 units -- must FAIL before the F1 fix: `build_state` used to
        multiply `sizing.qty` by `size_scale` AFTER calling `sizing_info`,
        while `thesis.submit` never scaled at all, so the ticket's own
        0.25-unit qty (or the deny path) never matched `thesis.submit`'s
        unscaled $50 SizingComputed record -> R-012 denied every S4 draft at
        binding ('entry denied by policy'). After the fix both call sites
        scale identically: one paper position opens, qty 0.25, no denial,
        and the ledgered SizingComputed is $25.0."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        _install_cadence_seams(monkeypatch, daily=_F_TIGHT_DAILY, hourly_close=Decimal("100"))
        monkeypatch.setattr(
            "tradekit.hud._build.scan_setup",
            lambda symbol: SimpleNamespace(
                signal_tags=["at_support"] if symbol == _SYMBOL else [],
                strategy_key="s4_reversion" if symbol == _SYMBOL else "",
            ),
        )
        _create_paper_account(Decimal("500"))

        run_once(digest_dir=tmp_path)

        positions = broker.get("paper:alpha").positions()
        assert len(positions) == 1, "AC-25: the scaled ticket must clip, scale, and still open"
        assert positions[0].symbol == _SYMBOL
        assert positions[0].qty == Decimal("0.25")

        content = _digest_content(tmp_path)
        assert "entry denied by policy" not in content, (
            "AC-25: preview and binding must scale identically -- R-012 must not deny"
        )

        sizing = _sizing_computed_for(_SYMBOL)
        assert sizing["sizing"]["recommended_size_usd"] == 25.0
        assert sizing["sizing"]["size_scale"] == 0.5
