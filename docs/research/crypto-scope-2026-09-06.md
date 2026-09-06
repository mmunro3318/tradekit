# Crypto scope — 2026-09-06 22:00 UTC (LINK impulse day)

Mike asked for market scope + trade plans after LINK's jump. Everything below is
from OUR archive (D:\tradekit-data, collectors healthy: LINK 21:00 hour files
written 21:37 UTC) plus the toolkit's own funnel (`tk hud --audit on`) and
Kraken 1h/1d bars via `mae._runtime.get_closed_bars`. Scratch scripts:
session scratchpad `mkt.py`, `mkt2.py`, `evt.py` (not repo code).

## 1. Tape (Kraken, last closed 1h close vs N ago)

| sym | px | 1d | 3d | 7d | 30d |
|---|---|---|---|---|---|
| ZEC | 1223.6 | +21.3 | +27.9 | +43.4 | – |
| TAO | 267.2 | +14.4 | +16.3 | +13.2 | – |
| TIA | 0.42 | +12.3 | +12.7 | +23.9 | – |
| NEAR | 2.41 | +11.5 | +22.1 | +28.3 | +51.5 |
| LINK | 13.10 | +9.0 | +10.2 | +13.7 | – |
| SOL | 105.7 | +2.4 | +0.8 | +0.9 | +44.0 |
| ETH | 2499 | +0.9 | -0.2 | +0.3 | +31.1 |
| BTC | 79909 | +0.2 | -1.9 | +1.7 | – |

Breadth 1d>0: 23/25; 7d>0: 24/25; median 30d +42%. Daily structure: LINK closed
12.05 = 200-day high, above SMA20/50/100/200 (11.26/9.59/8.77/8.99), 90d low
7.19 (+68%). LINK/BTC ratio 1.51e-4 vs 1.26e-4 30d/90d ago — relative strength
is real. BTC 79.8k vs SMA50 69.1k / SMA200 69.7k, 90d high 81.3k (09-03).
Toolkit regime model: `low_vol_trend` (momentum/breakout families armed).

Read: "crypto surging" is true on the 30–90d horizon; TODAY it is an alt
rotation (ZEC/TAO/TIA/NEAR/LINK) on flat majors (BTC 1d realized vol 15%).

## 2. LINK impulse anatomy (Kraken + Coinbase 5-min, OKX liqs, HL perps)

- Whole day's +8.7% happened 20:30–21:05 UTC: 12.43 -> 13.34 wick. Kraken hour
  20:00 = $2.8M notional / 3,769 prints vs $0.1–0.3M normal hours.
- OKX 21:02–21:05: short liquidations 13.21 -> 13.34 (squeeze). 21:13: a
  2,946.9-contract LONG liquidation at 13.088; 21:30 another long liq at 12.914.
  Price 12.91 by 21:30, 13.00 at 21:45. ~40% of the impulse given back from top.
- Coinbase taker-buy share during the 12.77 -> 13.11 leg: 0.31 (sellers hit into
  it); Kraken 0.6–0.9. Mixed aggression, not one-sided buying.
- Hyperliquid LINK-PERP: funding 11% APR (08-30) -> 40% APR (last 6h); OI
  $64M -> $92M (+43% in 7d). Crowding rising.
- TAO-PERP: funding 108% APR last bucket, OI +48% 7d. NEAR-PERP: funding
  bursts to 29–53% APR. ZEC: 12–19% APR, OI $483M -> $708M.

## 3. Event study (Kraken 1h, 30d cap, 11 mapped symbols, n=16)

After a >=+4% single 1h close: +4h median -0.54% (38% win), +12h -0.14%,
+24h +0.69% (56%), +72h -1.05%; next-24h MAE median -4.9%, MFE +4.95%.
LINK's own three events (08-15/19/21): 4h fwd -3.2/-0.6/-2.3%. SMALL SAMPLE —
directional read only: chasing the candle is negative in the first 4–12h.
Consistent with STRATEGY-PACK's S2 pullback design over S1 chase.
Mapping gap: ZEC/TIA/DOT/ADA/SUI/FIL/ALGO/HBAR/POL are archived but have no
Kraken pair mapping in `mae/_data/kraken.py` — the funnel cannot see 9/25.

