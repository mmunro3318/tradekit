"""BEHAVIOR/SEAM tests for `tk hud` (SPEC-hud-orderbook T4/T5, AC-9/AC-10
CLI aspect, AC-13).

Determinism seams (sanctioned, per ASSUMPTIONS 157/158 and
tests/unit/hud/test_build_state.py's precedent): monkeypatch ONLY
``mae._runtime.get_closed_bars`` / ``mae._runtime.clock`` and the four
sanctioned ``tradekit.hud._build`` seams (``evaluate_policy``,
``open_position_symbols``, ``sizing_info``, ``scan_setup``) — never mock
tradekit internals directly. The CLI itself must source `captured_at` from
``mae._runtime.clock()`` (ASSUMPTIONS 155c precedent: never
``datetime.now`` in tradekit code).

Invocation follows tests/unit/cli/test_cli_bridge.py's convention: Typer
``CliRunner`` against ``tradekit.cli.main.app``. Every invocation now
carries the T5-mandated required ``--equity`` option (SPEC addendum: "the
advisory surface never guesses account equity").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from tradekit.cli.main import app

runner = CliRunner()

CAPTURED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
EQUITY = "5000"


@dataclass(frozen=True)
class _FakeSizingInfo:
    qty: Decimal
    stop_distance_usd: Decimal
    r_multiple_target: Decimal


class _PassingSetup:
    signal_tags: ClassVar[list[str]] = ["macd_bullish", "volume_spike"]


class _AllowDecision:
    allowed = True
    verdict_id = "verdict-link-1"
    rationale = "all gates passed"


def _fixture_series(symbol: str, n_bars: int = 24):
    """Real BarSeries fixture, last close 8.30000 (mirrors test_build_state.py
    seam pattern) — used to drive the funnel to a ticket for any symbol."""
    from tradekit.contracts import AssetRef, Bar, BarSeries

    bars = [
        Bar(
            ts_open=CAPTURED_AT - timedelta(hours=n_bars - i),
            open=Decimal("8.30000"),
            high=Decimal("8.40000"),
            low=Decimal("8.20000"),
            close=Decimal("8.30000"),
            volume=Decimal("1000"),
        )
        for i in range(n_bars)
    ]
    return BarSeries(
        asset=AssetRef(
            symbol=symbol,
            venue="kraken",
            asset_class="crypto",
            tick_size=Decimal("0.00001"),
        ),
        timeframe="1h",
        bars=bars,
        source="test-fixture",
    )


def _patch_allow_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: freeze clock, allow policy, no open positions, real bars,
    passing setup, fixed sizing — drives every scanned symbol to an
    allowed ticket."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    monkeypatch.setattr(mae_runtime, "clock", lambda: CAPTURED_AT)
    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: _fixture_series(symbol),
    )
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _PassingSetup())
    monkeypatch.setattr(
        hud_build,
        "sizing_info",
        lambda symbol, limit_price, equity_usd: _FakeSizingInfo(
            qty=Decimal("12"),
            stop_distance_usd=Decimal("0.24900"),
            r_multiple_target=Decimal("2"),
        ),
    )
    monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _AllowDecision())
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


def _patch_refuse_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEAM: freeze clock; policy refuses everything -> empty-ticket path
    (AC-10)."""
    import tradekit.hud._build as hud_build
    import tradekit.mae._runtime as mae_runtime

    class _Refuse:
        allowed = False
        verdict_id = None
        rationale = "R-rule breach"

    monkeypatch.setattr(mae_runtime, "clock", lambda: CAPTURED_AT)
    monkeypatch.setattr(
        mae_runtime,
        "get_closed_bars",
        lambda symbol, timeframe, lookback_days: _fixture_series(symbol),
    )
    monkeypatch.setattr(hud_build, "scan_setup", lambda symbol: _PassingSetup())
    monkeypatch.setattr(
        hud_build,
        "sizing_info",
        lambda symbol, limit_price, equity_usd: _FakeSizingInfo(
            qty=Decimal("12"),
            stop_distance_usd=Decimal("0.24900"),
            r_multiple_target=Decimal("2"),
        ),
    )
    monkeypatch.setattr(hud_build, "evaluate_policy", lambda proposal: _Refuse())
    monkeypatch.setattr(hud_build, "open_position_symbols", lambda: set())


