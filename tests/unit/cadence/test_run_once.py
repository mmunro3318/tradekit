"""`tradekit.cadence.run_once` -- T3's autonomous paper cadence runner
(SPEC-cadence.md T3, docs/specs/SPEC-cadence.md:126-173). RED this batch:
`run_once`/`CadenceAccountRefused` do not exist yet in `tradekit.cadence`
(the module currently only exports T2's `exit_trigger`) -- the top-level
import below is EXPECTED to fail at collection (ImportError naming the
missing attribute), the correct red reason for every test in this file.

`scripts/run_cadence.py` itself is NOT unit-tested here (per the spec's own
"the script body is a thin main() over a testable run_once(...) function"
pin) -- this file tests `cadence.run_once` only.

ASSUMPTIONS-FLAG 1 (signature, escape hatch -- CTO adjudicates): the spec
pins `run_once`'s ALGORITHM (guard -> entries -> exits -> digest) but not
its exact parameter list. This file pins the MINIMAL keyword-only surface
the spec's own prose requires: `run_once(*, digest_dir: Path = <default>)`
-- `digest_dir` because SPEC-cadence.md:183-186 explicitly flags "digest via
tmp_path redirection seam if needed" as a red-time seam-design decision, and
tests below always pass `digest_dir=tmp_path` explicitly (never touching the
real `docs/digest/`). No other parameter is pinned by the spec text, so none
is passed here; a GREEN dev pass that needs additional required parameters
should update these calls and reconcile in ASSUMPTIONS.md.

ASSUMPTIONS-FLAG 2 (active-theses-with-symbol enumeration, escape hatch):
`ledger.models.active_theses()` returns `(thesis_id, account_ref,
strategy_tag)` -- NO symbol column (the `theses` projection carries none,
per `hud/_build.py::_default_open_position_symbols`'s own docstring, which
has to re-walk `ThesisDrafted` events to recover it). `run_once` needs
symbol-keyed active-thesis info for BOTH the entry skip-set (T3-AC-3) and
the exit trigger evaluation (contract stop/target/horizon per active
thesis) -- there is no existing single public verb that returns this
mapping directly. This file does NOT assume how `run_once` derives it
internally (no test mocks a specific private helper); every test below
drives REAL `thesis`/`broker` verbs to build genuine ledger state and only
asserts observable outcomes (positions, ledger events, promotion_status),
so it stays green regardless of which internal walk the dev pass picks.
Flagging this as a probable small-addition gap (e.g. a
`ledger.models.active_theses_with_symbol()` accessor) for the CTO to
adjudicate.

ASSUMPTIONS-FLAG 3 (digest content wording, escape hatch): SPEC-cadence.md
T3-AC-5 pins the digest's SECTIONS (entries, exits, per-symbol attrition,
per-strategy prefilter-kill counts, promotion summary, drought line,
warnings) but not exact wording. Per the dispatch's own "substring pins per
175.4, not exact formats" instruction, this file pins the loosest honest
substrings: the literal ticket/thesis symbol, the exit reason word
("target"/"stop"/"horizon"), the fabricated attrition `killed_by` stage
name, and a case-insensitive "drought" marker on a zero-entry/zero-exit
run. A GREEN dev pass using different wording for the drought marker itself
must reconcile via ASSUMPTIONS.md (this is the one substring genuinely
invented by this red pass, not derivable from any existing sibling module).

Bars/clock/account harness below is REUSED verbatim in spirit from
`tests/unit/broker/test_pipeline.py`'s own `_flat_atr10_price100_bars` /
`_fake_submit_get_closed_bars` / `_fake_submit_clock` (same flat ATR(10)=10,
price=100, equity=500 -> recommended_size_usd=25 derivation documented
there) -- reproduced here (not imported cross-file, matching this
repo's existing convention of each test file owning its own fixtures) so
this file's fixtures don't silently drift if that file's are ever edited
for unrelated reasons.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ulid import ULID

from tradekit import broker, policy, thesis

# The module import itself is expected to fail until `run_once` /
# `CadenceAccountRefused` exist -- correct RED collection error.
from tradekit.cadence import CadenceAccountRefused, run_once
from tradekit.contracts import (
    AdvisoryTicket,
    AssetRef,
    Bar,
    BarSeries,
    EventFilter,
    HudState,
)
from tradekit.ledger import default_ledger
from tradekit.policy._dials import PolicyDials

_ASSET = AssetRef(symbol="ETH/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
_OTHER_ASSET = AssetRef(
    symbol="SOL/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
)
_BAR_START = datetime(2026, 1, 1, tzinfo=UTC)
_N_BARS = 20
_ENTRY_NOW = _BAR_START + timedelta(days=_N_BARS + 5)  # 2026-01-25, matches test_pipeline


def _flat_bars(asset: AssetRef, price: Decimal = Decimal("100"), n: int = _N_BARS) -> BarSeries:
    """Flat open=close=price, high=price+5/low=price-5 -> Wilder ATR(14)=10
    at price=100 (`test_pipeline.py`'s own proven-safe sizing derivation:
    equity=500 paper_starting_equity_usd -> recommended_size_usd=25.00,
    inside every R-rule cap)."""
    bars = [
        Bar(
            ts_open=_BAR_START + timedelta(days=i),
            open=price,
            high=price + Decimal("5"),
            low=price - Decimal("5"),
            close=price,
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


def _target_breach_bars(asset: AssetRef, price: Decimal, n: int = 3) -> BarSeries:
    """A short recent run of bars whose HIGH/CLOSE clears `price` (a target
    touch, `_grading.py::_satisfied`'s own `price_touch`/`gte` rule: measured
    = bar.high for a `cmp="gte"` predicate) -- used to make BOTH
    `exit_trigger` (close>=target) and `thesis.grade`'s real criteria walk
    (bar.high>=target_price) agree the target fired, honestly, off the same
    fixture."""
    bars = [
        Bar(
            ts_open=_BAR_START + timedelta(days=_N_BARS + i),
            open=price,
            high=price + Decimal("10"),
            low=price - Decimal("1"),
            close=price + Decimal("5"),
            volume=Decimal("1000"),
        )
        for i in range(n)
    ]
    return BarSeries(asset=asset, timeframe="1d", bars=bars, source="fake-kraken")


class _BarsClockHolder:
    """Mutable seam state -- monkeypatched ONCE per test via the dotted
    string path (`thesis.submit`/`grade`'s sanctioned seam), mutated
    in-place between an entry run and an exit run so both use the SAME
    monkeypatch installation (mirrors the codebase's own "no real clock"
    TD-17 discipline while still letting a round-trip test move time
    forward)."""

    def __init__(self, bars: BarSeries, now: datetime) -> None:
        self.bars = bars
        self.now = now

    def get_closed_bars(self, symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return self.bars

    def clock(self) -> datetime:
        return self.now


def _install_seams(monkeypatch: pytest.MonkeyPatch, holder: _BarsClockHolder) -> None:
    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", holder.get_closed_bars)
    monkeypatch.setattr("tradekit.mae._runtime._clock", holder.clock)


def _fake_dials(**overrides: Any) -> PolicyDials:
    return PolicyDials(**overrides)


def _patch_dials(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    monkeypatch.setattr(PolicyDials, "load", classmethod(lambda cls: _fake_dials(**overrides)))


def _ticket(
    pair: str = "ETH/USD",
    *,
    limit_price: str = "100",
    quantity: str = "1",
    tp_price: str = "110",
    sl_price: str = "90",
    strategy_key: str = "",
    created_at: datetime = _ENTRY_NOW,
) -> AdvisoryTicket:
    """A self-consistent `AdvisoryTicket` a real confirm chain can consume.
    Field values mirror `tests/unit/hud/test_serve.py::TICKET_BODY`'s shape
    (proven to build a valid `ThesisContract` through `_serve._build_contract`)."""
    return AdvisoryTicket(
        pair=pair,
        side="buy",
        mode="spot",
        order_type="limit",
        limit_price=Decimal(limit_price),
        quantity=Decimal(quantity),
        est_total_usd=Decimal(limit_price) * Decimal(quantity),
        oso="bracket",
        tp_price=Decimal(tp_price),
        tp_distance_pct=Decimal("0.10"),
        sl_price=Decimal(sl_price),
        sl_distance_pct=Decimal("0.10"),
        est_pnl_tp_usd=Decimal("1"),
        est_pnl_sl_usd=Decimal("1"),
        est_fee_usd=Decimal("0.01"),
        trigger_signal="last",
        post_only=False,
        tif="gtc",
        warnings=(),
        thesis_id=f"interim-thesis-{pair.replace('/', '-').lower()}",
        verdict_id=str(ULID()),
        created_at=created_at,
        strategy_key=strategy_key,
    )


def _hud_state(
    tickets: tuple[AdvisoryTicket, ...] = (),
    *,
    attrition: tuple[dict[str, Any], ...] = (),
    generated_at: datetime = _ENTRY_NOW,
) -> HudState:
    return HudState(generated_at=generated_at, tickets=tickets, report=(), attrition=attrition)


def _drought_attrition() -> tuple[dict[str, Any], ...]:
    """A fabricated attrition trail whose `killed_by` names an S4
    regime-prefilter kill -- the exact stage-name convention
    `mae/_strategies.py`/`hud/_build.py:202` already use
    (`f"{strategy_def.key} regime_prefilter"`), so the digest's
    per-strategy prefilter-kill-count section (T3-AC-5) has something
    genuine to count."""
    return (
        {
            "symbol": "AKT/USD",
            "timeframe": "1h",
            "stages": [
                {"name": "bars", "outcome": "pass", "observed": "24 closed bars"},
                {
                    "name": "s4_reversion regime_prefilter",
                    "outcome": "fail",
                    "observed": "regime not restricted",
                },
            ],
            "killed_by": "s4_reversion regime_prefilter",
        },
    )


def _thesis_drafted_count(symbol: str | None = None) -> int:
    events = default_ledger().query(EventFilter(types=["ThesisDrafted"]))
    if symbol is None:
        return len(events)
    return sum(
        1
        for e in events
        if (e.payload.get("contract") or {}).get("asset", {}).get("symbol") == symbol
    )


def _all_events() -> list:
    return default_ledger().query(EventFilter())


# ---------------------------------------------------------------------------
# T3-AC-1 -- paper-only refusal
# ---------------------------------------------------------------------------


class TestT3AC1PaperOnlyRefusal:
    def test_non_paper_default_account_ref_refuses_loudly_before_anything_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT (T3-AC-1): a non-`paper:`-prefixed
        `PolicyDials.default_account_ref` raises `CadenceAccountRefused`
        BEFORE `build_state` is ever called (zero evaluation) and appends
        ZERO ledger events (zero orders, zero mutations)."""
        _patch_dials(monkeypatch, default_account_ref="live:unconfirmed-demo")

        def _must_not_be_called(*args: Any, **kwargs: Any) -> HudState:
            raise AssertionError("build_state must never be called off-paper (T3-AC-1)")

        from tradekit import cadence

        monkeypatch.setattr(cadence, "build_state", _must_not_be_called)

        assert _all_events() == [], "sanity: fresh isolated ledger starts empty"

        with pytest.raises(CadenceAccountRefused):
            run_once(digest_dir=tmp_path)

        assert _all_events() == [], (
            "T3-AC-1: the refusal must precede any ledger mutation whatsoever"
        )

    def test_paper_prefixed_account_ref_does_not_raise_cadence_account_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT (T3-AC-1, negative case): a `paper:`-prefixed account
        clears the guard -- `run_once` proceeds into `build_state` (here
        faked to a zero-ticket drought so this test stays focused on the
        guard, not the funnel)."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")

        from tradekit import cadence

        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: _hud_state())

        run_once(digest_dir=tmp_path)  # must not raise


