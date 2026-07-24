"""tests for SPRINT-TICKET-001 P4 — `hud._build`:
  - `HudState` gains a new frozen `attrition` field, same per-symbol shape
    as the scanner's `P3` attrition entries PLUS two extra stage names
    (`"sizing"`, `"policy_verdict"`) appended by hud's own downstream gates.
  - New pure helper `hud._build.render_attrition_log(state) -> str` in
    Mike's format (TICKET-001 §4.2): a header (ts + equity + universe), a
    per-symbol stage-line section, and a SUMMARY line naming the killer
    filter with counts.

Per ASSUMPTIONS 163 (`observed` / whole-log format is human prose, not a
parsing surface), assertions below match SUBSTRINGS of the rendered log,
never the whole template.

ASSUMPTIONS-FLAG: the pin does not specify whether `HudState.attrition`
entries are plain dicts (matching `_scanner.scan`'s `"attrition"` shape
verbatim) or a new frozen pydantic model. This test constructs entries as
plain dicts (the same shape `_scanner.scan` already produces) since P4 says
hud "composes scanner attrition + its own downstream gates ... into
HudState.attrition" — composition of an existing dict shape reads as the
more natural reading absent a dedicated model type in the pins. Flagging
for CTO adjudication in tests/ASSUMPTIONS.md; do not treat this dict-shape
choice as load-bearing on the implementer if a model type is pinned instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _attrition_entry(symbol: str, killed_by: str | None, stages: list[dict]) -> dict:
    return {"symbol": symbol, "timeframe": "1h", "stages": stages, "killed_by": killed_by}


_SAMPLE_ATTRITION = (
    _attrition_entry(
        "NEAR/USD",
        "macd_signal",
        [
            {"name": "bars", "outcome": "pass", "observed": "179 bars"},
            {"name": "macd_signal", "outcome": "fail", "observed": "hist=-0.0035"},
        ],
    ),
    _attrition_entry(
        "LINK/USD",
        None,
        [
            {"name": "bars", "outcome": "pass", "observed": "179 bars"},
            {"name": "setup", "outcome": "pass", "observed": "signal_tags=['macd_bullish']"},
            {"name": "sizing", "outcome": "pass", "observed": "qty=12"},
            {"name": "policy_verdict", "outcome": "pass", "observed": "allow"},
        ],
    ),
)


class TestHudStateAttritionField:
    def test_hud_state_accepts_and_carries_an_attrition_field(self) -> None:
        """CONTRACT: `HudState` gains a new frozen `attrition` field (P4) —
        constructing it with an `attrition=` kwarg must round-trip that
        value on the instance (today, pydantic silently ignores unknown
        kwargs for a plain `FrozenModel`, so `state.attrition` raises
        `AttributeError`)."""
        from tradekit.contracts import HudState

        state = HudState(
            generated_at=datetime(2026, 7, 24, tzinfo=UTC),
            tickets=(),
            report=(),
            attrition=_SAMPLE_ATTRITION,
        )

        assert state.attrition == _SAMPLE_ATTRITION


class TestRenderAttritionLog:
    def _make_state(self):
        from tradekit.contracts import HudState

        return HudState(
            generated_at=datetime(2026, 7, 24, 11, 53, 42, tzinfo=UTC),
            tickets=(),
            report=(),
            attrition=_SAMPLE_ATTRITION,
        )

    def test_render_attrition_log_is_a_pure_function_returning_a_string(self) -> None:
        """BEHAVIOR: `hud._build.render_attrition_log(state) -> str` — pure,
        no I/O; calling it twice with the same state yields identical
        output (byte-for-byte), which is what "pure function" means for a
        log-writer that must be safe to call repeatedly (e.g. before a
        file write and again for a ledger note)."""
        from tradekit.hud import _build

        state = self._make_state()
        first = _build.render_attrition_log(state, equity_usd=Decimal("5000"))
        second = _build.render_attrition_log(state, equity_usd=Decimal("5000"))

        assert isinstance(first, str)
        assert first == second

    def test_summary_line_contains_killer_filter_label(self) -> None:
        """BEHAVIOR (TICKET-001 §4.2 SUMMARY payoff line): the rendered log
        contains a line naming the killer filter, format
        `"killer filter: X (n/m)"` per Mike's sketch — substring match only,
        never the whole template (ASSUMPTIONS 163). A-FIX-1: the killer
        filter named here is the real per-filter stage (macd_signal), not
        the collapsed "setup" gate."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state(), equity_usd=Decimal("5000"))

        assert "killer filter:" in rendered
        assert "killer filter: macd_signal" in rendered

    def test_summary_line_contains_per_stage_kill_counts(self) -> None:
        """BEHAVIOR: the SUMMARY carries a kill count per stage name that
        appears anywhere in the attrition data — here "macd_signal" killed
        NEAR/USD (1 kill), NOT the collapsed "setup" name (A-FIX-1) —
        asserted as a substring, not the whole summary line, since the
        exact template may evolve (ASSUMPTIONS 163)."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state(), equity_usd=Decimal("5000"))

        assert "macd_signal" in rendered
        # the killed symbol and the surviving symbol both must be named
        # somewhere in the per-symbol section
        assert "NEAR/USD" in rendered
        assert "LINK/USD" in rendered

    def test_header_contains_timestamp_and_equity_and_universe_size(self) -> None:
        """BEHAVIOR (TICKET-001 §4.2 header line): the rendered log's header
        carries the scan timestamp, equity, and universe size — substring
        match on each independently, format may evolve. A-FIX-2: equity is
        an explicit `equity_usd` parameter (HudState carries no equity
        field) and must actually appear in the header, not merely be
        accepted and dropped."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state(), equity_usd=Decimal("5000"))

        assert "2026" in rendered  # scan_ts / generated_at is somewhere in the header
        assert "2" in rendered  # universe=2 pairs (NEAR/USD + LINK/USD)
        assert "5000" in rendered  # equity_usd must actually render, not just be accepted


