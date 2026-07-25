"""tests for SCAN-AUDIT-LOG (docs/design/SCAN-AUDIT-LOG.md) — `_scanner.scan()`
gains a keyword-only `audit: ScanAuditMode = "off"` param and (when not
"off") writes a full-lifecycle trace to `data/scans/<UTC-date>/`.

Behavior pins under test (design doc "Behavior pins", B1-B5):
    B1 audit="off"  -> byte-identical return value, zero audit files.
    B2 audit="on"   -> return value == "off"; audit log + sidecar CSV
                       written with pinned sections; GATE-line numbers
                       cross-check the returned attrition/matches.
    B3 audit="exhaustive" -> matches/killed_by/warnings == "on"; every
                       PRESENT filter gets a verdict line for every
                       candidate that passed the `bars` gate; post-kill
                       verdicts carry the exhaustive-only marker.
    B4 audit="bogus" -> loud ValueError naming the bad value.
    B5 (fixture discipline: fixed clock, fake bars, no network) is a
       property of the test setup below, not a separate test.

ASSUMPTIONS-FLAG 1 (output-root seam): the design doc pins the on-disk
layout (`data/scans/<UTC-date>/audit-<HHMMSS>.log` + sidecar dir) but names
no monkeypatchable constant, and no existing scan/attrition log writer
exists anywhere in `src/` to mirror (grepped "data/scans", "audit-",
".log" writers repo-wide — none found; the attrition telemetry added by
SPRINT-TICKET-001 lives only in the returned dict, never touches disk).
This batch therefore ALSO pins the seam itself: a private module-level
`_OUTPUT_ROOT: Path` constant on the new `tradekit.mae._scan_trace` module,
monkeypatched the same way `_runtime._cache_path` is monkeypatched directly
in tests/unit/mae/test_runtime.py:91 (module-level Path constant, not an
env var or CLI flag). Import of `_scan_trace` is deferred to INSIDE each
test body (not top-of-file) precisely so a not-yet-existing module fails
as an individual test failure, not a whole-file collection error, per the
tk-tdd red-verification rule.

ASSUMPTIONS-FLAG 2 (symbol/sidecar filename collision): design pins the
sidecar filename as `<SYMBOL>-<tf>.csv`, but real symbols in this repo
contain "/" (e.g. "NEAR/USD" — see test_scan_attrition.py), which is a
path separator; naive interpolation would silently create a nested
directory instead of a flat file. The design doc does not address
sanitization. This batch's fixtures sidestep the question by using
slash-free symbol names (numeric fixtures are unaffected — MACD histogram
and volume_ratio depend only on the close/volume series, not the symbol
string) so the tests below make no claim about slash-sanitization; the
implementer must resolve ASSUMPTIONS-FLAG 2 independently (ratify in
tests/ASSUMPTIONS.md) before a real crypto symbol reaches audit="on".

Fixture provenance: MACD histogram values below are the SAME independently
derived vectors already cited in tests/unit/mae/test_scan_attrition.py's
module docstring (derived directly against `_indicators.momentum.macd`,
not from `scan()`):
    bullish closes [100.0]*40 + [100.0 + i**1.3 for i in 1..20]
        -> macd(closes).histogram[-1] == 2.632866287861548   (> 0)
    bearish closes [100.0]*40 + [100.0 - i**1.3 for i in 1..20]
        -> macd(closes).histogram[-1] == -2.6328662878615496  (< 0)
Volume-ratio golden value reused from the same file: 19 bars of volume=100.0
+ 1 spike bar of volume=1000.0 -> volume_ratio(20)[-1] ==
1000.0/145.0 == 6.896551724137931, which clears `volume_spike: 1.5`.
The killer symbol's volumes are flat 100.0 throughout (ratio ~= 1.0),
which FAILS the same `volume_spike: 1.5` filter — the later gate that
would ALSO have failed, which is what makes the exhaustive-mode pins (B3)
meaningful for this fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from tradekit.contracts import AssetRef, Bar, BarSeries
from tradekit.mae import _scanner

_MACD_BULLISH_CLOSES = [100.0] * 40 + [100.0 + i**1.3 for i in range(1, 21)]
_MACD_BEARISH_CLOSES = [100.0] * 40 + [100.0 - i**1.3 for i in range(1, 21)]
_BEARISH_HIST_GOLDEN = "-2.6328662878615496"  # independently derived, see docstring above

_FILTERS = {"macd_signal": "bullish_cross", "volume_spike": 1.5}
_TIMEFRAME = "1d"
_KILLER_SYMBOL = "MACDBEAR"  # engineered: fails macd_signal (early), would also fail volume_spike
_SURVIVOR_SYMBOL = "MACDBULL"  # engineered: passes every present filter
_FIXED_CLOCK = datetime(2026, 7, 24, 15, 30, 45, tzinfo=UTC)
_EXPECTED_DATE_DIR = "2026-07-24"
_EXPECTED_LOG_STEM = "audit-153045"

_GATE_NAME_UNIVERSE = {
    "bars",
    "rsi",
    "macd_signal",
    "bb_position",
    "volume_spike",
    "atr_percentile",
    "regime_gate",
}


def _series(symbol: str, closes: list[float], volumes: list[float]) -> BarSeries:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [
        Bar(
            ts_open=start + timedelta(days=i),
            open=Decimal(str(c)),
            high=Decimal(str(c + 0.3)),
            low=Decimal(str(c - 0.3)),
            close=Decimal(str(c)),
            volume=Decimal(str(v)),
        )
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
    ]
    asset = AssetRef(symbol=symbol, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))
    return BarSeries(asset=asset, timeframe=_TIMEFRAME, bars=bars, source="fake-kraken")


def _universe() -> dict[str, BarSeries]:
    killer = _series(_KILLER_SYMBOL, _MACD_BEARISH_CLOSES, [100.0] * len(_MACD_BEARISH_CLOSES))
    survivor = _series(
        _SURVIVOR_SYMBOL,
        _MACD_BULLISH_CLOSES,
        [100.0] * (len(_MACD_BULLISH_CLOSES) - 1) + [1000.0],
    )
    return {_KILLER_SYMBOL: killer, _SURVIVOR_SYMBOL: survivor}


def _install_bars_and_clock(monkeypatch) -> None:
    series_by_symbol = _universe()

    def _fake(symbol: str, timeframe: str, lookback_days: int) -> BarSeries:
        return series_by_symbol[symbol]

    monkeypatch.setattr("tradekit.mae._runtime.get_closed_bars", _fake)
    monkeypatch.setattr("tradekit.mae._runtime._clock", lambda: _FIXED_CLOCK)


def _install_audit_root(monkeypatch, tmp_path: Path) -> Path:
    """ASSUMPTIONS-FLAG 1 seam (see module docstring). Local import so a
    not-yet-existing `_scan_trace` module fails THIS test, not collection."""
    from tradekit.mae import _scan_trace

    monkeypatch.setattr(_scan_trace, "_OUTPUT_ROOT", tmp_path)
    return tmp_path


def _scan(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        asset_class="crypto",
        timeframes=[_TIMEFRAME],
        filters=_FILTERS,
        symbols=[_KILLER_SYMBOL, _SURVIVOR_SYMBOL],
        regime_gate=False,
    )
    kwargs.update(overrides)
    return _scanner.scan(**kwargs)  # type: ignore[arg-type]


class TestB1AuditOff:
    def test_off_mode_return_value_matches_no_audit_param_baseline(self, monkeypatch, tmp_path):
        """CONTRACT: `audit="off"` must be byte-identical to calling `scan()`
        without the new param at all (design B1: "today's behavior,
        byte-identical")."""
        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        baseline = _scan()
        off_result = _scan(audit="off")

        assert off_result == baseline

    def test_off_mode_writes_no_audit_files(self, monkeypatch, tmp_path):
        """CONTRACT: `audit="off"` must never touch disk under the audit
        output root — no log, no sidecar directory, nothing (design B1)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="off")

        written = list(root.rglob("*"))
        assert written == [], f"audit='off' must write zero files, found: {written}"


class TestB2AuditOn:
    def test_on_mode_return_value_equals_off_mode(self, monkeypatch, tmp_path):
        """BEHAVIOR: `audit="on"` must not change scan semantics — same
        matches/attrition/warnings/scan_ts as the off-mode baseline
        (design B2: "return value equal to 'off' on identical inputs")."""
        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        baseline = _scan()
        on_result = _scan(audit="on")

        assert on_result == baseline

    def test_on_mode_writes_log_and_sidecar_at_pinned_paths(self, monkeypatch, tmp_path):
        """CONTRACT: `audit="on"` writes
        data/scans/<UTC-date>/audit-<HHMMSS>.log and one sidecar CSV per
        symbol/timeframe under data/scans/<UTC-date>/audit-<HHMMSS>/
        (design "Output artifacts"; clock is the monkeypatched fixed
        clock, never wall time — B5)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="on")

        log_path = root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log"
        sidecar_dir = root / _EXPECTED_DATE_DIR / _EXPECTED_LOG_STEM
        assert log_path.is_file(), f"expected audit log at {log_path}"
        assert (sidecar_dir / f"{_KILLER_SYMBOL}-{_TIMEFRAME}.csv").is_file()
        assert (sidecar_dir / f"{_SURVIVOR_SYMBOL}-{_TIMEFRAME}.csv").is_file()

    def test_on_mode_log_header_names_mode_universe_timeframes_filters_regime_gate(
        self, monkeypatch, tmp_path
    ):
        """CONTRACT: header section carries scan_ts, audit mode, universe
        (approved symbol list as passed), timeframes, active filters,
        regime_gate flag (design "Log structure" §1)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="on")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        assert "on" in log_text.splitlines()[0].lower() or "mode" in log_text.lower()
        assert _KILLER_SYMBOL in log_text
        assert _SURVIVOR_SYMBOL in log_text
        assert _TIMEFRAME in log_text
        assert "macd_signal" in log_text
        assert "volume_spike" in log_text
        assert "regime_gate" in log_text.lower()

    def test_on_mode_sidecar_csv_row_count_equals_bars_fed(self, monkeypatch, tmp_path):
        """CONTRACT: "Full dataset always lands in the sidecar CSV so every
        calculation is replicable" — row count (excluding header) must equal
        the number of bars fetched for that symbol/timeframe, 60 for this
        fixture (design "Per symbol x timeframe section")."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="on")

        sidecar = (
            root / _EXPECTED_DATE_DIR / _EXPECTED_LOG_STEM / f"{_KILLER_SYMBOL}-{_TIMEFRAME}.csv"
        )
        rows = sidecar.read_text().strip().splitlines()
        data_rows = rows[1:]  # header row excluded
        assert len(data_rows) == len(_MACD_BEARISH_CLOSES) == 60

    def test_on_mode_log_shows_first_and_last_bars_with_sidecar_reference(
        self, monkeypatch, tmp_path
    ):
        """CONTRACT: bar fetch section inlines first 5 / last 5 bars and
        references the sidecar CSV for the rest (design: "... N more rows:
        see <sidecar CSV>")."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="on")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        series = _universe()[_KILLER_SYMBOL]
        first_bars = series.bars[:5]
        last_bars = series.bars[-5:]
        for bar in first_bars + last_bars:
            assert bar.ts_open.isoformat()[:10] in log_text, (
                f"expected bar {bar.ts_open.isoformat()} inlined in the log"
            )
        assert f"{_KILLER_SYMBOL}-{_TIMEFRAME}.csv" in log_text, (
            "sidecar CSV filename must be referenced from the log's bar-fetch section"
        )

    def test_on_mode_gate_line_numbers_match_returned_attrition_observed(
        self, monkeypatch, tmp_path
    ):
        """GOLDEN + CONTRACT: the killer's GATE macd_signal line must carry
        the independently-derived histogram value (-2.6328662878615496,
        derived directly against `_indicators.momentum.macd`, cited in this
        file's module docstring — NOT read back from `scan()`'s own output)
        and, separately, cross-check that it also equals the SUT's own
        returned attrition observed string (design B2: "every number in a
        GATE line equals the corresponding value in the returned
        attrition/matches structures")."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        result = _scan(audit="on")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        assert _BEARISH_HIST_GOLDEN[:6] in log_text or "-2.63" in log_text, (
            "GATE macd_signal line for the killer must carry the independently "
            "derived bearish histogram value"
        )

        attrition_by_symbol = {entry["symbol"]: entry for entry in result["attrition"]}
        killer_macd_stage = next(
            s
            for s in attrition_by_symbol[_KILLER_SYMBOL]["stages"]
            if s["name"] == "macd_signal"
        )
        assert killer_macd_stage["observed"] in log_text, (
            "GATE line must carry the exact 'observed' string scan() itself "
            "attached to the attrition stage — no recomputation, no drift "
            "(design: 'a logged number can never drift from the number the "
            "gate actually compared')"
        )

    def test_on_mode_gate_names_come_from_fixed_expected_set(self, monkeypatch, tmp_path):
        """SEAM: every `GATE <name>` line in the log names a gate from the
        fixed, closed vocabulary the design pins for `GATE_SPECS`
        (bars/rsi/macd_signal/bb_position/volume_spike/atr_percentile/
        regime_gate) — asserted through the log's OUTPUT, never by
        importing `_scan_trace.GATE_SPECS` internals directly (dispatch
        constraint: test through outputs, not registry internals)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="on")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        gate_names_seen = {
            line.split()[1]
            for line in log_text.splitlines()
            if line.strip().startswith("GATE ")
        }
        assert gate_names_seen, "expected at least one GATE line in the audit log"
        assert gate_names_seen <= _GATE_NAME_UNIVERSE, (
            f"unexpected gate name(s) not in the fixed registry vocabulary: "
            f"{gate_names_seen - _GATE_NAME_UNIVERSE}"
        )


class TestB3AuditExhaustive:
    def test_exhaustive_mode_matches_killed_by_warnings_identical_to_on(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR: "Kill semantics unchanged" — `matches`, `killed_by`,
        `warnings` are identical between "on" and "exhaustive" (design B3)."""
        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        on_result = _scan(audit="on")
        exhaustive_result = _scan(audit="exhaustive")

        assert exhaustive_result["matches"] == on_result["matches"]
        assert exhaustive_result["warnings"] == on_result["warnings"]
        on_killed_by = {e["symbol"]: e["killed_by"] for e in on_result["attrition"]}
        exhaustive_killed_by = {
            e["symbol"]: e["killed_by"] for e in exhaustive_result["attrition"]
        }
        assert exhaustive_killed_by == on_killed_by

    def test_exhaustive_mode_killed_symbol_has_verdict_for_every_present_filter(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR: the early-killed symbol (dies at macd_signal, the
        FIRST present filter) must still get a verdict line for
        volume_spike too — every present filter evaluated for every
        candidate that passed `bars` (design B3)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="exhaustive")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        killer_section = log_text.split(_KILLER_SYMBOL, 1)[1]
        next_symbol_idx = killer_section.find(_SURVIVOR_SYMBOL)
        if next_symbol_idx != -1:
            killer_section = killer_section[:next_symbol_idx]
        assert "GATE macd_signal" in killer_section, "the real killing gate must have a verdict"
        assert "GATE volume_spike" in killer_section, (
            "exhaustive mode must ALSO evaluate volume_spike for the killer, "
            "since it is a present filter and the killer passed the bars gate"
        )

    def test_exhaustive_mode_post_kill_verdict_carries_exhaustive_only_marker(
        self, monkeypatch, tmp_path
    ):
        """BEHAVIOR: the killer's post-kill gate (volume_spike, evaluated
        AFTER macd_signal already killed it) must carry the literal marker
        "(exhaustive-only — would not have run)" (design B3 verdict
        vocabulary)."""
        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        _scan(audit="exhaustive")

        log_text = (root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log").read_text()
        killer_section = log_text.split(_KILLER_SYMBOL, 1)[1]
        next_symbol_idx = killer_section.find(_SURVIVOR_SYMBOL)
        if next_symbol_idx != -1:
            killer_section = killer_section[:next_symbol_idx]
        volume_spike_block = killer_section.split("GATE volume_spike", 1)[1]
        gate_block_end = volume_spike_block.find("GATE ")
        if gate_block_end != -1:
            volume_spike_block = volume_spike_block[:gate_block_end]
        assert "(exhaustive-only" in volume_spike_block and "would not have run" in (
            volume_spike_block
        ), (
            "post-kill gate verdict must carry the exhaustive-only marker "
            f"verbatim; got block: {volume_spike_block!r}"
        )


class TestB4AuditBogusValue:
    def test_bogus_audit_value_raises_value_error_naming_the_value(self, monkeypatch, tmp_path):
        """CONTRACT: unknown `audit` value is a closed-vocabulary violation
        — loud ValueError naming the bad value (design B4, TICKET-001
        convention), never a silent fallback to "off" and never a
        KeyError/AttributeError leaking an implementation detail."""
        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        with pytest.raises(ValueError, match="bogus"):
            _scan(audit="bogus")