# ---------------------------------------------------------------------------
# T3-AC-2 -- funnel-only + drought
# ---------------------------------------------------------------------------


class TestT3AC2FunnelOnlyAndDrought:
    def test_zero_tickets_submits_nothing_and_still_writes_the_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T3-AC-2): a `build_state` returning zero tickets must
        submit zero orders (no `ThesisDrafted`/`OrderSubmitted` events) AND
        the digest file must STILL be written, carrying the drought marker
        plus the funnel attrition/prefilter-kill sections (ASSUMPTIONS-FLAG
        3: drought wording pinned by this test)."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        from tradekit import cadence

        state = _hud_state(attrition=_drought_attrition())
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: state)

        run_once(digest_dir=tmp_path)

        assert _thesis_drafted_count() == 0, "T3-AC-2: zero tickets -> zero submissions"
        assert broker.get("paper:alpha").positions() == []

        digest_files = list(tmp_path.glob("DIGEST-*.md"))
        assert len(digest_files) == 1, "T3-AC-5: one digest file for the UTC day of this run"
        content = digest_files[0].read_text(encoding="utf-8")
        assert "drought" in content.lower(), (
            "ASSUMPTIONS-FLAG 3: drought marker wording pinned here, reconcile if the dev "
            "pass names it differently"
        )
        assert "AKT/USD" in content, "T3-AC-5: per-symbol attrition must be present"
        assert "s4_reversion regime_prefilter" in content, (
            "T3-AC-5: per-strategy prefilter-kill count section must name the real stage"
        )

    def test_tickets_present_submits_only_for_ticket_symbols(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T3-AC-2): with a real ticket for ETH/USD only, exactly
        one entry is submitted, for that symbol -- never a symbol the
        (faked) funnel didn't ticket."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        holder = _BarsClockHolder(_flat_bars(_ASSET), _ENTRY_NOW)
        _install_seams(monkeypatch, holder)

        from tradekit import cadence

        state = _hud_state((_ticket("ETH/USD"),))
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: state)

        run_once(digest_dir=tmp_path)

        assert _thesis_drafted_count("ETH/USD") == 1
        assert _thesis_drafted_count("SOL/USD") == 0
        positions = broker.get("paper:alpha").positions()
        assert [p.symbol for p in positions] == ["ETH/USD"], (
            "T3-AC-2: only the ticketed symbol gets an open position"
        )


