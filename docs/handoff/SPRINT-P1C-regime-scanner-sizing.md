# SPRINT P1C — Regime, scanner, sizing, correlation (completes P1)

> Executor: Sonnet; **regime override logic and verdict wiring reviewed by Opus before merge** (it gates money later). Prereqs: P1A + P1B. References: DESIGN §9.2–9.4, TD-11/13, G1/G3, rules R-012/R-013 context.

## Mission

Implement the four remaining MAE verb stubs in `src/tradekit/mae/__init__.py`. Signatures are PINNED there — fill bodies, never alter parameters (TD-11 especially: `size_position` grows no P&L inputs, ever).

## New dependencies

`uv add hmmlearn` (brings scipy). Pin the versions uv resolves; note them in the dev log.

## Stories

### 1. `size_position` (do first — pure math + one ATR fetch)

> **UPDATE 2026-07-12: the math is DONE** — `mae/_sizing.py` (Kelly with negative-clamp, ATR position) with fraction-exact golden vectors in `tests/unit/mae/test_sizing.py`. Remaining work: fetch ATR(14)+price via the P1A data layer, assemble the canonical output dict, re-point tests through the public verb, add `_sizing` to the TID251 ban list (ASSUMPTIONS 23). The golden vectors below are already encoded in the tests.
- `kelly_full = W − (1−W)/R`; quarter-Kelly = 0.25×; clamp negative Kelly to 0 (negative edge = no position, warning `negative_kelly`).
- `atr_size_usd = (equity × risk_pct) / (atr × multiplier) × price` per canonical formula; `recommended = min(atr_size, kelly_size)`.
- Golden vectors (hand-derived — do NOT trust the canonical doc's example output, its arithmetic is wrong):
  - `W=.574, R=1.572` → `f* = .574 − .426/1.572 = 0.30302…` → quarter `0.07576`.
  - `W=.40, R=1.0` → `f* = −0.2` → clamped 0, `negative_kelly` warning, recommended size 0.
  - equity 1000, risk 1%, ATR 2.0, mult 2.0, price 100 → stop distance 4.0 → atr_units = 10/4 = 2.5 → atr_size_usd 250.
- Output must include every field in canonical §3 `size_position` (stop_distance, stop_pct, both sizes, risk_usd, r_multiple_target default 2.0).
- Emit nothing to the ledger here — `SizingComputed` is written by thesis.submit (P2), which CALLS this verb.

### 2. `get_regime` — HMM + deterministic fallbacks (G3 is the load-bearing part)
- `hmmlearn.GaussianHMM(n_components=n_states, random_state=1337)` on daily log-returns + realized vol (2 features). Fit ONLY via an explicit refit path; persist with pickle to `data/models/hmm-{symbol}-{lookback}.pkl` + a sidecar JSON (fit date, window, feature means). On call: load artifact; if missing or older than 7 days → refit (log it).
- State labeling: order states by fitted variance → lowest = `low_vol_trend`, highest = `breakdown`/`high_vol_chop` per n_states (map exactly as canonical §3 get_regime output).
- **EWMA override (G3):** every call, compute EWMA vol (span 20) over the last 30 daily returns; if `ewma_vol > state_mean_vol + 3×state_vol_std` (from the fitted state's emission params) → return `method="ewma_override"`, state `high_vol_chop`, `recommended_strategies=[]`. This must be pure arithmetic on top of the loaded artifact — no refit inside the override path.
- Rules fallback when < 60 daily bars: realized-vol percentile × ADX (P1B) grid → same output schema, `method="rules"`.
- Tests: synthetic return series with a planted vol spike must trigger the override (deterministic, seeded); persisted-artifact reload returns identical states for identical inputs (determinism test); insufficient history → rules path.

### 3. `get_correlation_matrix`
- Pearson on daily log-returns, `window_days`, inner-join on UTC dates where BOTH assets have bars (crypto weekends drop vs equities). `< 20` overlapping points → pair entry `null` + `insufficient_overlap` in a warnings list (NEVER a silent number; R-013 treats unmeasured as needs-review).
- Flag pairs |r| > 0.75 in `high_correlation_warnings` per canonical output shape.
- Tests: hand-built 30-point series with known r (construct y = 2x → r=1.0; y = −x → r=−1.0; independent seeded noise → |r| small); weekend-drop join test (7-day crypto vs 5-day equity series → join has 5 rows/week).

### 4. `scan_markets`
- Pipeline: resolve universe (explicit symbols only in this sprint — "full universe" scan deferred) → fetch bars per timeframe → compute only the indicators the filters need → apply filters (rsi_max/min, macd_signal, bb_position, volume_spike, atr_percentile_min per canonical input schema) → if `regime_gate`, call `get_regime` once per symbol and drop regime-incompatible strategy tags → emit canonical output shape with `signal_tags`.
- Tests: canned BarSeries fixtures with planted setups (an oversold-RSI bar, a volume spike); filter combinations AND together; `regime_gate=True` consults regime (mock the regime call — this is plumbing, regime correctness is story 2's job).

## Definition of done

- All four verbs return canonical §3 output shapes (tests assert key fields, not exhaustive dicts).
- Full suite green offline; `scripts/smoke_scan.py` does one live Kraken scan for Mike to eyeball.
- ROADMAP M1.4/M1.5 (Composio spike: timebox 1 session, connectors only, wiki note with verdict — Haiku can do the research, Sonnet the note).
- Dev-log + agent-metrics entries.

## Traps

- **hmmlearn convergence is flaky on short windows.** Catch non-convergence, fall back to `method="rules"` with a warning — never return a half-fit model's states.
- **Lookahead bias:** regime for a scan at time T must use bars with `ts_open + duration ≤ T`. The live (unclosed) bar NEVER feeds regime or indicators. Write the test.
- Pickle artifacts are trusted local state — fine here, but never load one from outside `data/models/` (path-validate).
- The scanner calls `get_regime` at most once per symbol per scan (cache in-call) — 50 symbols × 3 TFs must not mean 150 HMM loads.
