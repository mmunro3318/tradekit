# STRATEGY-PROCEDURE — the battle procedure for finding, proving, and running an edge

> CTO doctrine draft, 2026-07-19. Status of each stage is marked
> **[EXISTS]** (code shipped and gate-green today), **[M5.2-PENDING]**
> (designed in docs/handoff/SPRINT-P5-PROP.md, not yet built), or
> **[NEW DOCTRINE]** (proposed by this document — requires CTO
> ratification before it is canon; nothing here silently becomes law).
> Companion evidence: docs/research/deep-research-reports/ Reports 2-6
> and the prop questionnaire (Q.<section>.<n>).

The one-sentence version: **indicators never trade; they classify.**
The system is a funnel — regime says what KIND of trade is even
allowed, the scanner says where a setup exists, the backtest chain says
whether that setup is a real edge or a statistical artifact, the prop
simulator says whether the edge survives the account's barriers, and
only then do sizing and the policy gate let money move. Edge selection
is not one step; it is the funnel — but the explicit ranking decision
lives at Stage 5.

---

## Stage 0 — Universe and data integrity [EXISTS]

**Inputs:** symbol list (Mike's universe, Q.D.44-55 eligibility rules),
timeframes 4h/1h/15m (Q.F.78-81), 1d for regime.

**Code:** every bar in the system flows through ONE door —
`mae._runtime.get_closed_bars(symbol, timeframe, lookback_days)`
(`get_daily_bars` is its `"1d"` alias). It strips any trailing bar
whose close time is after `clock()`'s now, so a still-open candle can
never reach an indicator (ASSUMPTIONS 45 — the lookahead trap Report 4
§1 calls "the most dangerous bias in the taxonomy"). Providers
(`mae/_data/kraken.py` et al.) are reached only through this seam.

**Decision rule:** insufficient/withheld data is loud, never silently
permissive. **Flows on:** clean closed-bar series.

Gap [M5.2-PENDING]: Kraken's public OHLC endpoint returns only the
last 720 candles per timeframe; deep history for backtests arrives via
the historical-CSV ingest (sprint §2c).

## Stage 1 — Regime classification [EXISTS]

**Inputs:** daily closed bars (90-day lookback default).

**Code:** `mae.get_regime` → `_regime.compute_regime(symbol,
lookback_days, n_states)`.

- Features per bar: `log_return_i = ln(close_i/close_{i-1})`;
  `realized_vol_i` = population stdev of the trailing 20 log-returns.
- 3-state GaussianHMM (diag covariance, `random_state=1337`), states
  labeled by realized-vol variance ascending: `low_vol_trend` →
  `high_vol_chop` → `breakdown`. Confidence = posterior
  `P(state | observations)`, last row.
- EWMA override (G3): `alpha = 2/21` over the last 30 log-returns; if
  `ewma_vol > calm_state_mean_vol + 3*calm_state_vol_std`, force
  `high_vol_chop`, recommend nothing — a vol spike vetoes everything.
- Rules fallback (<60 bars or HMM non-convergence): `vol_pctile > 0.8`
  → chop; else `ADX(14) >= 25` → trend; else `neutral`.

**What each state permits** (`_regime._strategy_tags` /
`strategies.TAGS` vocabulary):

| state | recommend | avoid |
|---|---|---|
| low_vol_trend | momentum, breakout | mean_reversion |
| high_vol_chop | mean_reversion | momentum, breakout |
| breakdown / ewma_override | nothing | everything |
| neutral (rules only) | nothing | nothing |

Report 6 validates this architecture: ADX≥25 is the near-universal
trend gate (§2), HMM three-state is mainstream (§1), and the
rules-fallback must PERMANENTLY coexist with the HMM as a check, not
be retired (§8). **Flows on:** state + confidence +
recommended/avoid families.

## Stage 2 — Scan: evidence-weighted indicator battery [EXISTS, weighting is NEW DOCTRINE]

**Code:** `mae.scan_markets` → `_scanner.scan(asset_class, timeframes,
filters, symbols, regime_gate)`. Filter vocabulary (AND-composed;
per-filter indicator, computed only if the filter is present):

| filter | indicator | tag on hit | family |
|---|---|---|---|
| `rsi_max`/`rsi_min` | `momentum.rsi(closes,14)` | oversold/overbought | mean_reversion |
| `macd_signal` | `momentum.macd(closes)` histogram sign | macd_bullish/bearish | momentum |
| `bb_position` | `volatility.bollinger(closes,20,2.0)` | at_support/at_resistance/bb_inside | mean_reversion / none |
| `volume_spike` | `volume.volume_ratio(volumes,20)` >= value | volume_spike | breakout |
| `atr_percentile_min` | `volatility.atr(h,l,c,14)` `<=`-rank pctile | high_volatility | breakout |

With `regime_gate=True`, `_apply_regime_gate` drops every tag whose
family is not in that symbol's `recommended_strategies` — this is the
mechanical "signals interpret each other" step: the SAME RSI-28 print
is a candidate tag in `high_vol_chop` and a dropped tag in
`low_vol_trend`.

**[NEW DOCTRINE — evidence weighting per Report 3, ratify:]**
- **In (strong evidence):** time-series momentum / trend-following
  (R3 §1 — the single best-supported family in crypto, 31.96% ann. TSM
  study + Han 2023) and pullback-continuation (R3 §3 — best
  evidence-to-complexity fit for our 4h/1h/15m structure; practitioner-
  consistent, no academic backtest, so OUR validation must supply the
  proof). Breakout/vol-expansion as sibling ONLY with volume
  confirmation and a vol-regime filter (R3 §2 — unconfirmed breakouts
  documented to fail at higher rates).
- **Deprioritized:** symmetric mean-reversion (R3 §4 — Turatti 2020
  found mean AVERSION in BTC multi-period returns; reversion is
  asymmetric, downside-extremes-only, short lookbacks). Range trading
  inherits the same caveat unvalidated (R3 §5).
- **Banned from v1 (explicitly):** order-flow imbalance (R3 §6 — sound
  theory, we lack tick/book data; Q.F.83), open-interest/liquidation
  fades (R3 §7 — practitioner heuristic only, opposing thesis
  category, v2 track), chart-pattern engines (R3 §8 — restates
  trend/breakout mechanics while multiplying n_trials; Q.E.72),
  stat-arb (R3 §9 — no crypto evidence, out of single-slot scope).

Note the honest tension: our scanner's mean_reversion-tagged filters
(oversold/at_support) carry the WEAKEST evidence, while the
best-evidenced family (pullback-continuation) is a composite the
scanner expresses only via a multi-timeframe filter combination —
Stage 3's job.

## Stage 3 — Candidate StrategySpec [M5.2-PENDING]

Declarative, thesis-shaped spec (sprint §2a): entry condition in the
scanner filter vocabulary + regime gate, direction, stop rule
(ATR-mult or structure), target rule, time expiry, `strategy_tag` from
`strategies.TAGS`. Rationale: backtested logic and live scanner logic
share ONE code path, and specs hash into the experiment registry.
Every spec declares prohibited regimes (Q.E.61), a market-mechanism
story (Q.E.66 — no mechanism, no live), and essential/nonessential
inputs (Q.E.77).

## Stage 4 — Edge quantification: the formula chain [metrics EXIST; backtest/walk-forward M5.2-PENDING]

`run_backtest`/`run_walkforward` (pending) produce `list[TradeRecord]`
→ the EXISTING `mae.compute_strategy_metrics` (`_metrics.compute`).
The chain, exactly as coded:

1. Per trade: `pnl = side * (exit-entry)/entry * size_usd - fees_usd`;
   `r = pnl / size_usd`.
2. `expectancy_usd = total_pnl / n` (mean pnl per trade, net of fees).
3. `profit_factor = gross_wins / |gross_losses|`; PF > 3 auto-flags
   `overfit_risk_pf` (Q.M.257 disqualifier lives at this threshold).
4. Trade-level Sharpe `SR = (mean(r) - rf_per_trade) / stdev(r)`,
   annualized by `sqrt(trades_per_year)`; Sortino uses full-sample
   downside deviation.
5. **DSR** (Bailey/López de Prado; n>=30 only): from the per-trade SR,
   sample skew and raw kurtosis, and the honest `n_trials` from the
   experiment registry, compute the benchmark
   `SR* = sqrt(V[SR]) * ((1-γ)Φ⁻¹(1-1/N) + γΦ⁻¹(1-1/(Ne)))`, then
   `DSR = Φ((SR - SR*)·sqrt(n-1)/sqrt(1 - skew·SR + (kurt-1)/4·SR²))`.
   10<=n<30 gets penalized Sharpe `SR_ann*(1-1/sqrt(n))`; n<10 is
   `insufficient`.
6. `edge_verdict` (deterministic table, `_metrics._verdict`):
   `negative` if expectancy<=0 or PF<1; `positive` iff PF>=1.3 AND
   expectancy>0 AND (DSR>0.5 at n>=30, else penalized SR>0);
   otherwise `marginal`.

Walk-forward wrapper (pending, Q.M.235/R4 §3): anchored expanding IS /
fixed OOS with embargo; every candidate evaluated increments the
append-only registry that feeds `n_trials` — R4 §5 is blunt that
discarding failed trials silently defeats the whole machinery.
Baselines (sprint batch D): buy-and-hold, random-entry-same-exit, SMA
trend — the random-entry control is the key one.

## Stage 5 — EDGE SELECTION: ranking across candidates [NEW DOCTRINE — ratify]

Already pinned (Q.E.60): deterministic weighted rank on expected value
per unit time, penalized by risk and cost share; LLM may VETO the
winner, never promote a loser. This doc proposes the concrete rule:

1. **Hard gates first (any failure = out, no ranking rescue):**
   `edge_verdict == "positive"`; n>=100 backtest trades (Q.M.238);
   Q.M.256 robustness battery (1-bar delay, 2x slippage, ±20% param
   perturbation, block-bootstrap p5 path passes the account sim, every
   n>=30 regime cell expectancy>=0 net); expected cost share <=15% of
   planned risk (Q.I.137, Report 2's cost model); no Q.M.257
   disqualifier (profits in <5 trades, single-regime, PF>3 w/o
   mechanism).
2. **Rank survivors by `DSR` descending** — DSR is the one number that
   already prices in sample size, non-normality, and how many things
   we tried (R4 §5), so it is the least-gameable primary key.
3. **Tiebreak (DSR within 0.05):** expectancy per hour held, net of
   costs, divided by max-drawdown share — i.e. Q.E.60's
   EV-per-unit-time with risk/cost penalty made concrete.
4. **Prop-fit is a gate, not a rank input** (Stage 6): a
   better-ranked strategy that cannot clear ruin<=2%/mo at ANY ladder
   rung loses the slot to a lower-ranked one that can.

Genuinely new here vs already-pinned: the DSR-first ordering, the 0.05
tiebreak band, and gate-vs-rank placement of prop-fit. R4 also
recommends adding PBO alongside DSR — flagged as a candidate metric,
not yet built.

## Stage 6 — Prop-fit: account-level survival [EXISTS]

**Code:** `tradekit.prop.simulate_evaluation(spec, seed=...)` —
parametric Monte Carlo (10k paths) of the trade profile against the
absorbing barriers (Kraken Prop Starter: $5,000; MDL 3% of the daily
00:30 UTC balance snapshot; MDD 6% static from starting balance;
target 10%; 4bps/side fees; 0.033%/day funding every 4h).
`recommended_max_risk_frac` scans a 0.25%→2% risk ladder and returns
the LARGEST rung with monthly ruin
`1-(1-ruin_prob)^(30/horizon) <= 2%` (Q.A.8) — `None` if nothing
clears, fail closed. Report 5 §1 is why this gate exists: ruin is
EXPONENTIAL in position size, and the eval is structurally a two-
barrier gambler's-ruin problem where distance-to-barriers dominates
edge (§3). Kraken's static (non-trailing) MDD means the real defensive
burden is the daily MDL ladder (R5 §4, Q.H.122-131).

## Stage 7 — Thesis contract + policy gate [EXISTS]

Every actual trade enters as a thesis: direction, entry, stop, target,
horizon, measurable invalidation — graded later by
`thesis._grading.evaluate_criteria` (Stage 9). Between agent intent
and money sits the policy gate (R-rules): risk caps, R-017/R-018
internal prop walls at 50%/70% of MDL and the 40% MDD reserve (sprint
§1a), unknown outcomes fail closed. Nothing in Stages 0-6 can move
money; only a thesis that clears the gate can.

## Stage 8 — Sizing [EXISTS]

**Code:** `mae._sizing` — position = **min(ATR-normalized,
quarter-Kelly)**:

- `kelly_fractions(win_rate, payoff_ratio, fraction=0.25)`:
  `f* = W - (1-W)/R`, clamped at 0 (negative edge = no trade),
  quarter taken as the working cap. R5 §2: quarter-Kelly is the
  practitioner standard, Kelly inputs need >=50 trades to trust, and
  Kelly is computed per-strategy, never blended.
- `atr_position(equity, risk_pct, atr, multiplier, price)`:
  `units = (equity × risk_pct)/(ATR × multiplier)` — a stop-out loses
  exactly `risk_usd`. `risk_pct` hard-capped at 5%; in practice
  bounded by Stage 6's `recommended_max_risk_frac` and the H.106/H.108
  drawdown-and-ramp ladders.

## Stage 9 — Execution, grading, feedback [EXISTS; execution bridge pending]

Execution is advisory-HUD / bridge (no Prop API). Afterward,
`evaluate_criteria` grades the thesis against closed bars only:
failure > invalidation > success within a bar (stop-and-target in one
bar = FAIL — same stop-wins canon the backtest engine will use);
horizon expiry with nothing triggered = FAIL; VOID only via measurable
invalidation — VOID can never erase a loss (§10.4 gaming vector).
Graded trades append to the live trade log → back into
`compute_strategy_metrics` (live DSR at n>=30, Q.L.223); CUSUM/SPRT
edge-decay monitoring (Q.N.260-264, R6 §6) can demote a strategy;
every new experiment increments the registry, tightening Stage 4's
DSR for all future candidates. The funnel is a loop.

---

## Worked example — ETH/USD, live pull 2026-07-19 (Kraken public OHLC via `get_closed_bars`)

**Stage 0/2 — real indicator battery** (computed with the shipped
`_indicators` functions; last closed bar per timeframe):

| | 1d (89 bars) | 4h (179) | 1h (335) |
|---|---|---|---|
| close | 1861.54 | 1869.97 | 1869.03 |
| RSI-14 | 58.68 | 57.88 | 60.90 |
| MACD hist | +15.10 | +0.53 | +0.065 |
| BB(20,2) | 1591-1949 | 1817-1897 | 1852-1875 |
| ATR-14 (pctile) | 73.28 (18%) | 19.92 (1%) | 7.69 (7%) |
| vol_ratio-20 | 0.40 | 0.34 | 1.24 |
| ADX-14 | 23.2 | 18.2 | 43.7 |

**Stage 1 — regime (rules-path features, daily):** realized-vol-20 =
0.0243, vol_pctile = 0.609 (not > 0.8 → not chop), daily ADX 23.2 < 25
→ **neutral** on the strict grid — right at the trend threshold.
Interpretation cascade: positive MACD on every timeframe + RSI high-50s
+ ATR percentiles compressed (1-18%) = a quiet uptrend consolidating,
not chop. Context flips meaning: 1h RSI 60.9 in `high_vol_chop` would
read "approaching overbought, fade candidate"; here, with 4h/1d
momentum positive and 1h ADX 43.7, the same number reads "healthy
continuation pressure." That reading is exactly what the regime gate
mechanizes: in a trend state, `oversold`/`at_support` tags get dropped
and momentum/breakout tags survive; in `neutral`, EVERY family-tagged
signal is dropped (ASSUMPTIONS 53) — today's strict answer is "no
strategy green-light; wait for daily ADX to confirm."

**Stage 3 — hypothetical candidate** (for the arithmetic): pullback-
continuation long — 4h MACD hist > 0 (trend context), 15m RSI <= 40
(pullback exhaustion), volume_ratio >= 1.2, entry next 15m open, stop
1.5×ATR(1h), target 1.8R, 24h expiry.

**Stage 4 — formula chain on a SYNTHETIC-BUT-REALISTIC 60-trade
walk-forward sample** (45% wins at +1.35%, losses -0.75%, $1,000
clips, $0.80 fees/trade, n_trials=12 from the registry; actual
`compute_strategy_metrics` output):

- expectancy = **+$1.15/trade**; avg win $12.70 / avg loss $8.30
- profit factor = **1.25** (below the 1.3 bar)
- Sharpe(ann) = 3.32, Sortino = 5.85
- **DSR = 0.20** — the naked Sharpe looks great, but after deflating
  for 12 tried variants the probability this beats luck is 20%
- **edge_verdict = "marginal"** → does NOT pass Stage 5's hard gate.
  This is the system working: positive expectancy is necessary, never
  sufficient.

**Stage 6 — prop-fit** (actual `simulate_evaluation`, parametric,
10k paths, win 45% / payoff 1.8 / 2 trades/day / 6h holds / 66%
notional, Kraken dials, 60-day horizon, seed 1337):

| risk_frac | pass_prob | ruin | monthly ruin |
|---|---|---|---|
| 0.25% | 1.8% | 6.4% | 3.2% |
| 0.50% | 56.2% | 10.8% | 5.5% |
| 0.75% | 76.1% | 16.9% | 8.9% |

`recommended_max_risk_frac = None` — NO ladder rung clears the <=2%/mo
cap for this profile; fail closed. A marginal 1.25-PF edge cannot
safely carry a $5k eval with a $300 static MDD. (Also visible: fees +
funding alone are why 0.25% risk still ruins 6.4% — Report 2/3's cost-
sensitivity warning in one number.)

**Stage 8 — sizing arithmetic (had it passed):** quarter-Kelly:
f* = 0.45 - 0.55/1.53 = 0.0905 → quarter = **2.26%**; ATR-normalized
at 0.5% risk: risk_usd = $25, stop = 1.5×7.69 = $11.54 (0.617% of
price), units = 25/11.54 = **2.167 ETH ≈ $4,051 notional**. Binding
constraint = min(0.5% ATR-rule, 2.26% Kelly, Stage 6 rung) — here
Stage 6's `None` zeroes it. No trade.

**Stage 9:** had it traded and printed 1889.80 (target) and 1857.49
(stop) inside one 15m bar, grading rules FAIL, not PASS — ambiguity
resolves against the agent, and the FAIL flows into the live metrics.

---

## New doctrine proposed here (needs CTO ratification)

1. Stage 2 evidence weighting: R3-strong families in; OFI, OI/liq
   fades, chart patterns, stat-arb explicitly banned from v1 scanning.
2. Stage 5 selection rule: hard gates → DSR-first rank → EV-per-time
   tiebreak within 0.05 DSR → prop-fit as gate not rank input.
3. Adopt R4's decay-ratio (<0.5 = overfit), rolling-vs-anchored gap
   diagnostic, param-count < sqrt(observations) bound, and PBO as
   walk-forward report fields.
4. R6: heatmap-neighborhood parameter selection + out-of-order holdout
   for regime-filter changes; variance-ratio test as a G.95
   regime-confidence candidate.
5. R5: staged Kelly trust — 30-trade DSR gate governs trading at all;
   >=50 trades before per-strategy Kelly inputs override the fixed
   conservative default; flag any Kelly f* > 20% as suspect.

## Report findings vs what's built — frictions found

- **No contradictions with shipped code.** R4 §5 validates the DSR
  machinery as-built; R6 validates the 3-state HMM + rules fallback;
  R5 validates quarter-Kelly and negative-clamp; triple-barrier
  labeling (R4 §4) is structurally what thesis grading already does.
- **Tension, not contradiction:** R4 §3 notes rolling walk-forward is
  often more realistic than our pinned anchored protocol (Q.M.235) —
  resolution: keep anchored primary, report rolling as diagnostic.
- **Tone check:** DSR literature treats ~0.95 as the confidence bar;
  our `_verdict` uses DSR > 0.5. Ours is a *screening* band (candidates
  then face Q.M.256 robustness + holdout), but the gap should be a
  conscious, documented choice — flagged, not changed.
- **Scanner semantics flags still open:** `macd_signal` "cross" is
  implemented as histogram sign, not an actual crossover event
  (flagged in `_scanner` docstring, unratified).
