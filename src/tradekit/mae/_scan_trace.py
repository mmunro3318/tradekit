"""Scan audit-log trace writer (SCAN-AUDIT-LOG design doc, D8 seed;
docs/design/SCAN-AUDIT-LOG.md — authority for this module). Private, behind
`_scanner.scan`'s `audit` keyword; nothing here is re-exported from
`tradekit.mae`.

Mike's requirement (module docstring copy, see design doc): show the full
lifecycle of a scan — every number, the formula that produced it, and every
gate's name/purpose/check/why/terminality — with a testing toggle
("exhaustive") that keeps evaluating gates past the first kill so a gate's
verdict is visible even before it ever goes green for real.

No recomputation: `ScanTrace.record_symbol_timeframe` is handed the exact
`values` dict `_scanner._precompute_indicators` produced and the exact
`stages` list `_scanner._evaluate_symbol_timeframe` returned — a logged
number can never drift from the number a gate actually compared.

Output-root seam (ratified, design doc "Red-stage adjudications"):
`_OUTPUT_ROOT` is a plain module-level `Path`, monkeypatched directly in
tests the same way `_runtime._cache_path` is. No env var, no CLI flag.

Sidecar filename sanitization (ratified, same section): symbols may contain
"/" (e.g. "NEAR/USD"); sidecar filenames replace "/" with "_". The log body
always shows the raw, unsanitized symbol.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from tradekit.contracts import Bar

ScanAuditMode = Literal["off", "on", "exhaustive"]

_OUTPUT_ROOT: Path = Path("data/scans")
"""Base dir for audit artifacts: `<_OUTPUT_ROOT>/<UTC-date>/audit-<HHMMSS>.log`
+ `<_OUTPUT_ROOT>/<UTC-date>/audit-<HHMMSS>/<SYMBOL>-<tf>.csv` sidecars.
Monkeypatched directly in tests (never overridden any other way)."""


@dataclass(frozen=True)
class GateSpec:
    """One row of the static gate registry every `GATE <name>` log line
    renders from — purpose/check/why/terminal are never improvised at the
    call site (design doc "Trace module")."""

    name: str
    purpose: str
    check: str
    why: str
    terminal: bool


# Pipeline order (matches `_scanner`'s evaluation order: bars first, then
# rsi/macd_signal/bb_position/volume_spike/atr_percentile, regime_gate last).
GATE_SPECS: dict[str, GateSpec] = {
    "bars": GateSpec(
        name="bars",
        purpose="ensure every filter's indicator has a real, non-None value to read",
        check="last non-None indicator value present in the fetched window",
        why="a match built on a fabricated or None value is worse than no match",
        terminal=True,
    ),
    "rsi": GateSpec(
        name="rsi",
        purpose="momentum-extremity filter",
        check="last non-None RSI(14) vs rsi_max/rsi_min threshold",
        why="screens for over-extended momentum before entry",
        terminal=True,
    ),
    "macd_signal": GateSpec(
        name="macd_signal",
        purpose="trend-direction filter",
        check="last non-None MACD histogram sign vs bullish_cross/bearish_cross",
        why="confirms trend direction agrees with the requested signal",
        terminal=True,
    ),
    "bb_position": GateSpec(
        name="bb_position",
        purpose="band-position filter",
        check="last close vs Bollinger(20,2) upper/lower bands",
        why="confirms price sits at the requested band location",
        terminal=True,
    ),
    "volume_spike": GateSpec(
        name="volume_spike",
        purpose="volume-confirmation filter",
        check="last non-None volume_ratio(20) vs threshold",
        why="confirms the move is backed by real volume, not noise",
        terminal=True,
    ),
    "atr_percentile": GateSpec(
        name="atr_percentile",
        purpose="volatility-regime filter",
        check="ATR(14) <=-rank percentile within the fetched window vs atr_percentile_min",
        why="avoids low-volatility chop where setups tend to fail",
        terminal=True,
    ),
    "regime_gate": GateSpec(
        name="regime_gate",
        purpose="strategy-family regime filter",
        check="signal_tags after regime pruning vs before",
        why="drops tags whose strategy family the current regime does not recommend",
        terminal=False,
    ),
}

_GATE_ORDER: list[str] = list(GATE_SPECS)

# Static formula text per indicator, matching the pinned docstring
# conventions in `_indicators/momentum.py` and `_indicators/volatility.py`
# and `_indicators/volume.py` (EMA seed = SMA of first `period`; ATR Wilder
# seeding; MACD 12/26/9 histogram; Bollinger 20/2; volume_ratio v/SMA20;
# ATR percentile).
FORMULAE: dict[str, str] = {
    "rsi": (
        "RSI(14): diff[i]=closes[i]-closes[i-1]; gain=max(diff,0), loss=max(-diff,0); "
        "seed at index period: avg_gain=mean(gain[1:period+1]), "
        "avg_loss=mean(loss[1:period+1]); Wilder recurrence for i>period: "
        "avg_gain[i]=(avg_gain[i-1]*(period-1)+gain[i])/period (same shape for avg_loss); "
        "RS=avg_gain/avg_loss; RSI=100-100/(1+RS) (RSI=100.0 when avg_loss==0)"
    ),
    "macd_signal": (
        "MACD(12,26,9): macd_line=EMA(12)-EMA(26) of close (EMA seed = SMA of first "
        "`period` values); signal=EMA(9) of macd_line; histogram=macd_line-signal"
    ),
    "bb_position": (
        "Bollinger(20,2): mid=SMA(20); std=stdev(20, ddof=0); upper=mid+2*std; "
        "lower=mid-2*std; position = close vs [lower, upper]"
    ),
    "volume_spike": "volume_ratio(20): volume[i] / SMA(period=20)(volumes)[i]",
    "atr_percentile": (
        "ATR(14): Wilder-seeded average true range (seed = simple average of the first "
        "period true_range values, then atr[i]=(atr[i-1]*(period-1)+TR[i])/period); "
        "percentile = <=-rank of the last ATR value within the fetched window's "
        "non-None ATR values, scaled 0-100"
    ),
}

_INDICATOR_LINES: list[tuple[str, str, str]] = [
    # (values-key, formula-key, label)
    ("rsi", "rsi", "rsi(14)"),
    ("macd_hist", "macd_signal", "macd(12,26,9)"),
    ("bb_position_value", "bb_position", "bollinger(20,2)"),
    ("volume_ratio", "volume_spike", "volume_ratio(20)"),
    ("atr", "atr_percentile", "atr(14)"),
]


def _sanitize_symbol(symbol: str) -> str:
    """Sidecar filenames are flat files, not nested dirs — symbols
    containing "/" (e.g. "NEAR/USD") sanitize to "_" (ratified adjudication,
    design doc "Red-stage adjudications"). The log body always shows the
    raw symbol."""
    return symbol.replace("/", "_")


def _threshold_str(gate_name: str, filters: dict[str, Any]) -> str:
    """The threshold half of a GATE line's `checks: <observed> vs
    <threshold>` — read straight from the caller-supplied `filters` dict,
    never recomputed."""
    if gate_name == "rsi":
        parts = []
        if "rsi_max" in filters:
            parts.append(f"rsi_max={filters['rsi_max']}")
        if "rsi_min" in filters:
            parts.append(f"rsi_min={filters['rsi_min']}")
        return ", ".join(parts) if parts else "n/a"
    if gate_name == "macd_signal":
        return str(filters.get("macd_signal", "n/a"))
    if gate_name == "bb_position":
        return str(filters.get("bb_position", "n/a"))
    if gate_name == "volume_spike":
        return str(filters.get("volume_spike", "n/a"))
    if gate_name == "atr_percentile":
        return str(filters.get("atr_percentile_min", "n/a"))
    return "n/a"


def _bar_line(bar: Bar) -> str:
    return (
        f"{bar.ts_open.isoformat()} O={bar.open} H={bar.high} L={bar.low} "
        f"C={bar.close} V={bar.volume}"
    )


class ScanTrace:
    """Collects one scan's full-lifecycle trace and renders/writes it. No
    recomputation: every value logged is handed in by the caller (`scan()`),
    read straight from the same arrays/dicts the real gate checks used."""

    def __init__(
        self,
        ts: datetime,
        mode: ScanAuditMode,
        asset_class: str,
        timeframes: list[str],
        filters: dict[str, Any],
        symbols: list[str],
        regime_gate: bool,
    ) -> None:
        self._ts = ts
        self._lines: list[str] = [
            f"SCAN AUDIT LOG | scan_ts={ts.isoformat()} | mode={mode} | "
            f"asset_class={asset_class}",
            f"  universe: {len(symbols)} symbols",
            f"  timeframes: {timeframes}",
            f"  filters: {filters}",
            f"  regime_gate: {regime_gate}",
        ]
        self._bars_by_key: dict[tuple[str, str], list[Bar]] = {}

    def record_symbol_timeframe(
        self,
        symbol: str,
        timeframe: str,
        bars: list[Bar],
        source: str,
        lookback_days: int,
        values: dict[str, Any],
        stages: list[dict[str, Any]],
        filters: dict[str, Any],
    ) -> None:
        """Append one symbol/timeframe section: bar fetch (head/tail inline,
        full series to the sidecar), indicators actually computed, and every
        gate's verdict in pipeline order."""
        self._bars_by_key[(symbol, timeframe)] = bars
        sidecar_name = f"{_sanitize_symbol(symbol)}-{timeframe}.csv"

        self._lines.append(f"--- SYMBOL {symbol} TIMEFRAME {timeframe} ---")
        self._lines.append(
            f"  bars: source={source} lookback_days={lookback_days} count={len(bars)}"
        )
        n = len(bars)
        if n <= 10:
            head, tail, remaining = bars, [], 0
        else:
            head, tail = bars[:5], bars[-5:]
            remaining = n - 10
        for bar in head:
            self._lines.append(f"    {_bar_line(bar)}")
        if remaining > 0:
            self._lines.append(f"    ... {remaining} more rows: see {sidecar_name}")
        for bar in tail:
            self._lines.append(f"    {_bar_line(bar)}")

        for values_key, formula_key, label in _INDICATOR_LINES:
            if values_key not in values:
                continue
            self._lines.append(f"  indicator {label}: {FORMULAE[formula_key]}")
            self._lines.append(f"    value: {values_key}={values[values_key]}")
        if "atr_pctile" in values:
            self._lines.append(f"    value: atr_pctile={values['atr_pctile']}")

        stage_by_name = {stage["name"]: stage for stage in stages}
        for name in _GATE_ORDER:
            spec = GATE_SPECS[name]
            stage = stage_by_name.get(name)
            if stage is None:
                observed, threshold, verdict = "n/a", "n/a", "SKIPPED(no filter set)"
            else:
                observed = stage["observed"]
                threshold = _threshold_str(name, filters)
                post_kill = bool(stage.get("post_kill", False))
                if stage["outcome"] == "pass":
                    verdict = (
                        "PASS(exhaustive-only — would not have run)" if post_kill else "PASS"
                    )
                else:
                    verdict = (
                        "FAIL(exhaustive-only — would not have run)"
                        if post_kill
                        else "FAIL(kills candidate)"
                    )
            terminal = "yes" if spec.terminal else "no"
            self._lines.append(
                f"  GATE {name} | purpose: {spec.purpose} | checks: {observed} vs {threshold} "
                f"| why: {spec.why} | terminal: {terminal} | verdict: {verdict}"
            )

    def write(self, footer: dict[str, Any]) -> None:
        """Write sidecar CSVs (full bar series, one per symbol/timeframe)
        and the narrative `.log` file under `<_OUTPUT_ROOT>/<UTC-date>/
        audit-<HHMMSS>[.log|/]`."""
        date_dir = _OUTPUT_ROOT / self._ts.strftime("%Y-%m-%d")
        stem = f"audit-{self._ts.strftime('%H%M%S')}"
        sidecar_dir = date_dir / stem
        sidecar_dir.mkdir(parents=True, exist_ok=True)

        for (symbol, timeframe), bars in self._bars_by_key.items():
            sidecar_path = sidecar_dir / f"{_sanitize_symbol(symbol)}-{timeframe}.csv"
            with sidecar_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["ts_open", "open", "high", "low", "close", "volume"])
                for bar in bars:
                    writer.writerow(
                        [
                            bar.ts_open.isoformat(),
                            bar.open,
                            bar.high,
                            bar.low,
                            bar.close,
                            bar.volume,
                        ]
                    )

        tally: dict[str, int] = {}
        for entry in footer["attrition"]:
            killed_by = entry["killed_by"]
            if killed_by is not None:
                tally[killed_by] = tally.get(killed_by, 0) + 1
        self._lines.append("--- FOOTER ---")
        self._lines.append(f"  killed_by tally: {tally}")
        self._lines.append(f"  matches: {len(footer['matches'])}")
        self._lines.append(f"  warnings: {footer['warnings']}")

        log_path = date_dir / f"{stem}.log"
        log_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")