## 4. What the funnel saw (`tk hud --equity 500`, 8 symbols, S1 4h leg)

| sym | macd_hist | vol ratio | S1 |
|---|---|---|---|
| LINK | +0.045 | 1.16 | FAIL vol (spike is in the OPEN 20:00 4h bar) |
| ETH | +1.48 | 0.76 | FAIL |
| SOL | +0.35 | 1.07 | FAIL |
| NEAR | +0.02 | 1.38 | FAIL |
| TAO | +3.21 | 4.99 | PASS, regime PASS -> 1 match |
| AVAX | +0.01 | 0.71 | FAIL |

Result: 0 advisory tickets. TAO's match died at the scan-time policy preview:
`R-010: insufficient_context:thesis_review_artifact_id vs None; R-012:
insufficient_context:recorded_sizing_usd vs None`.

**BLOCKER (known since 2026-07-23, still open):** `hud._build.build_state`
evaluates policy against an `interim-thesis-*` id (no ledgered thesis), so
R-010/R-012 fail-close, `decision.allowed` is False, no ticket is appended.
`cadence.run_once` enters ONLY from `state.tickets` -> the paper cadence can
never open a position. The cadence task was also never registered (ROADMAP
line 273 unchecked; docs/digest/ does not exist). Paper record: 0 trades in
series 8, 1 graded ever. The 30-trade ladder has not started.

## 5. Sizing (mae.size_position, $500 paper, 1% risk, 2xATR14 stop, 2R)

| sym | px | ATR14 | stop dist | size | units |
|---|---|---|---|---|---|
| LINK | 12.05 | 0.60 | 1.20 (10.0%) | $50.07 | 4.16 |
| TAO | 236.1 | 14.2 | 28.4 (12.0%) | $41.55 | 0.176 |
| NEAR | 2.19 | 0.141 | 0.282 (12.9%) | $38.90 | 17.7 |
| ETH | 2480.6 | 95.5 | 190.9 (7.7%) | $64.96 | 0.026 |

R-005 paper cap = 10% of equity = $50; ETH would be clipped to $50.

## 6. Paper trade plans (all paper:alpha, all through the funnel)

**P1 — TAO/USD S1 momentum (the trade the system actually wanted tonight).**
4h close 268.02 with vol 4.99x, MACD hist +3.21, regime pass. Bracket per
sizing: entry ~268 (limit at/below 4h close), stop 239.6 (2xATR), target 324.8
(2R), size $41.55, risk $5, horizon 168h. Overlay caveat (NOT a veto — the
paper record exists to grade S1 as designed): 108% APR funding + a +14% day
= this is the event-study "chase" case. Take it, grade it.

**P2 — LINK/USD S2 pullback-continuation (do NOT chase 13+).**
Arm when 4h stays above EMA50 with MACD bullish AND 1h RSI(14) re-enters
35–50. Expected zone 12.2–12.6 (pre-spike shelf 12.32–12.43; 09-04/05 highs
12.16/12.24 = breakout retest). Bracket at a 12.50 fill: stop 11.30, target
14.90, size $50 (4.0 LINK), risk $5, horizon 168h. Structural invalidation:
daily close < 12.05 (failed 200d breakout) -> void, not stop.

**P3 — NEAR/USD S2 pullback.** Same rule; 30d leader (+52%). Bracket at a
2.30 fill: stop 2.02, target 2.86, size $38.90, risk $5. Watch funding bursts.

Not doing: shorting the LINK spike (trend up, squeeze proven at 21:02);
buying LINK above 13; any live trade (T1, live disabled, LINK not on
`allowed_assets_live`). Mike's "$50 to lose" answer: no — the ladder is the
product; the $50 is the probation stake AFTER a clean 30-trade paper series.

## 7. Actions (order matters)

1. tk-implement batch: fix the scan-preview fail-close (R-010/R-012 should
   report `deferred` at preview for interim theses, binding chain unchanged)
   OR draft the ledgered thesis before preview. policy/ touch -> review round.
2. Register "TradeKit Paper Cadence" (Mike's hands; command in
   scripts/run_cadence.py header). Verify LastTaskResult 0, not "Ready".
3. Add Kraken pair mappings for the 9 archived-but-unmapped pairs.
4. Then P1–P3 flow through the cadence on their own bars; grade, don't touch.