class TestAFix1AttritionStagesSplice:
    """A-FIX-1 (HIGH, review 2026-07-24): the scanner's real per-filter
    attrition stages must survive into HudState.attrition and the rendered
    log — the collapsed hud "setup" gate name must never be the reported
    killer when the scanner's own stages are available."""

    def test_build_state_splices_scanner_stages_naming_macd_signal_not_setup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEAM: `scan_setup` returns a `_SetupResult` whose
        `attrition_stages` show the scanner killed the candidate at
        `macd_signal` (not `bars`, not the collapsed "setup"). `build_state`
        must splice those stages into `HudState.attrition` in place of the
        collapsed setup gate, and the rendered log must name macd_signal —
        this is the exact defect that produced the S1 outage-shaped bug
        (TICKET-001): a real per-filter killer collapsing into an
        uninformative "setup" gate."""
        from dataclasses import dataclass, field
        from datetime import timedelta

        import tradekit.hud._build as hud_build
        import tradekit.mae._runtime as mae_runtime
        from tradekit.contracts import AssetRef, Bar, BarSeries

        captured_at = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(mae_runtime, "clock", lambda: captured_at)

        bars = [
            Bar(
                ts_open=captured_at - timedelta(hours=24 - i),
                open=Decimal("8.30000"),
                high=Decimal("8.40000"),
                low=Decimal("8.20000"),
                close=Decimal("8.30000"),
                volume=Decimal("1000"),
            )
            for i in range(24)
        ]
        series = BarSeries(
            asset=AssetRef(
                symbol="NEAR/USD",
                venue="kraken",
                asset_class="crypto",
                tick_size=Decimal("0.00001"),
            ),
            timeframe="1h",
            bars=bars,
            source="test-fixture",
        )
        monkeypatch.setattr(mae_runtime, "get_closed_bars", lambda *a, **k: series)

        @dataclass(frozen=True)
        class _KilledAtMacdSetup:
            signal_tags: list[str] = field(default_factory=list)
            attrition_stages: list[dict] = field(
                default_factory=lambda: [
                    {"name": "bars", "outcome": "pass", "observed": "540 bars"},
                    {"name": "macd_signal", "outcome": "fail", "observed": "hist=-0.0035"},
                ]
            )

        monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _KilledAtMacdSetup())
        monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())

        state = hud_build.build_state(
            ["NEAR/USD"], captured_at=captured_at, equity_usd=Decimal("5000")
        )

        entry = state.attrition[0]
        assert entry["killed_by"] == "macd_signal"
        assert "setup" not in {stage["name"] for stage in entry["stages"]}
        assert {"name": "macd_signal", "outcome": "fail", "observed": "hist=-0.0035"} in (
            entry["stages"]
        )

        rendered = hud_build.render_attrition_log(state, equity_usd=Decimal("5000"))
        assert "macd_signal" in rendered
        assert "killer filter: macd_signal" in rendered
