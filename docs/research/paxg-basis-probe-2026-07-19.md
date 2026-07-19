# PAXG/gold basis — first empirical probe (2026-07-19, Fable)

Question (Mike): PAXG is tethered to gold; is the deviation harvestable?
This probe ran REAL numbers (497 overlapping daily closes, 2024-07-29 →
2026-07-19: PAXG/USD from Kraken OHLC @1d, gold via Yahoo GC=F front-month
futures — stooq's XAUUSD is now behind a JS wall; no keyless spot-XAU
daily source found, flag for Mike's Perplexity round).

## Raw findings

- Basis = PAXG/GC − 1: mean **+0.23%** (persistent token premium), sd
  0.77%, extremes −3.5% / +4.4%. The premium itself is structural
  (redemption friction + crypto-native demand) — the tradeable object is
  the DEVIATION from a rolling mean, exactly as Mike intuited ("don't
  jump inside the average deviation").
- Deviations beyond 2σ of a 30d rolling band happen ~10% of days;
  AR(1) half-life of the deviation ≈ **0.6 days** — excursions collapse
  fast.
- Naive same-close fade backtest (enter at the closing print that
  defines the signal, 20bps round-trip cost): 24 trades, **+1.9%/trade,
  96% win rate**. ← *This number is the lesson, not the result.*

## The artifact hunt (why 96% is a red flag, not an edge)

A 96% win rate in a first naive backtest is almost always measurement
error. Three artifacts are baked into this data:
1. **Timestamp misalignment** — Kraken daily closes at 00:00 UTC; GC=F
   settles on NY hours. The two prices are ~5-6h apart; gold's move in
   between manufactures fake "deviations" that "revert" when the series
   realign next day.
2. **Thin-book closes** — PAXG's Kraken book is thin; a stale last trade
   IS a fake deviation that reverts when the next real print lands
   (bid-ask bounce at daily scale).
3. **Futures roll** — GC=F contract rolls create basis jumps that are
   calendar mechanics, not signal.

Robustness check: forcing entry at the NEXT day's close (can't trade the
print that measured the signal) collapsed the result to 23 trades,
**+0.65%/trade, 61% win, +14.9% total over ~15.5 months** — i.e. ~⅔ of
the naive edge was artifact. The remainder is NOT validated edge either;
it still contains artifacts 1-3.

## Verdict + the real path (MS-PAXG-1 next steps)

Daily-close data CANNOT settle this question — the signal's half-life
(<1 day) lives below the sampling interval. The honest instrument is the
one we're already building: **our tick collector has been recording
PAXG/USD trades + 10-level depth since 2026-07-19.** The real study:
1. Same-timestamp comparison: PAXG book MID (not last trade) vs a spot
   XAU print at the same UTC minute. Needs an intraday XAU source —
   the one genuine blocker (candidates: TwelveData/metals-API free
   tiers, or GC=F intraday via Yahoo; decision for Mike/CTO).
2. Executable prices: cross the observed spread from our book data, not
   a 20bps guess — with a thin book, spread is the strategy-killer.
3. Event windows (rate decisions, macro shocks) where the deviation
   widens beyond the arb channel's speed — the only regime where the
   naive story plausibly survives costs.
4. Only then the metrics chain (expectancy → DSR ≥ 0.5 screen). No bot
   before that gate; ~weeks of collector data needed for (1)-(3).

Wisdom line for the log: **the first backtest of any basis trade mostly
measures your data's clock skew.** Every future strategy probe in this
shop runs the next-period-entry check before anyone gets excited.

Probe script: experiments/paxg-basis/probe_daily_basis.py (rerunnable).
