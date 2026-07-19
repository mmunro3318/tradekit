# DESIGN — MTF-SCAN (multi-timeframe scanning + cross-timeframe confluence)

CTO-authored (Fable, 2026-07-19), pinned and delegation-ready: a
Sonnet-tier implementer with this doc + tk-spec should need zero
judgment calls. Prereq for STRATEGY-PACK.md (S2/S3/S4).

## The physical constraint everything sits on (verified live)

Kraken OHLC **retains only the most recent 720 candles per interval** —
`since` filters within that window; deeper history does not exist on the
endpoint (probe 2026-07-19: since=60d @1h returned exactly the last 720
bars). Pagination is impossible; ProviderRangeError's message now states
this. Therefore every timeframe carries a HARD max lookback:

| timeframe | 720-bar retention | pinned scan lookback (headroom) |
|---|---|---|
| 15m | 7.5 d | 6 d |
| 1h | 30 d | 25 d |
| 4h | 120 d | 90 d |
| 1d | 720 d | 365 d |

Pin these in ONE place: `mae/_data/limits.py` →
`TIMEFRAME_MAX_LOOKBACK_DAYS: dict[str, int]` (the pinned-scan column),
consumed by the scanner and hud. Nothing else may hardcode a lookback.
Deep history beyond retention = the tick collector's job (accruing since
2026-07-19) — never a provider call.

## New verb (one, deep): `mae.scan_confluence`

`scan_markets` stays untouched (Surgical Changes; its single-timeframe
contract has existing consumers). New sibling:

```python
class ScanLeg(TypedDict):
    timeframe: str                  # key into TIMEFRAME_MAX_LOOKBACK_DAYS
    filters: dict[str, Any]         # same vocabulary as scan_markets
    min_tags: int                   # leg passes iff >= min_tags survive

def scan_confluence(
    asset_class: str,
    legs: list[ScanLeg],            # ALL legs must pass (AND composition)
    symbols: list[str],
    regime_gate: bool = True,
) -> dict[str, Any]:
    # returns {scan_ts, regime_context, matches: [
    #   {symbol, legs: {timeframe: {signal_tags: [...], indicators: {...}}},
    #    confluence: true}], warnings: [...]}
```

Semantics (pinned):
- Per symbol: evaluate each leg via the EXISTING `_evaluate_symbol_timeframe`
  (reuse, don't fork) at that leg's timeframe, bars fetched with that
  timeframe's pinned lookback. A leg with insufficient bars → symbol
  drops with a warning (same anti-silent doctrine as scan).
- Regime gate runs ONCE per symbol (existing cache pattern) and prunes
  every leg's tags. `min_tags` is checked AFTER pruning.
- A symbol matches iff every leg passes. Partial passes are reported in
  `warnings` as `"<symbol>: leg <tf> failed (<n>/<min> tags)"` — the HUD
  report needs the why, not just the absence.
- Determinism: bars only via `_runtime.get_closed_bars`; clock via
  `_runtime.clock` (existing seams; no new ones).

## Strategy registry (data, not code)

`src/tradekit/mae/_strategies.py` (exported read-only via `mae`):

```python
@dataclass(frozen=True)
class StrategyDef:
    key: str                        # "s1_momentum", "s2_pullback", ...
    side: Literal["buy", "sell"]
    legs: tuple[ScanLeg, ...]       # consumed by scan_confluence
    regime_families: tuple[str, ...] # families that must be in the regime's
                                     # recommended_strategies for the def to arm
    size_scale: Decimal             # multiplier on sizing_info.qty (1 or 0.5)
    tag: str                        # stamped into thesis contract + report

STRATEGIES: tuple[StrategyDef, ...]  # ordered by priority; first match wins per symbol
```

hud's `scan_setup` seam default changes from the hardcoded S1 battery to:
walk `STRATEGIES` in order, arm a def only if `regime_families` matches
the symbol's regime, return the first def whose legs all pass —
`_SetupResult` gains `strategy_key: str` (and the report's setup gate
rationale names it). One strategy per symbol per scan (first-match; no
stacking — stacking is a future ASSUMPTIONS decision, not an implementer
choice). Tickets stamp `strategy_key` into `warnings`-adjacent metadata
and the thesis contract's rationale so the grading loop can attribute
performance per strategy (the feedback loop from STRATEGY-PROCEDURE
stage 9 becomes queryable by tag).

## Error map

| Failure | Handling |
|---|---|
| leg timeframe not in TIMEFRAME_MAX_LOOKBACK_DAYS | ValueError at scan_confluence entry (caller bug, loud) |
| provider error on any leg | symbol dropped + warning (never an exception out of the verb) |
| empty STRATEGIES / no def arms | scan_setup returns empty tags → wait (existing path) |

## Test seams / plan (for tk-spec to expand into ACs)

- CONTRACT: ScanLeg/StrategyDef shape; registry ordering stable.
- BEHAVIOR: two-leg AND (pass/pass → match; pass/fail → warning with
  leg detail); min_tags boundary (exactly min passes, min−1 fails);
  regime prune applied per leg; first-match-wins across STRATEGIES;
  size_scale reaches sizing (qty × scale before quantize).
- SEAM: per-leg lookback equals the pinned table (assert the
  get_closed_bars call args — this is what keeps retention honesty).
- GOLDEN: one worked two-leg fixture (bars constructed so 4h trends up,
  1h dips) — derivation in STRATEGY-PACK S2's worked example.

## Task cut (for tk-tasks)

T-MTF-1 limits.py + retention pins (tiny, first). T-MTF-2
scan_confluence + tests. T-MTF-3 _strategies.py registry + S1 migrated
into it (behavior-identical for S1 — regression-pinned by existing hud
tests). T-MTF-4 hud scan_setup default → registry walk + report naming.
Order strict: 1→2→3→4. Only T-MTF-4 touches hud; none touch money-path.
