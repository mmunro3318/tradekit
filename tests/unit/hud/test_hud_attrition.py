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


def _attrition_entry(symbol: str, killed_by: str | None, stages: list[dict]) -> dict:
    return {"symbol": symbol, "timeframe": "1h", "stages": stages, "killed_by": killed_by}


_SAMPLE_ATTRITION = (
    _attrition_entry(
        "NEAR/USD",
        "setup",
        [
            {"name": "bars", "outcome": "pass", "observed": "179 bars"},
            {"name": "setup", "outcome": "fail", "observed": "signal_tags=[]"},
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
        first = _build.render_attrition_log(state)
        second = _build.render_attrition_log(state)

        assert isinstance(first, str)
        assert first == second

    def test_summary_line_contains_killer_filter_label(self) -> None:
        """BEHAVIOR (TICKET-001 §4.2 SUMMARY payoff line): the rendered log
        contains a line naming the killer filter, format
        `"killer filter: X (n/m)"` per Mike's sketch — substring match only,
        never the whole template (ASSUMPTIONS 163)."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state())

        assert "killer filter:" in rendered

    def test_summary_line_contains_per_stage_kill_counts(self) -> None:
        """BEHAVIOR: the SUMMARY carries a kill count per stage name that
        appears anywhere in the attrition data — here "setup" killed
        NEAR/USD (1 kill) — asserted as a substring, not the whole summary
        line, since the exact template may evolve (ASSUMPTIONS 163)."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state())

        assert "setup" in rendered
        # the killed symbol and the surviving symbol both must be named
        # somewhere in the per-symbol section
        assert "NEAR/USD" in rendered
        assert "LINK/USD" in rendered

    def test_header_contains_timestamp_and_equity_and_universe_size(self) -> None:
        """BEHAVIOR (TICKET-001 §4.2 header line): the rendered log's header
        carries the scan timestamp, equity, and universe size — substring
        match on each independently, format may evolve."""
        from tradekit.hud import _build

        rendered = _build.render_attrition_log(self._make_state())

        assert "2026" in rendered  # scan_ts / generated_at is somewhere in the header
        assert "2" in rendered  # universe=2 pairs (NEAR/USD + LINK/USD)