# ---------------------------------------------------------------------------
# T3-AC-3 -- skip open-position / active-thesis symbols
# ---------------------------------------------------------------------------


class TestT3AC3SkipOpenOrActiveSymbols:
    def _seed_active_thesis(
        self, monkeypatch: pytest.MonkeyPatch, make_event, thesis_kwargs: dict, holder
    ) -> str:
        """Real draft/submit/[review]/approve/execute_order round trip
        (mirrors `test_pipeline.py::_build_approved_thesis` +
        `broker.execute_order`), producing a genuinely `active` thesis with
        an open ETH/USD position -- never a fabricated `ThesisActivated`
        harness event."""
        kw = dict(thesis_kwargs)
        kw["asset"] = {**thesis_kwargs["asset"], "symbol": "ETH/USD", "venue": "kraken"}
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
        return thesis_id

    def test_symbol_with_open_position_and_active_thesis_gets_no_new_entry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_event,
        thesis_kwargs: dict,
    ) -> None:
        """BEHAVIOR (T3-AC-3): a symbol already carrying an open
        position/active thesis is skipped for new entries EVEN WHEN the
        (faked) funnel still tickets it -- one position per symbol."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        holder = _BarsClockHolder(_flat_bars(_ASSET), _ENTRY_NOW)
        _install_seams(monkeypatch, holder)

        existing_thesis_id = self._seed_active_thesis(
            monkeypatch, make_event, thesis_kwargs, holder
        )
        assert thesis._machine.derive_state(default_ledger(), existing_thesis_id) == "active"
        drafted_before = _thesis_drafted_count("ETH/USD")

        from tradekit import cadence

        state = _hud_state((_ticket("ETH/USD"),))
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: state)

        run_once(digest_dir=tmp_path)

        assert _thesis_drafted_count("ETH/USD") == drafted_before, (
            "T3-AC-3: no NEW ThesisDrafted for a symbol with an open position/active thesis"
        )
        positions = broker.get("paper:alpha").positions()
        assert len(positions) == 1, "T3-AC-3: still exactly one position, never doubled"

    def test_active_but_flat_thesis_still_skips_new_entries(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        make_event,
        thesis_kwargs: dict,
    ) -> None:
        """BEHAVIOR (T3-AC-3, active-but-flat branch): an ACTIVE thesis
        whose position has been zeroed by an out-of-band fill (mirrors
        `test_pipeline.py::test_execute_exit_on_an_active_but_flat_thesis_
        raises_exit_nothing_to_close`'s own harness) still counts as
        'active thesis' for the skip rule, independent of `positions()`."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        holder = _BarsClockHolder(_flat_bars(_ASSET), _ENTRY_NOW)
        _install_seams(monkeypatch, holder)

        existing_thesis_id = self._seed_active_thesis(
            monkeypatch, make_event, thesis_kwargs, holder
        )
        entry_fill = next(
            e
            for e in default_ledger().query(EventFilter(types=["FillRecorded"]))
            if e.payload.get("thesis_id") == existing_thesis_id
        )
        qty = Decimal(str(entry_fill.payload["qty"]))
        price = Decimal(str(entry_fill.payload["price"]))
        default_ledger().append(
            make_event(
                type="FillRecorded",
                ts=_ENTRY_NOW + timedelta(minutes=1),
                payload={
                    "order_id": "manual-close-1",
                    "thesis_id": existing_thesis_id,
                    "account_ref": "paper:alpha",
                    "ts_utc": (_ENTRY_NOW + timedelta(minutes=1)).isoformat(),
                    "price": str(price),
                    "qty": str(qty),
                    "fees_usd": "0",
                    "fee_asset_qty": "0",
                    "side": "sell",
                    "symbol": "ETH/USD",
                    "quote_snapshot": {},
                },
            )
        )
        assert broker.get("paper:alpha").positions() == [], "sanity: harness fill flattens it"
        assert thesis._machine.derive_state(default_ledger(), existing_thesis_id) == "active", (
            "sanity: a raw FillRecorded never itself advances thesis lifecycle state"
        )
        drafted_before = _thesis_drafted_count("ETH/USD")

        from tradekit import cadence

        state = _hud_state((_ticket("ETH/USD"),))
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: state)

        run_once(digest_dir=tmp_path)

        assert _thesis_drafted_count("ETH/USD") == drafted_before, (
            "T3-AC-3: an active-but-flat thesis STILL skips a new entry for its symbol"
        )


