# SPRINT P1B — Indicator library + golden vectors

> Executor: Sonnet. Reviewer: Opus. Prereqs: P1A (Bar/BarSeries contracts). References: DESIGN §3 (no TA-Lib — every formula in-house and unit-tested), ROADMAP M1.2; canonical MAE doc §4 module list.

## Mission

`src/tradekit/mae/_indicators/` — pure functions over bar lists. No I/O, no state, no MAE-verb changes this sprint.

## New dependencies

`uv add numpy` (this sprint introduces it; keep it INSIDE `mae/`). pandas still deferred — indicators take `list[Bar]` or numpy arrays internally; the boundary type stays `list[Bar]`.

## Contract per indicator (uniform, non-negotiable)

```python
def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
```
- Input floats (analysis layer, §13). Output aligned 1:1 with input; positions with insufficient lookback are `None` — NEVER zero-filled, NEVER shorter arrays (misalignment is the classic off-by-one indicator bug).
- Wilder smoothing where the canon says Wilder (RSI, ATR, ADX): first value = simple average of first `period`, then `w_t = (w_{t-1}*(period-1) + x_t)/period`. Do not substitute EMA smoothing — values will be close enough to look right and wrong enough to change scans.

## Stories

1. **volatility.py**: `true_range`, `atr` (Wilder), `bollinger` (SMA ± k·population-σ), `keltner`.
2. **momentum.py**: `rsi` (Wilder), `macd` (12/26/9 EMA; EMA seed = SMA of first period), `stoch_rsi`, `roc`.
3. **trend.py**: `sma`, `ema`, `adx` (Wilder, needs +DI/−DI), `supertrend`.
4. **volume.py**: `vwap` (session-anchored: reset at UTC day boundary for crypto, exchange session for equities — document which), `obv`, `volume_ratio` (vol / 20-bar SMA of vol). CVD deferred to P3 (needs tick trades).
5. **structure.py**: swing-high/low S/R levels (fractal window k=2), QFL base detection per canonical doc. Simplest correct version; mark TODO-P5 for refinement.

## Golden vectors — the whole point of this sprint

For EACH indicator, `tests/golden/indicators/<name>.json`: input series + expected outputs. Derivation rules:
- Compute expected values ONCE from a reference implementation (e.g., a spreadsheet, or `pandas_ta`/`ta` installed in a THROWAWAY venv — never added to the project) — or hand-compute short series.
- Cross-check at least 3 points per indicator by hand arithmetic in the test file's comments.
- **NEVER generate expected values by running the code under test.** A reviewer who finds a golden file produced that way must fail the sprint.
- Include edge vectors: constant price (RSI → 100-or-None convention: pin one, document), fewer bars than period (all None), single bar, gap bar (high < prev close).

## Definition of done

- Suite green offline; each indicator's test cites its reference source in a comment.
- Property tests: output length == input length; `None` prefix length == documented lookback; ATR ≥ 0; RSI ∈ [0,100].
- ROADMAP M1.2 boxes; dev-log entry.

## Traps

- Off-by-one in Wilder seeding is THE historical indicator bug. The golden vectors catch it only if they include the first 2×period bars — make sure they do.
- MACD sign convention: histogram = macd_line − signal_line. Pin it in a test; both conventions exist in the wild.
- Don't "optimize" with numpy vectorization at the cost of the None-alignment contract. Correct first; these run on ≤720 bars.

## Addendum — CTO signature & convention pins (session P1B, 2026-07-15)

Written by the executing CTO session before dispatch; the reviewer reviews against
these pins. Internals are the implementer's; signatures and conventions are not.

### Signatures (multi-output = NamedTuple of aligned `list[float | None]`)

