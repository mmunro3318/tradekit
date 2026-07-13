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