# ---------------------------------------------------------------------------
# T3-AC-4 -- full paper round trip (entry run, then exit run)
# ---------------------------------------------------------------------------


class TestT3AC4RoundTrip:
    def test_entry_then_trigger_satisfying_exit_grades_the_thesis_and_advances_promotion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BEHAVIOR (T3-AC-4, the sprint's honest end-to-end): run 1 tickets
        ETH/USD and enters it through the real funnel/pipeline; run 2 (bars
        moved to breach the ticket's own tp_price=110, clock still inside
        the 168h manual horizon) fires `exit_trigger`'s "target" branch,
        `execute_exit` flattens the position, and `run_once` grades the
        thesis -- `policy.promotion_status()`'s current-series graded count
        increments by exactly one."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        holder = _BarsClockHolder(_flat_bars(_ASSET), _ENTRY_NOW)
        _install_seams(monkeypatch, holder)

        from tradekit import cadence

        entry_state = _hud_state((_ticket("ETH/USD", tp_price="110", sl_price="90"),))
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: entry_state)

        run_once(digest_dir=tmp_path)  # entry run

        positions = broker.get("paper:alpha").positions()
        assert len(positions) == 1 and positions[0].symbol == "ETH/USD", (
            "sanity: the entry run must have opened exactly one ETH/USD position"
        )
        active = default_ledger().models.active_theses()
        assert len(active) == 1, "sanity: exactly one active thesis after the entry run"
        thesis_id = active[0].thesis_id

        baseline_graded = policy.promotion_status()["current_series"]["counts"]["graded"]

        # Move clock forward (still inside the manual 168h/+7d horizon) and
        # swap in bars whose high/close clear tp_price=110 -- satisfies BOTH
        # `exit_trigger` (close>=target) and the real grading walk
        # (bar.high>=target_price, `_grading.py::_satisfied`).
        holder.now = _ENTRY_NOW + timedelta(hours=2)
        holder.bars = _target_breach_bars(_ASSET, Decimal("110"))

        drought_state = _hud_state()  # zero NEW tickets this run -- exits only
        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: drought_state)

        run_once(digest_dir=tmp_path)  # exit run

        assert broker.get("paper:alpha").positions() == [], (
            "T3-AC-4: the position must be flat after the trigger-satisfying exit run"
        )
        graded_events = [
            e
            for e in default_ledger().query(EventFilter(types=["ThesisGraded"]))
            if e.payload.get("thesis_id") == thesis_id
        ]
        assert len(graded_events) == 1, "T3-AC-4: the thesis must be graded exactly once"
        assert graded_events[0].payload["outcome"] == "PASS", (
            "sanity: a target-touch grades PASS (this file's own bars clear tp_price)"
        )

        after_graded = policy.promotion_status()["current_series"]["counts"]["graded"]
        assert after_graded == baseline_graded + 1, (
            "T3-AC-4: promotion_status()'s graded count increments by exactly one round trip"
        )

        digest_files = sorted(tmp_path.glob("DIGEST-*.md"))
        exit_digest = digest_files[-1].read_text(encoding="utf-8")
        assert "ETH/USD" in exit_digest
        assert "target" in exit_digest.lower(), (
            "T3-AC-5: the exit's trigger reason must appear in the digest"
        )