```python
# volatility.py
def true_range(highs, lows, closes) -> list[float | None]        # TR[0] = high−low (Wilder), never None
def atr(highs, lows, closes, period=14) -> list[float | None]    # Wilder, seed = SMA of first `period` TRs
def bollinger(closes, period=20, k=2.0) -> Bollinger             # (mid, upper, lower); POPULATION σ (ddof=0)
def keltner(highs, lows, closes, ema_period=20, atr_period=10, mult=2.0) -> Keltner
                                                                 # mid = EMA(close); bands = mid ± mult·ATR(atr_period)
# momentum.py
def rsi(closes, period=14) -> list[float | None]                 # Wilder; avg_loss == 0 → 100.0 (incl. constant price; RS→∞)
def macd(closes, fast=12, slow=26, signal=9) -> Macd             # (macd, signal, histogram); hist = macd − signal
def stoch_rsi(closes, rsi_period=14, stoch_period=14, k=3, d=3) -> StochRsi
                                                                 # (raw, k, d); raw ∈ [0,100]; max==min window → 0.0;
                                                                 # k = SMA(k) of raw, d = SMA(d) of k
def roc(closes, period=10) -> list[float | None]                 # (c_t/c_{t−period} − 1)·100
# trend.py
def sma(values, period) -> list[float | None]
def ema(values, period) -> list[float | None]                    # seed = SMA of first `period` (everywhere EMA is used)
def adx(highs, lows, closes, period=14) -> Adx                   # (plus_di, minus_di, adx); Wilder throughout
def supertrend(highs, lows, closes, period=10, mult=3.0) -> Supertrend
                                                                 # (line, direction); direction ∈ {1.0, −1.0, None};
                                                                 # basis (H+L)/2, ratcheting final bands; initial direction
                                                                 # pinned by golden vector + docstring
# volume.py
def vwap(bars: Sequence[Bar]) -> list[float | None]              # Σ(tp·vol)/Σ(vol), tp = (H+L+C)/3, reset at UTC day
                                                                 # boundary of ts_open. Works for US-equity RTH too: the
                                                                 # regular session never crosses UTC midnight — document.
                                                                 # Zero cumulative volume in session-so-far → None.
def obv(closes, volumes) -> list[float | None]                   # obv[0] = 0.0
def volume_ratio(volumes, period=20) -> list[float | None]       # vol / SMA(period) of vol
# structure.py
def swing_points(highs, lows, k=2) -> SwingPoints                # (swing_highs, swing_lows); level AT pivot index i iff
                                                                 # strictly greater (resp. lower) than all of i±1..k; edge
                                                                 # indices (< k from either end) can never be pivots;
                                                                 # docstring must state confirmation lags k bars (no lookahead
                                                                 # use before i+k).
def qfl_bases(lows, closes, k=2) -> list[float | None]           # at each i: most recent CONFIRMED (i.e. pivot idx + k ≤ i)
                                                                 # swing-low level not yet cracked; crack = close < level;
                                                                 # cracked base is dropped (None until next base confirms).
                                                                 # Simplest correct; bounce-magnitude/volume filters = TODO-P5.
```

Scalar inputs are `Sequence[float]` (floats — analysis layer, §13; Decimal→float
happens at the P1C caller boundary). Only `vwap` takes `Sequence[Bar]`.

### Lookback pins (first non-None index, default params — property tests assert these)

| fn | first non-None | fn | first non-None |
|---|---|---|---|
| true_range | 0 | roc(n) | n |
| atr(14) | 13 | sma(n)/ema(n) | n−1 |
| bollinger(20) | 19 | adx(14): DI | 14 |
| keltner(20,10) | 19 | adx(14): adx | 27 (= 2·period−1) |
| rsi(14) | 14 | supertrend(10) | 9 |
| macd: macd line | 25 | vwap / obv | 0 |
| macd: signal/hist | 33 | volume_ratio(20) | 19 |
| stoch_rsi: raw/k/d | 27 / 29 / 31 | | |

### Process pins

- Modules live in `src/tradekit/mae/_indicators/`; no re-exports from `mae`'s
  public surface this sprint (scan_markets wires them in P1C). Tests import the
  submodules directly — add the temporary-internal-import note to
  tests/ASSUMPTIONS.md (same pattern as `mae._data`, entry 33-ish).
- Golden vector JSONs carry provenance: `{"indicator", "params", "source":
  "<how derived>", "input": ..., "expected": ...}`. Reference-library values
  (throwaway venv) may be used ONLY after proving the library matches the pinned
  convention on a fully hand-computed short series; where conventions differ
  (e.g. EMA seeding), an explicit auditable step-by-step derivation is the
  reference. Hand cross-checks (≥3/indicator, in test comments) must include at
  least one value at the Wilder seed boundary (index period−1 … period+1).
- Numeric comparison: `pytest.approx(rel=1e-9, abs=1e-12)` — golden values are
  floats derived outside; bit-exactness is not the contract, the formula is.
