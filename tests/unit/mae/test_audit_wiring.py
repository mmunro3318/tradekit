"""tests for T-AUDIT-2 (audit wiring): SCAN-AUDIT-LOG's `audit` param wired
to the public `scan_markets` verb (W1) and the `tk hud` CLI (W2 flag + W3
console tee + W4 rejection of unknown values). See
docs/design/SCAN-AUDIT-LOG.md ("HUD wiring (only flag passthrough): tk hud
--audit [on|exhaustive]"; "Console echo: when invoked through hud with
--audit, the same lines tee to stdout").

Fixture provenance (REUSED, not re-derived): the bearish-MACD-closes /
flat-volume "killer" fixture below is the SAME shape as
tests/unit/mae/test_scan_audit.py's `_KILLER_SYMBOL` fixture (that file's
docstring cites the independent derivation: 40 flat closes @ 100.0 + 20
closes falling by `i**1.3`, MACD histogram goes negative -> fails
`macd_signal: "bullish_cross"` before ever reaching `volume_spike` or
`regime_gate`). Reused here purely so a real (unfaked) `mae.scan_markets` /
`_default_scan_setup` call runs to completion deterministically without
needing to fake `_regime.compute_regime` at all (a killed candidate never
reaches the regime-gate branch — `_scanner.scan` line ~531:
`if match is not None and regime_gate:`). No new golden value is asserted
here; only file-existence / substring observables are checked (W1-W4 pins
are about wiring, not scan math).

Determinism seams (sanctioned, same as test_scan_audit.py / test_hud_cli.py
precedent): `tradekit.mae._runtime.clock` / `.get_closed_bars`,
`tradekit.mae._scan_trace._OUTPUT_ROOT`, and the hud `_build.py` module-level
seam `open_position_symbols` (module attribute reassignment). `scan_setup`
is deliberately left REAL (not monkeypatched) in the W2/W3 tests below so
the actual `mae.scan_markets` call fires and the actual `_scan_trace` audit
file gets written — that is the exact "scan running with that audit mode"
observable W2 pins. `evaluate_policy` / `sizing_info` are never reached for
the killer-symbol fixture (empty `signal_tags` short-circuits `build_state`
before either is called), so they are left unfaked too.

ASSUMPTIONS-FLAG (this batch, logged per protocol — see
tests/ASSUMPTIONS.md): no existing console-tee/stdout-boundary helper
exists anywhere in src/ to pin against (grepped "tee", "stdout.buffer",
"errors=.replace." across src/tradekit/cli and src/tradekit/hud — none
found). W3's cp1252-crash-proof unit tests below therefore PIN a new
private seam, `tradekit.cli.main._tee_audit_log(text: str) -> None`, as the
natural home (same module already owning the CLI-boundary code —
typer.echo, webbrowser.open, atomic file write). This is an invented name,
not a rediscovered one; the CLI-observable tests in
`TestW3ConsoleTeeCliObservable` are the authority the implementer must
satisfy — `_tee_audit_log` may be renamed/relocated during green iff those
observable tests still pass unmodified.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()

_TIMEFRAME = "1d"
_FILTERS = {"macd_signal": "bullish_cross", "volume_spike": 1.5}
_KILLER_SYMBOL = "AUDITKILL"  # slash-free (ASSUMPTIONS-FLAG 2 precedent, test_scan_audit.py)
_MACD_BEARISH_CLOSES = [100.0] * 40 + [100.0 - i**1.3 for i in range(1, 21)]
_FIXED_CLOCK = datetime(2026, 7, 25, 9, 15, 30, tzinfo=UTC)
_EXPECTED_DATE_DIR = "2026-07-25"
_EXPECTED_LOG_STEM = "audit-091530"
EQUITY = "5000"


def _killer_series():
    from tradekit.contracts import AssetRef, Bar, BarSeries

    volumes = [100.0] * len(_MACD_BEARISH_CLOSES)
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
        for i, (c, v) in enumerate(zip(_MACD_BEARISH_CLOSES, volumes, strict=True))
    ]
    asset = AssetRef(
        symbol=_KILLER_SYMBOL, venue="kraken", asset_class="crypto", tick_size=Decimal("0.01")
    )
    return BarSeries(asset=asset, timeframe=_TIMEFRAME, bars=bars, source="fake-kraken")


def _install_bars_and_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: same as test_scan_audit.py's `_install_bars_and_clock`, but
    patches the public `clock()` wrapper (test_hud_cli.py's convention)
    since both `_scanner.scan` and `hud._build.build_state` read the clock
    through that same wrapper (see src/tradekit/mae/_scanner.py:515,
    `ts = _runtime.clock()`)."""
    series = _killer_series()

    monkeypatch.setattr(
        "tradekit.mae._runtime.get_closed_bars",
        lambda symbol, timeframe, lookback_days: series,
    )
    monkeypatch.setattr("tradekit.mae._runtime.clock", lambda: _FIXED_CLOCK)