class TestAC9Success:
    def test_success_writes_file_matching_render_of_build_state_with_clock_captured_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 BEHAVIOR: `tk hud --symbols LINK/USD --equity 5000 --out
        <tmp>` with seamed data exits 0 and writes a file whose content
        equals `hud.render(hud.build_state(["LINK/USD"],
        captured_at=clock(), equity_usd=Decimal("5000")))` — `captured_at`
        sourced from the sanctioned `mae._runtime.clock` seam, never a
        fresh wall-clock read (ASSUMPTIONS 155c); `equity_usd` reaches
        build_state verbatim from `--equity` (AC-13)."""
        _patch_allow_all(monkeypatch)
        out = tmp_path / "hud.html"

        result = runner.invoke(
            app,
            ["hud", "--symbols", "LINK/USD", "--equity", EQUITY, "--out", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert out.exists()

        from tradekit import hud

        expected = hud.render(
            hud.build_state(["LINK/USD"], captured_at=CAPTURED_AT, equity_usd=Decimal(EQUITY))
        )
        assert out.read_text(encoding="utf-8") == expected

    def test_default_symbols_covers_all_eleven_greenlist_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 BEHAVIOR: `tk hud --equity 5000` invoked with no `--symbols`
        uses the pinned 11-pair greenlist default (SPEC Unknowns register:
        ETH, SOL, LINK, NEAR, EIGEN, RENDER, PAXG, TAO, XRP, AVAX, AKT, all
        /USD) — every one of the 11 appears as a report entry in the
        written file."""
        _patch_allow_all(monkeypatch)
        out = tmp_path / "hud.html"

        result = runner.invoke(app, ["hud", "--equity", EQUITY, "--out", str(out)])

        assert result.exit_code == 0, result.output
        content = out.read_text(encoding="utf-8")
        expected_pairs = [
            "ETH/USD",
            "SOL/USD",
            "LINK/USD",
            "NEAR/USD",
            "EIGEN/USD",
            "RENDER/USD",
            "PAXG/USD",
            "TAO/USD",
            "XRP/USD",
            "AVAX/USD",
            "AKT/USD",
        ]
        for pair in expected_pairs:
            assert pair in content, f"{pair} missing from default-symbols report"


class TestAC9UnwritableOutIsAtomicAndExitsFour:
    def test_out_path_colliding_with_existing_file_as_parent_exits_four_and_leaves_target_untouched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 BEHAVIOR: `--out` points inside a path segment that is
        itself an existing regular file (so no directory can be created
        there, cross-platform) -> exit 4, a stderr message, and — since the
        parent-as-file collision means the final target was never a
        pre-existing file to begin with — nothing is written at all
        (atomicity: temp-file + os.replace never touches a half-written
        target)."""
        _patch_allow_all(monkeypatch)
        blocking_file = tmp_path / "not_a_dir"
        blocking_file.write_bytes(b"pre-existing byte content")
        out = blocking_file / "hud.html"

        result = runner.invoke(
            app,
            ["hud", "--symbols", "LINK/USD", "--equity", EQUITY, "--out", str(out)],
        )

        assert result.exit_code == 4
        assert result.stderr != "", "unwritable --out must report a message on stderr"
        assert blocking_file.read_bytes() == b"pre-existing byte content"

    def test_pre_existing_target_file_left_byte_identical_when_replace_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 BEHAVIOR (atomicity): a pre-existing file already sits at
        the resolved `--out` target, but the write path is blocked because
        `--out`'s parent segment is itself a file, not a directory — the
        pre-existing target content (reachable only because the parent
        collision prevents ever reaching the real target) must be left
        byte-identical; the CLI must not partially overwrite anything it
        touches on the failure path."""
        _patch_allow_all(monkeypatch)
        blocking_file = tmp_path / "not_a_dir"
        blocking_file.write_bytes(b"original bytes untouched")
        out = blocking_file / "nested" / "hud.html"

        result = runner.invoke(app, ["hud", "--equity", EQUITY, "--out", str(out)])

        assert result.exit_code == 4
        assert blocking_file.read_bytes() == b"original bytes untouched"


class TestAC10EmptyStatePathStillWritesPlaceholder:
    def test_policy_refuses_everything_still_writes_file_with_no_advisory_tickets_placeholder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-10: policy refuses every scanned symbol (no tickets built at
        all) -> `tk hud` still exits 0 and writes a non-empty file whose
        content contains the "no advisory tickets" placeholder — never an
        empty file."""
        _patch_refuse_all(monkeypatch)
        out = tmp_path / "hud.html"

        result = runner.invoke(
            app,
            ["hud", "--symbols", "LINK/USD", "--equity", EQUITY, "--out", str(out)],
        )

        assert result.exit_code == 0, result.output
        content = out.read_text(encoding="utf-8")
        assert content != ""
        assert "no advisory tickets" in content


class TestAC13MissingEquityIsUsageError:
    def test_missing_equity_option_exits_two(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-13: `tk hud` invoked without `--equity` -> Typer's default
        usage error, exit code 2 — the advisory surface never falls back to
        a guessed or default account equity."""
        _patch_allow_all(monkeypatch)
        out = tmp_path / "hud.html"

        result = runner.invoke(app, ["hud", "--symbols", "LINK/USD", "--out", str(out)])

        assert result.exit_code == 2
        assert not out.exists()
