# STRATEGY BACKLOG — codified, queued, and researched-but-not-built

CTO-authored (Fable, 2026-07-19) so lower-tier session models can execute
without re-deriving strategy judgment. Evidence grades cite the deep-
research reports (docs/research/deep-research-reports/, Report 3 = the
strategy-families evidence review). Doctrine: STRATEGY-PROCEDURE.md.

## Volley 1 — LIVE today (codified in `tk hud`)

**S1. Momentum + volume confirmation (4h).** `macd_signal=bullish AND
volume_spike>=1.5`, regime-gated (tags surviving only when the HMM
regime's recommended families include momentum/breakout). Evidence: the
single best-supported family in crypto (R3 §1). Buy-side only. This is
deliberately the strictest, quietest battery — silence is a result, not a
malfunction.

## Volley 2 — queued (build order if volley 1 is structurally silent)

**S2. Pullback-continuation composite (best evidence-to-complexity fit,
R3 §3).** Trend up on 4h (e.g. price > EMA50, MACD hist > 0) AND pullback
on 1h (RSI dip 35-50, price near EMA20) AND no volume capitulation.
Multi-timeframe — needs the scanner to AND tags across timeframes for the
same symbol (small `_scanner` extension: per-symbol tag join across
`timeframes`). This is the FIRST fallback: same bull thesis as S1, earlier
entry, more signals, still doctrine-approved.

**S3. Confirmed breakout (sibling, R3 §2).** `bb_position=at_resistance
breached + volume_spike>=2 + atr_percentile_min` — ONLY with volume
confirmation and vol-regime filter (unconfirmed breakouts documented to
fail at higher rates). Build after S2, not before.

**S4. Downside-extreme asymmetric reversion (R3 §4, restricted).** Crypto
mean-reverts only after downside extremes on short lookbacks (Turatti
2020 found mean AVERSION otherwise). Long-only, RSI<25 + at_support +
regime=high_vol_chop, tight time stop. Lowest priority; smallest size.

**Never (banned v1, doctrine):** order-flow imbalance (until the tick/book
dataset matures — see below), OI/liquidation fades, chart-pattern
engines, stat-arb. Nothing below coin-flip gets built to "find action" —
the inactivity clock is handled by the OPERATIONS.md minimal-trade rule,
not by strategy desperation.

## MS-PAXG-1 — PAXG/gold basis (Mike's idea; research task, not yet a bot)

**The idea, sharpened.** PAXG is Paxos's gold token, redeemable ~1:1 for
allocated LBMA gold. In a perfect market PAXG ≈ XAU spot; in practice a
premium/discount band exists because true arbitrage (mint/redeem) has
institutional minimums + fees, so retail flows can push the token off its
peg — especially in fear spikes when crypto-native demand for gold jumps
faster than the token's arb channel closes it. That deviation is NOT
free-money arbitrage for us (we can't redeem), but it IS a mean-reverting
**basis signal**: fade excursions beyond the historical band, or ride
momentum INTO the band-widening during a macro shock and exit at
reversion. Mike's caution is exactly right and becomes the core rule:
**inside the normal deviation band = no trade.**

**Research plan (grunt-model executable, in order):**
1. Data: PAXG/USD 1h+1d from Kraken (mapped, live). Reference gold: we
   have NO XAU feed today — candidates: yfinance `GC=F` (futures, basis
   of its own), a free XAU/USD API, or XAUT/USD as a second token leg.
   DECISION NEEDED (flag to CTO): GC=F is easiest but adds futures basis;
   document whichever is chosen.
2. Build the paired series, compute basis_t = PAXG/XAU − 1. Stats:
   rolling mean/std (30d), full-history percentiles, half-life of
   mean-reversion (OU fit), seasonality cuts, and event windows around
   known macro shocks (rate decisions, war headlines, banking scares).
3. Backtest threshold rules (enter beyond ±k·std, exit at mean, time
   stop) with FULL costs: 4bps/side + observed PAXG spread (it's a thin
   book — spread is the strategy-killer to check first). Walk-forward,
   then the metrics chain: expectancy → PF → Sharpe → DSR. DSR ≥ 0.5 to
   screen, 0.95 to promote (house doctrine, no exceptions for pet ideas).
4. Only then: codify as a scanner battery or a dedicated `tk` verb.

**Prior expectation (honest):** thin PAXG books + no redemption access
means most of the band is untradeable after costs; the tradeable tail is
the shock-window behavior. The dataset (our own tick/book collector
already records PAXG/USD depth) is the real asset here — every week it
runs, the eventual analysis gets stronger.

## Tick/book dataset — what it unlocks (for later, per Mike's ask)

The collector records trades (price/qty/side/ord_type) and 10-level depth
snapshots hourly-rotated. Near-term uses: real spread/cost curves per
pair (feeds honest backtests), volume-profile levels, PAXG basis
microstructure. Long-term: order-flow imbalance features (currently
banned pending exactly this data maturing). A full explainer for Mike is
queued as a session task ("parquet data explainer").