def _install_audit_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """ASSUMPTIONS-FLAG 1 seam precedent (test_scan_audit.py). Local import
    so a missing/changed `_scan_trace` module fails the individual test."""
    from tradekit.mae import _scan_trace

    monkeypatch.setattr(_scan_trace, "_OUTPUT_ROOT", tmp_path)
    return tmp_path


def _install_no_open_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    import tradekit.hud._build as hud_build

    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


def _expected_log_path(root: Path) -> Path:
    return root / _EXPECTED_DATE_DIR / f"{_EXPECTED_LOG_STEM}.log"


class TestW1ScanMarketsAuditPassthrough:
    """W1: `mae.scan_markets` gains keyword-only `audit: ScanAuditMode =
    "off"` and passes it through to `_scanner.scan` untouched; default path
    stays behavior-identical."""

    def test_no_audit_kwarg_is_byte_identical_to_explicit_audit_off(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: calling `scan_markets` with no `audit` kwarg at all
        must return the exact same dict as passing `audit="off"` explicitly
        (W1: "Default path behavior-identical to today")."""
        from tradekit import mae

        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        baseline = mae.scan_markets(
            "crypto", [_TIMEFRAME], _FILTERS, symbols=[_KILLER_SYMBOL], regime_gate=False
        )
        explicit_off = mae.scan_markets(
            "crypto",
            [_TIMEFRAME],
            _FILTERS,
            symbols=[_KILLER_SYMBOL],
            regime_gate=False,
            audit="off",
        )

        assert explicit_off == baseline

    def test_audit_on_writes_the_same_trace_file_scanner_scan_writes_directly(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: `scan_markets(..., audit="on")` passes `audit`
        THROUGH UNTOUCHED to `_scanner.scan` (W1) — observable as the exact
        same audit trace file `_scanner.scan(audit="on")` itself writes at
        its pinned path (design doc "Output artifacts";
        test_scan_audit.py's B2 path-pin precedent), reached via the public
        verb instead of the private one."""
        from tradekit import mae

        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        mae.scan_markets(
            "crypto",
            [_TIMEFRAME],
            _FILTERS,
            symbols=[_KILLER_SYMBOL],
            regime_gate=False,
            audit="on",
        )

        assert _expected_log_path(root).is_file()

    def test_audit_off_writes_zero_audit_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: `scan_markets(..., audit="off")` must never touch disk
        under the audit output root (W1 default-path pin, mirrors design
        B1 at the public-verb layer)."""
        from tradekit import mae

        _install_bars_and_clock(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        mae.scan_markets(
            "crypto",
            [_TIMEFRAME],
            _FILTERS,
            symbols=[_KILLER_SYMBOL],
            regime_gate=False,
            audit="off",
        )

        assert list(root.rglob("*")) == []

    def test_unknown_audit_value_raises_value_error_naming_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: an unknown `audit` value passed through the public verb
        raises `ValueError` naming the bad value — passthrough of
        `_scanner.scan`'s own validation (design doc B4 / TICKET-001
        convention), never swallowed or reinterpreted at the `scan_markets`
        layer."""
        from tradekit import mae

        _install_bars_and_clock(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path)

        with pytest.raises(ValueError, match="bogus"):
            mae.scan_markets(
                "crypto",
                [_TIMEFRAME],
                _FILTERS,
                symbols=[_KILLER_SYMBOL],
                regime_gate=False,
                audit="bogus",
            )


class TestW2HudBuildStateAuditThreading:
    """W2 core pin (function level, ahead of the CLI shell): `hud.build_state`
    must accept keyword-only `audit` and, when != "off", drive a REAL scan
    that writes an audit trace file — the observable "scan running with
    that audit mode" the CLI wiring depends on."""

    def test_build_state_audit_on_writes_a_real_audit_trace_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BEHAVIOR: `hud.build_state([...], captured_at=..., equity_usd=...,
        audit="on")` — with `scan_setup` left REAL (not the CLI-test-suite's
        usual fake) — results in an audit trace file under
        `_scan_trace._OUTPUT_ROOT`, because the real `_default_scan_setup`
        calls `mae.scan_markets(..., audit=...)` per symbol (W2)."""
        from tradekit import hud

        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        hud.build_state(
            [_KILLER_SYMBOL], captured_at=_FIXED_CLOCK, equity_usd=Decimal(EQUITY), audit="on"
        )

        assert _expected_log_path(root).is_file()

    def test_build_state_default_audit_is_off_and_writes_no_audit_files(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: `hud.build_state` called with no `audit` kwarg (today's
        call shape, unchanged) must write zero audit files — the hud-layer
        default path stays behavior-identical (mirrors W1's default-path
        pin one layer up)."""
        from tradekit import hud

        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path)

        hud.build_state([_KILLER_SYMBOL], captured_at=_FIXED_CLOCK, equity_usd=Decimal(EQUITY))

        assert list(root.rglob("*")) == []