# ---------------------------------------------------------------------------
# T3-AC-5 -- digest file mechanics (naming, append-per-run)
# ---------------------------------------------------------------------------


class TestT3AC5DigestMechanics:
    def test_two_runs_same_utc_day_append_to_the_same_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT (T3-AC-5): "append-per-run" -- two `run_once` calls on
        the same UTC day produce ONE digest file whose content grows
        (never two files, never an overwrite that loses the first run's
        section)."""
        _patch_dials(monkeypatch, default_account_ref="paper:alpha")
        from tradekit import cadence

        monkeypatch.setattr(cadence, "build_state", lambda *a, **kw: _hud_state())

        run_once(digest_dir=tmp_path)
        files_after_first = list(tmp_path.glob("DIGEST-*.md"))
        assert len(files_after_first) == 1
        content_after_first = files_after_first[0].read_text(encoding="utf-8")

        run_once(digest_dir=tmp_path)
        files_after_second = list(tmp_path.glob("DIGEST-*.md"))
        assert len(files_after_second) == 1, (
            "T3-AC-5: still exactly one file for the UTC day -- append, not a new file per run"
        )
        content_after_second = files_after_second[0].read_text(encoding="utf-8")
        assert len(content_after_second) > len(content_after_first), (
            "T3-AC-5: the second run's section must be APPENDED, not overwrite the first"
        )
        assert content_after_second.startswith(content_after_first) or content_after_first in (
            content_after_second
        ), "T3-AC-5: the first run's content must survive verbatim inside the appended file"
