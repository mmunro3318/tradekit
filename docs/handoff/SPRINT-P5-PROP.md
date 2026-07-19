# SPRINT P5-PROP — Prop barrier machinery + backtest engine

> Design + implementation plan, authored 2026-07-19 (CTO). Context:
> Kraken Prop Starter Eval 1 is live ($5,000; MDL $150/day, MDD $300
> lifetime, target $500). NO API exists for Prop (probe-confirmed);
> execution is advisory-HUD / execution-bridge. This sprint builds the
> two unblocked, purely-internal work items everything else consumes:
> **(1) prop account dials + evaluation barrier simulator** and
> **(2) the bar-based backtest / walk-forward engine (M1.3 open box)**.
> Read with: docs/research/prop-questionnaire-answers-CTO-2026-07-18.md
> (binding design calls, cited as Q.<section>.<n>) and
> docs/research/kraken-prop-report1-2026-07-19.md (venue mechanics).

## Ground rules (unchanged house law)

Four-stage TDD batches (pin→red→green→gate→review→fix), bespoke
subagent prompts, `(red)` commits, tk-gate before every green commit,
ASSUMPTIONS flag-don't-improvise, money-path review round before commit
(policy/ changes here ARE money-path). Determinism: seeded RNG only,
no wall clock — clock/rng enter as parameters or `mae._runtime` seams.

---

## Work item 1 — Prop dials + evaluation barrier simulator

### 1a. Dials (policy layer, TD-24 shape)

Extend `AccountConfig`/`PolicyDials` with a prop constraint block —
all slots `None = disabled` (existing TD-24 convention):

- `prop_mdl_pct` (0.03) — max daily loss as pct of the 00:30 UTC
  **balance** snapshot (NOT equity; report §6 is definitive).
- `prop_mdd_pct` (0.06) — static lifetime drawdown from **starting
  balance** (does not trail).
- `prop_profit_target_pct` (0.10).
- `prop_fee_side_bps` (4.0), `prop_funding_daily_pct` (0.00033,
  charged every 4h on open positions — venue-exact, report §8).
- Internal survival buffers (Q.H.122–123/130–131):
  `internal_daily_soft_frac` (0.50) / `internal_daily_hard_frac`
  (0.70) of MDL; `internal_mdd_reserve_frac` (0.40) of MDD.

Wire R-017/R-018 to evaluate against the INTERNAL walls (fractions of
venue limits), keeping the venue numbers as the outer truth. New audit
outcomes stay inside the existing ALLOWLIST discipline — unknown
outcomes fail closed.

**Breach semantics pins** (each becomes a test):
- MDL breach: real-time equity < snapshot_balance × (1 − mdl_pct) —
  equality at the boundary = breach (anti-permissive).
- Snapshot uses balance only; an open position at 00:30 UTC does not
  change the snapshot but its unrealized P&L counts against the new
  day immediately after.
- MDD breach: equity ≤ starting_balance × (1 − mdd_pct), any time.
- Fees and funding reduce balance and count toward both.
- Target hit: venue force-flattens; simulator models this as
  absorbing "passed" state.

### 1b. Barrier simulator — new module `src/tradekit/prop/`

Deep module, one verb surface:

```
simulate_evaluation(spec: PropSimSpec, *, seed: int) -> PropSimResult
```

- `PropSimSpec`: starting_balance, dial block above, trade model
  (either parametric: win_rate, payoff_ratio, risk_frac,
  trades_per_day, hold_hours — or empirical: a TradeRecord/return
  sample to block-bootstrap), n_paths (default 10_000), horizon_days.
- Engine: per-path daily loop → per-trade P&L draws → fee + 4h-funding
  accrual → equity curve → absorbing barriers (MDL resets daily off
  balance snapshot; MDD static; target). Decimal for money, float for
  ratios (§13 convention).
- `PropSimResult`: pass_prob, ruin_prob (split by MDL vs MDD),
  expected_days_to_outcome, percentile equity paths, per-day breach
  hazard, and `recommended_max_risk_frac` — the largest risk tier
  whose ruin_prob clears Q.A.8 (≤2%/mo) — this number is the sprint's
  headline deliverable for Mike.
- Funded-mode variant: same engine, no target barrier, payout-cadence
  stats (Q.M.242).

### 1c. Test plan (batch A red)

Hand-derived goldens for: MDL boundary-equality breach; balance-vs-
equity snapshot worked example (transcribe report §6's $100k example
+ our $5k numbers); fee/funding accrual to the cent over a 3-day
2-position scenario; MDD static-not-trailing (gain then give-back);
seed reproducibility (same seed = identical result object); sanity
envelopes (zero-edge spec → pass_prob ≈ target/(target+mdd) region,
document derivation in ASSUMPTIONS; negative-edge → ruin-dominated).
CTO freeze gate: independent re-derivation of every golden before
freezing (standing process — it has caught a defect every sprint).

---

## Work item 2 — Backtest / walk-forward engine (M1.3 open box)

### 2a. Shape

`mae._backtest` — INTERNAL, reached only through
`compute_strategy_metrics`-style public verbs (standing pin, ROADMAP
M1.3 note). Public surface (mae verbs):

