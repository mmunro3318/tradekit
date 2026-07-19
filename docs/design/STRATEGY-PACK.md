# DESIGN — STRATEGY-PACK (S2, S3, S4) — pinned, delegation-ready

CTO-authored (Fable, 2026-07-19). Prereq: MTF-SCAN.md (scan_confluence +
strategy registry) must land first. Evidence citations: Report 3
(docs/research/deep-research-reports/). Consumers: an Opus/Sol-led
implement round — every decision below is made; if an implementer meets
a question this doc doesn't answer, that's an ASSUMPTIONS flag, not a
choice they get to make.

**Doc-structure decision (CTO, explicit):** one pack, not three docs —
S2/S3/S4 share the MTF substrate, the filter vocabulary, and the
StrategyDef shape; separate files would duplicate exactly the shared
pins and drift. Phasing lives in the build order, not in file
boundaries. PAXG is deliberately NOT here (different data dependency, a
research gate before any build — see STRATEGY-BACKLOG.md MS-PAXG-1).

## Vocabulary additions (build once, in `mae._indicators`/`_scanner`)

Two new filters; everything else reuses the existing table:

| filter | semantics | tag on hit | family |
|---|---|---|---|
| `ema_above: n` | last close > EMA(n) of closes (EMA seeded with SMA(n), standard recursive form; if EMA not in indicators yet, implement there with a hand-derived 5-value golden) | `trend_up` | momentum |
| `rsi_band: [lo, hi]` | lo <= RSI(14) <= hi (inclusive both ends) | `pullback` | momentum |

Rationale for `rsi_band` (do not "simplify" it away): the existing
`rsi_max` path tags `oversold` with family mean_reversion, which the
regime gate correctly DROPS in trend regimes — but a pullback within an
uptrend is momentum-family context (Report 3 §3). Reusing `rsi_max`
would make S2 self-cancelling. This asymmetry is the whole reason S2
needs new vocabulary.

Also: `StrategyDef` gains `r_multiple_override: Decimal | None = None`
(MTF-SCAN's dataclass) — when set, the ticket bracket uses it instead of
sizing_info.r_multiple_target. Needed by S4 only.

## S2 — Pullback-continuation (build FIRST; primary fallback)

Evidence: Report 3 §3 — best evidence-to-complexity fit; enters the S1
bull thesis earlier and fires more often without loosening any S1 gate.

```python
StrategyDef(
    key="s2_pullback",
    side="buy",
    legs=(
        ScanLeg(timeframe="4h", filters={"ema_above": 50, "macd_signal": "bullish"}, min_tags=2),
        ScanLeg(timeframe="1h", filters={"rsi_band": [35, 50]}, min_tags=1),
    ),
    regime_families=("momentum", "breakout"),   # arms in trend regimes
    size_scale=Decimal("1"),
    r_multiple_override=None,                    # standard 2R ATR bracket
    tag="s2_pullback",
)
```

Pinned boundaries: RSI exactly 35 or exactly 50 → pullback tag FIRES
(inclusive); RSI 34.99/50.01 → leg fails. EMA(50) needs ≥50 closed 4h
bars — inside the 90d/4h pinned lookback (540 bars), fine; if bars < 50
the leg fails with the standard insufficient-bars warning.

Worked-example golden (spec stage MUST freeze before red): construct a
4h fixture trending up (closes strictly ascending, MACD hist > 0 by
construction) and a 1h fixture whose last RSI lands in [40, 45];
independently re-derive EMA(50) and RSI(14) for the fixture in a scratch
script (NOT via tradekit code) per the golden-freeze gate, then pin the
exact tag sets. Registry order after this lands: **S1, then S2** (S1's
stricter volume-confirmed signal outranks; first-match-wins).

## S3 — Confirmed breakout (build SECOND)

Evidence: Report 3 §2 — sibling of momentum, valid ONLY with volume
confirmation + vol-regime awareness; unconfirmed breakouts fail at
documented higher rates, hence every gate here is conjunctive.

New bb_position value: `"above_upper"` — last close STRICTLY greater
than the upper Bollinger band (20, 2.0) → tag `breakout_confirmed`
(family breakout). (Existing `at_resistance` means near-band-from-below;
do not overload it.)

```python
StrategyDef(
    key="s3_breakout",
    side="buy",
    legs=(
        ScanLeg(
            timeframe="4h",
            filters={"bb_position": "above_upper", "volume_spike": 2.0,
                     "atr_percentile_min": 60},
            min_tags=3,
        ),
    ),
    regime_families=("breakout",),
    size_scale=Decimal("1"),
    r_multiple_override=None,
    tag="s3_breakout",
)
```

Boundary pins: volume_ratio exactly 2.0 → fires (>= semantics, matches
existing volume_spike code); ATR percentile exactly 60 → fires. Registry
order: S1, S2, S3.

## S4 — Downside-extreme reversion (build LAST; restricted by design)

Evidence: Report 3 §4 — crypto mean-reverts only after downside
extremes on short lookbacks (Turatti 2020: mean AVERSION otherwise).
Every restriction below is load-bearing; none may be relaxed without a
new ASSUMPTIONS entry.

```python
StrategyDef(
    key="s4_reversion",
    side="buy",                                  # LONG-ONLY, permanent
    legs=(
        ScanLeg(timeframe="1h",
                filters={"rsi_max": 25, "bb_position": "at_support"},
                min_tags=2),
    ),
    regime_families=("mean_reversion",),         # arms ONLY when the regime
                                                 # recommends reversion (chop)
    size_scale=Decimal("0.5"),                   # half size, permanent
    r_multiple_override=Decimal("1"),            # target the mean (1R), not a trend
    tag="s4_reversion",
)
```

Time-stop (pinned): S4 theses carry `horizon_end = captured_at + 48h`
in the thesis contract (the confirm-time chain already sets horizon —
make it strategy-aware via StrategyDef; add `horizon_hours: int = 168`
defaulting to the current 7d, S4 sets 48). A reversion that hasn't
reverted in 48h is a broken thesis, not a position to nurse. Registry
order: S1, S2, S3, S4 (last = lowest priority, by evidence grade).

## Cross-cutting pins

- Sell-side emissions stay OUT of scope for the whole pack (spot
  long-only prop account; the sell-side ticket math fix from the
  hud-orderbook T5 review notes is a prerequisite for any future short
  pack — do not bundle it here).
- Grading attribution: every ticket/thesis carries the StrategyDef tag;
  `tk report`'s per-strategy cut becomes possible but is NOT part of
  this pack (separate small task later).
- Each strategy lands as its own tk-spec → red → green batch (S2 alone,
  then S3, then S4) — one registry entry + its vocabulary additions per
  batch, existing S1 hud tests pinned as regression throughout.
- DSR discipline unchanged: these go live as ADVISORY tickets under the
  same policy gate; formal edge validation (backtest → DSR ≥ 0.5)
  happens when M5.2's engine lands and can retroactively demote any of
  them. Codifying ≠ validated edge; the report column that says so
  stays honest.
