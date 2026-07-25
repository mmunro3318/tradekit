# SCAN-AUDIT-LOG — full-lifecycle scan trace (D8 seed)

> Authority for the scan audit-log feature. CTO-pinned 2026-07-25; open
> questions were auto-adjudicated this sprint per Mike's standing instruction.
> First concrete instance of the proposed repo-wide visibility standard
> (ENGINEERING-CANON D8 — to be generalized in a later spec; this doc is
> deliberately scoped to the scanner only).

## Mike's requirement (verbatim intent)

Show the lifecycle of a scan from start to finish: pull assets from the
approved list, walk each step of the algorithm as values are calculated —
every number, and the formula used at that stage. Print datasets so each
calculation can be replicated (display head/tail of the candle range inline).
Every gate must be explicit in the log: name, purpose, what it checks, why,
and whether a failure would terminate the flow. Add a testing toggle that
opens all gates so every gate's verdict is visible even after the first kill
— to get ahead of issues before a gate ever goes green for real.

## Interface (narrow — one new closed-vocabulary param)

```python
ScanAuditMode = Literal["off", "on", "exhaustive"]   # GLOSSARY-bound

scan(asset_class, timeframes, filters, symbols, regime_gate,
     audit: ScanAuditMode = "off") -> dict[str, Any]
```

- `"off"` — today's behavior, byte-identical. Default.
- `"on"` — same scan semantics + full audit trace written.
- `"exhaustive"` — audit trace + ALL present filters are evaluated for every
  candidate with sufficient bars, even after the first failure.
  **Kill semantics unchanged**: `killed_by` is still the FIRST failing gate,
  `matches` is identical to `"on"`. Gates evaluated after the kill are marked
  `(exhaustive-only — would not have run)`. Read-only scan; no money-path.

HUD wiring (only flag passthrough): `tk hud --audit [on|exhaustive]`.

## Trace module

`src/tradekit/mae/_scan_trace.py` (private, behind the scan verb):

- `GATE_SPECS: dict[str, GateSpec]` — static registry:
  `GateSpec(name, purpose, check, why, terminal: bool)` for: `bars`
  (insufficient-context), `rsi`, `macd_signal`, `bb_position`,
  `volume_spike`, `atr_percentile`, `regime_gate`. Every gate line in the
  log renders from this registry — purpose/check/why are never improvised
  at the call site.
- `FORMULAE: dict[str, str]` — static formula text per indicator, matching
  the pinned docstring conventions (EMA seed = SMA of first `period`; ATR
  Wilder seeding; MACD histogram; Bollinger; volume_ratio; percentile).
- Trace writer collects structured events during the scan and renders a
  human-followable log. **No recomputation**: the trace taps the exact
  arrays `_precompute_indicators` produced — a logged number can never
  drift from the number the gate actually compared.

## Output artifacts (clock via `_runtime.clock()` only)

```
data/scans/<UTC-date>/audit-<HHMMSS>.log          # the narrative trace
data/scans/<UTC-date>/audit-<HHMMSS>/<SYMBOL>-<tf>.csv   # full bar series
```

Log structure:
1. **Header**: scan_ts, audit mode, universe (the approved symbol list as
   passed), timeframes, active filters, regime_gate flag.
2. **Per symbol × timeframe section**:
   - Bar fetch: provider/source, lookback_days, bar count, then the first 5
     and last 5 bars inline (ts, O, H, L, C, V) with `... N more rows: see
     <sidecar CSV>` between. Full dataset always lands in the sidecar CSV so
     every calculation is replicable.
   - Per indicator actually computed: parameters, formula (from `FORMULAE`),
     input tail it consumed, and the computed value(s) the gate will read
     (last value + any intermediate the formula names, e.g. MACD line /
     signal / histogram).
   - Per gate, in pipeline order, a GATE block:
     `GATE <name> | purpose: ... | checks: <observed> vs <threshold> |
     why: ... | terminal: yes/no | verdict: PASS / FAIL(kills candidate) /
     SKIPPED(no filter set) / FAIL(exhaustive-only — would not have run)`.
3. **Footer**: existing attrition summary (killed_by tally) + matches +
   warnings.

Console echo: when invoked through hud with `--audit`, the same lines tee to
stdout (dev-time console + saved reviewable file — the D8 split).

## Red-stage adjudications (CTO, 2026-07-25)

- **Output-root seam (ratified):** `_scan_trace._OUTPUT_ROOT: Path` is the
  module-level base dir (defaults to `data/scans`), monkeypatched in tests
  exactly like `_runtime._cache_path`. No other path override mechanism.
- **Sidecar name sanitization (ratified):** symbols may contain `/`
  (e.g. `NEAR/USD`); sidecar filenames replace `/` with `_` →
  `NEAR_USD-<tf>.csv`. Log body still shows the raw symbol. Pinning test
  added in the review round (red-stage fixtures used slash-free symbols).

## Behavior pins (tests consume these directly)

- **B1** `audit="off"`: `scan()` return value and existing scan-log behavior
  unchanged (regression-pinned against current outputs).
- **B2** `audit="on"`: return value equal to `"off"` on identical inputs;
  audit log + sidecars exist with the pinned sections; every number in a
  GATE line equals the corresponding value in the returned
  attrition/matches structures.
- **B3** `audit="exhaustive"`: `matches`, `killed_by`, `warnings` all equal
  to `"on"`; every present filter has a verdict line for every candidate
  that passed the `bars` gate; post-kill verdicts carry the exhaustive-only
  marker.
- **B4** Unknown audit value raises loud `ValueError` (closed vocabulary,
  TICKET-001 convention).
- **B5** No real clock/network in tests — `mae._runtime` seams only
  (`_clock`, provider factory, cache path).

## Non-goals (this batch)

- No repo-wide logging framework, levels, or retention policy (that is the
  full D8 spec, later).
- No ledger/event-store writes; no changes under `broker/` or `policy/`.
- No change to which filters exist or their thresholds.
- HUD changes limited to the `--audit` flag passthrough (T-MTF-4 owns the
  bigger hud refactor).
