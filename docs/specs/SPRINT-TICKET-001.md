# SPRINT-TICKET-001 — pins (CTO, 2026-07-24)

Batch: macd vocab fix + loud-on-unknown filter values + scan-attrition
telemetry. Source: docs/tickets/TICKET-001-scan-attrition-telemetry.md,
ENGINEERING-CANON D4, test-audit items 1-2, gating-filter-audit H1+M1.
Strategy-behavior change — Mike sign-off given 2026-07-24 (plan approval).

## Pinned interfaces

### P1 — filter vocabulary becomes typed (D4 first line of defense)
New module `src/tradekit/mae/_vocab.py`, re-exported from `tradekit.mae`:

```python
from enum import StrEnum

class MacdSignal(StrEnum):
    BULLISH_CROSS = "bullish_cross"
    BEARISH_CROSS = "bearish_cross"

class BBPosition(StrEnum):
    BELOW_LOWER = "below_lower"
    ABOVE_UPPER = "above_upper"
    INSIDE = "inside"
```

`hud/_build.py` `_SETUP_FILTERS` becomes
`{"macd_signal": MacdSignal.BULLISH_CROSS, "volume_spike": 1.5}` (StrEnum ⇒
str comparisons/JSON unchanged). GLOSSARY.md scan-context table already names
these the canonical forms.

### P2 — scan() validates filter VALUES up front, loud
At the top of `_scanner.scan()`, after the existing `symbols is None` raise
and BEFORE any bar fetch (mirrors that precedent): unknown `macd_signal` or
`bb_position` value →
`ValueError(f"scan_markets: unknown {key} value {value!r}; expected one of {sorted(allowed)}")`.
Plain strings that match enum values remain accepted (StrEnum equality).
The per-candidate `else: return None` branches for these two filters become
unreachable; replace with `raise AssertionError` guards or restructure —
implementer's choice, but NO silent path may remain.

### P3 — scan() result gains attrition telemetry
Result dict gains key `"attrition"`: one entry per (symbol, timeframe) in
input order:

```python
{"symbol": str, "timeframe": str,
 "stages": [{"name": str, "outcome": "pass"|"fail", "observed": str}],
 "killed_by": str | None}   # first failing stage name, None if match survived
```

Stage names, fixed order as evaluated: `"bars"` (insufficient-bars →
outcome fail, observed = the warning text), then per-filter present:
`"rsi"`, `"macd_signal"`, `"bb_position"`, `"volume_spike"`,
`"atr_percentile"`, then `"regime_gate"` (fail = all strategy tags dropped;
observed = regime state). Stages after the killer are ABSENT (not "skip").
`observed` is a short human string (e.g. `"hist=-0.0035"`, `"vr=2.059"`).
Existing keys (`matches`, `warnings`, `regime_context`, `scan_ts`) unchanged
— additive only.

### P4 — hud writes the scan log + ledger note
`hud/_build.build_state` unchanged signature; internally composes scanner
attrition + its own downstream gates (sizing, policy_verdict) into
`HudState.attrition` (new frozen field, same per-symbol shape with the two
extra stage names). New pure helper `hud._build.render_attrition_log(state) -> str`
in Mike's format (ticket §4.2: header w/ ts+equity+universe, per-symbol
stage lines, SUMMARY with per-stage kill counts + `killer filter: X (n/m)`).
`tk hud` writes it to `data/scans/<UTC yyyy-mm-dd>/scan-<HHMMSS>.log`
(append-file create-dirs, atomic-ish plain write; failure to write log is a
stderr warning, never a scan failure).
Ledger: append event `ScanAttritionRecorded` (new contract payload,
additive): `{scan_ts, equity_usd, universe: list[str], tickets: int,
stage_kills: dict[str, int], killer_filter: str | None}` — summary only, NOT
per-symbol detail (log file carries detail; ledger stays lean). Appended once
per `build_state` call by the CLI layer (not by build_state itself — purity).

### P5 — test inversion (R-rule-adjacent, ratified)
`tests/unit/mae/test_scan_markets_verb.py:490` (unknown filter value →
`matches == []`) asserts behavior now ratified as a DEFECT. Invert to
`pytest.raises(ValueError, match="unknown macd_signal")`. ASSUMPTIONS
Round-27 entry below is the authorization; cite it in the test docstring.

## ASSUMPTIONS Round-27 (CTO-ratified, append to tests/ASSUMPTIONS.md)
- **162**: An unknown value for a closed-vocabulary scan filter
  (`macd_signal`, `bb_position`) raises `ValueError` at `scan()` entry —
  never an empty `matches`. Supersedes the silent-drop behavior pinned by the
  old test at test_scan_markets_verb.py:490 (inverted this batch).
  WHY: ENGINEERING-CANON D4 / Saltzer-Schroeder fail-safe defaults; the
  2026-07-23 S1 outage (TICKET-001).
- **163**: Attrition stage taxonomy + shapes per P3/P4; stages after the
  killer are absent; `observed` is human-oriented prose, not a parsing
  surface (the structured surface is `stage_kills`/`killed_by`).
- **164**: Scan-log write failure warns and continues; ledger
  `ScanAttritionRecorded` carries summary only.

## Fences
- Files touched: `mae/_vocab.py` (new), `mae/_scanner.py`, `mae/__init__.py`
  (export), `hud/_build.py`, hud CLI writer + `_render` if needed,
  `contracts/_event_payloads.py` (+schema export), tests under
  `tests/unit/mae/`, `tests/unit/hud/`, `tests/contract/`.
- NO policy/, broker/ changes in this batch (audit bundle is separate).
- Determinism: clock/bars only via `mae._runtime` seams. No new deps.
- Contract test (test-audit item 1) IS in scope: un-mocked
  `_default_scan_setup` against real scanner with synthetic bars via the
  `get_closed_bars` seam — asserts `_SETUP_FILTERS` speaks the scanner's
  vocabulary (would have been red for S1's whole life).