class TestW2HudCliAuditFlag:
    """W2 CLI shell: `tk hud` gains `--audit` with choices on|exhaustive,
    absent = off."""

    def test_audit_on_flag_results_in_an_audit_log_file_under_output_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BEHAVIOR: `tk hud --symbols AUDITKILL --equity 5000 --audit on`
        results in the scan running with audit mode "on" — observable as an
        audit log file created under the (monkeypatched) output root
        (design doc: "HUD wiring (only flag passthrough): tk hud --audit
        [on|exhaustive]")."""
        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path / "audit_root")
        out = tmp_path / "out" / "hud.html"

        result = runner.invoke(
            app,
            [
                "hud",
                "--symbols",
                _KILLER_SYMBOL,
                "--equity",
                EQUITY,
                "--out",
                str(out),
                "--audit",
                "on",
            ],
        )

        assert result.exit_code == 0, result.output
        assert _expected_log_path(root).is_file()

    def test_absent_audit_flag_means_off_and_writes_no_audit_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: `tk hud` invoked without `--audit` at all (today's
        invocation shape, e.g. every pre-existing test in
        tests/unit/hud/test_hud_cli.py) writes zero audit files — "absent =
        off" (W2 pin)."""
        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        root = _install_audit_root(monkeypatch, tmp_path / "audit_root")
        out = tmp_path / "out" / "hud.html"

        result = runner.invoke(
            app,
            ["hud", "--symbols", _KILLER_SYMBOL, "--equity", EQUITY, "--out", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert list(root.rglob("*")) == []


class TestW3ConsoleTeeCliObservable:
    """W3 (CLI-observable half): when audit mode != off via the hud path,
    the rendered audit-log content is ALSO written to stdout (design doc
    "Console echo ... the same lines tee to stdout")."""

    def test_audit_on_stdout_contains_the_audit_header_and_a_gate_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """BEHAVIOR: `tk hud --audit on`'s captured stdout contains the
        audit trace's header marker `"SCAN AUDIT LOG"` (see
        src/tradekit/mae/_scan_trace.py:208) and at least one `"GATE "`
        verdict line (:291) — the tee is real content, not a placeholder
        notice."""
        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path / "audit_root")
        out = tmp_path / "out" / "hud.html"

        result = runner.invoke(
            app,
            [
                "hud",
                "--symbols",
                _KILLER_SYMBOL,
                "--equity",
                EQUITY,
                "--out",
                str(out),
                "--audit",
                "on",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "SCAN AUDIT LOG" in result.stdout
        assert "GATE " in result.stdout

    def test_audit_off_never_tees_audit_content_to_stdout(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: without `--audit`, stdout never contains the audit
        trace header — the tee is gated on audit mode, not unconditional
        chatter added by this batch."""
        _install_bars_and_clock(monkeypatch)
        _install_no_open_positions(monkeypatch)
        _install_audit_root(monkeypatch, tmp_path / "audit_root")
        out = tmp_path / "out" / "hud.html"

        result = runner.invoke(
            app,
            ["hud", "--symbols", _KILLER_SYMBOL, "--equity", EQUITY, "--out", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert "SCAN AUDIT LOG" not in result.stdout


class TestW3ConsoleTeeCp1252Safe:
    """W3 (unit half, function-level per dispatch fallback — see module
    docstring's ASSUMPTIONS-FLAG): pins a private
    `tradekit.cli.main._tee_audit_log(text: str) -> None` seam directly,
    since the cp1252-crash-proof claim cannot be exercised through
    `CliRunner` (Click's own `isolation()` context manager replaces
    `sys.stdout` during `invoke()`, so a test-installed cp1252 stream never
    reaches the app)."""

    def test_does_not_raise_when_stdout_is_a_strict_cp1252_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CONTRACT: a log string containing U+2192 (RIGHTWARDS ARROW — not
        representable in cp1252) must not raise `UnicodeEncodeError` even
        when `sys.stdout` is a strict-cp1252 text stream (the Windows
        console default) — the write must be cp1252-crash-proof (e.g.
        `sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))`
        or an `errors="replace"` text write)."""
        from tradekit.cli.main import _tee_audit_log

        cp1252_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        monkeypatch.setattr("sys.stdout", cp1252_stdout)

        _tee_audit_log("GATE macd_signal | note: → not encodable in cp1252")  # must not raise

    def test_writes_the_given_text_content_under_a_normal_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CONTRACT: `_tee_audit_log` actually emits the given text under a
        normal (non-cp1252) stdout — not a no-op stub that merely swallows
        the crash-proofing requirement."""
        from tradekit.cli.main import _tee_audit_log

        _tee_audit_log("SCAN AUDIT LOG | header\n  GATE macd_signal | verdict: FAIL")

        captured = capsys.readouterr()
        assert "SCAN AUDIT LOG" in captured.out
        assert "GATE macd_signal" in captured.out


class TestW4CliRejectsUnknownAuditValue:
    """W4: unknown `--audit` value -> CLI rejects loudly."""

    def test_unknown_audit_choice_exits_two_and_writes_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """CONTRACT: `tk hud --audit bogus` is rejected before any scan/write
        is attempted — exit code 2 (Click's standard usage-error code for a
        `click.Choice` violation; same code this file's own AC-13 precedent
        uses for a missing `--equity`, test_hud_cli.py's
        `TestAC13MissingEquityIsUsageError`) — and `--out` is never created."""
        out = tmp_path / "hud.html"

        result = runner.invoke(
            app,
            [
                "hud",
                "--symbols",
                _KILLER_SYMBOL,
                "--equity",
                EQUITY,
                "--out",
                str(out),
                "--audit",
                "bogus",
            ],
        )

        assert result.exit_code == 2
        assert not out.exists()