```
run_backtest(strategy: StrategySpec, bars: BarFrame, costs: CostModel,
             *, mode: Literal["standard","delayed_entry"]) -> BacktestResult
run_walkforward(strategy, bars, costs, *, protocol: WalkForwardSpec)
             -> WalkForwardResult
```

- `StrategySpec` (declarative, thesis-shaped — NOT arbitrary
  callables): entry condition expressed in the scanner filter
  vocabulary (rsi/macd/bb/volume/atr percentile + regime gate),
  direction, stop rule (ATR-mult or structure), target rule, time
  expiry, strategy_tag from `tradekit.strategies.TAGS` vocabulary.
  Rationale: keeps backtested logic and live scanner logic the SAME
  code path (no backtest/live divergence), and keeps specs
  serializable for the experiment registry.
- Execution semantics (each is a pinned test): signals evaluate on
  candle close (Q.E.70); entry at next bar open; intrabar stop/target
  resolution uses **stop-wins-on-ambiguous-bar** (same rule as thesis
  grading — one canon); time-expiry exits at close of expiry bar;
  `delayed_entry` mode shifts entry one further bar (Q.M.247 stress).
- `CostModel`: per-side bps + spread bps + slippage bps + funding
  accrual (reuses 1a's fee logic — single fee canon) + prop-basis bps
  slot (spot-vs-PROP instrument basis, default 2bps until Report 2).
- Output: `list[TradeRecord]` → feeds the EXISTING
  `compute_strategy_metrics` (edge_verdict, DSR) and 1b's simulator
  (trade sample → account-level pass/ruin). No second metrics canon.

### 2b. Walk-forward + experiment registry

- Anchored walk-forward (Q.M.235): expanding IS, fixed OOS windows,
  embargo gap dial; per-segment metrics + aggregate.
- **Experiment registry** (starts here — the open n_trials gap):
  append-only JSONL keyed by strategy-spec hash; every evaluated
  candidate increments the count; `compute_strategy_metrics`'s
  n_trials input reads from it. This makes the DSR deflation honest
  the day strategy search begins. Registry writes get a path seam
  (standing rule: every writer gets a seam).

### 2c. Data

- Kraken spot OHLC public endpoint returns only the LAST 720 candles
  per timeframe — insufficient for M.231 history. Acquisition plan:
  Kraken's downloadable historical CSVs (Mike's hands or scripted
  download) into the existing cache under a `kraken` provider key;
  provider module `data/_kraken.py` mirrors the existing provider
  seams (`mae._runtime.get_closed_bars` untouched as THE access
  path).
- Start tick/trade collection now (Q.F.83): small collector script +
  scheduled task, Parquet sink, 2y rolling retention (Q.Q.321).
  Not a blocker for batches A–C.

### 2d. Batches

- **A (red→green)**: prop dials + breach semantics + simulator core
  (goldens above). Money-path review round before green commit.
- **B**: StrategySpec/CostModel contracts + bar-loop trade resolution
  (goldens: hand-walked 20-bar scenarios covering every execution
  semantic, incl. ambiguous bar + expiry + delayed mode).
- **C**: walk-forward driver + experiment registry + integration:
  spec → backtest → metrics → prop sim end-to-end on synthetic bars.
- **D**: Kraken OHLC provider + historical data ingest + first REAL
  data pull-through (baseline suite: buy-and-hold + random-entry-
  same-exit + SMA trend on BTC/ETH — Q.L.207; random-entry baseline
  is the key control).

Model tiers per MVM: contracts/goldens red-phase by top model (me);
green passes Sonnet against pinned tests; reviews Opus/top with
pre-registered focus (suggested: batch A = boundary/reset semantics;
batch B = look-ahead leakage; batch C = registry honesty; batch D =
point-in-time discipline of ingested data).

---

## After this sprint (dependency-ordered next steps)

1. **Execution Bridge (`BridgeBroker`) + advisory HUD** — outbox order
   tickets / inbox fill reports, executor-agnostic (Mike, Codex, later
   API); reuses reconcile + halt machinery; Claude screenshot
   cross-check as independent reconcile verifier.
2. **tradekit Substrate Contract doc** (CTO-written) for the GPT design
   sequence; then Math Primer alignment.
3. **Strategy #1 design** (pullback-continuation family per Q.E.56) —
   spec'd as a StrategySpec, validated through batches A–D machinery,
   promoted per Q.M.256 robustness gates.
4. **Blocked/external**: Kraken support ticket (stop persistence =
   autonomy gate; API access), Report 2 (microstructure → CostModel
   parameters), remaining MIKE questionnaire answers, key rotations.

## Open flags for ASSUMPTIONS ratification (do NOT improvise)

- Zero-edge pass_prob analytical envelope derivation (1c) — number and
  tolerance need CTO derivation at red-phase time.
- Prop-basis default 2bps — observed once (ETH, 2026-07-19 screen);
  ratify as placeholder-pending-Report-2.
- Entry fill price = next bar open exactly (no spread-half adjustment)
  vs open+spread/2 — pick at batch B pin time, document either way.
- Whether PropSimSpec's parametric mode uses independent draws or
  enforces serial correlation via block length dial — batch A pin.
