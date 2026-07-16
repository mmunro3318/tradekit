# Mike's primer — what we just built (P1C: regime, sizing, correlation, scanner)

> Plain-English explainer, written 2026-07-17 at the close of sprint P1C.
> This completes Phase 1: the Market Analysis Engine. Five minutes' read.

## What a "regime" is

Markets have weather. The same trade that works in a calm uptrend gets
shredded in a violent chop, and no indicator fixes that — you have to know
which weather you're in before choosing a play. That's regime detection.

Ours works three ways, stacked by trust:

1. **The statistical model (HMM).** We feed it the last ~90 days of returns
   and volatility for a symbol, and it sorts the days into 2–3 "states" —
   calm-trending, choppy, breaking down. It's the same class of model used
   for speech recognition: it doesn't know *why* the market changed moods,
   it just detects that the mood changed. Fitted once a week, saved to disk,
   fully reproducible (same data, same answer, always).
2. **The circuit breaker (EWMA override).** Statistical models can be slow
   to admit the world changed. So on every single call we also run a dumb,
   fast check: is *recent* volatility more than three standard deviations
   above what "calm" looks like? If yes, we ignore the model and answer
   "high-vol chop, recommend nothing." This is the seatbelt. (Fun fact: the
   reviewer caught a bug in exactly this seatbelt this sprint — the
   threshold was accidentally set ~5× too loose. That's why every layer
   gets adversarially reviewed before it ever touches money.)
3. **The fallback rules.** A new listing with 40 days of history can't feed
   an HMM honestly. Below 60 days we use simple explicit rules instead, and
   the answer is clearly labeled as the lower-confidence kind — including a
   "neutral" answer that deliberately recommends *nothing* rather than
   guessing.

## Why sizing beats stock-picking

Here's the uncomfortable truth every professional accepts: you have limited
control over *whether* the next trade wins. You have total control over *how
much it costs you when it loses*. That's position sizing, and it's where
most self-taught traders actually blow up — not bad picks, oversized picks.

Ours computes two numbers and takes the **smaller**:

- **ATR sizing** — "how big can this position be so that a normal bad day
  costs me exactly 1% of my account?" If ETH swings $120/day, the position
  is sized so a two-swing stop-out loses exactly the dollar amount you
  pre-agreed to — never more.
- **Quarter-Kelly** — Kelly's formula computes the mathematically optimal
  bet size from your measured win rate and payoff. Full Kelly is a wild
  ride; we take 25% of it. And if your measured edge is *negative*, Kelly
  goes negative and we clamp the position to **zero** — a strategy that
  loses money gets sized out of existence, automatically.

The signature of this function is deliberately frozen: it takes no account
of your recent wins or losses, so no future code can ever implement "I'm
down, let me bet bigger to get it back." Revenge-sizing is structurally
impossible, not just discouraged.

## What correlation does to a small portfolio

Owning ETH, SOL, and LINK feels like three positions. On a bad crypto day
it's one position, three times — they move together (correlation near 1).
Diversification you *feel* but don't *have* is how a 1%-per-trade risk plan
quietly becomes 3% on the same event.

The new correlation matrix measures this on real overlapping trading days
(crypto trades weekends, stocks don't — we only compare days both traded),
flags any pair moving more than 75% in lockstep, and — importantly —
refuses to output a number when there isn't enough shared history to
measure honestly. "Unmeasured" is reported as unmeasured, never guessed.

## The scanner ties it together

`scan_markets` sweeps your universe (ETH/SOL/LINK/NEAR/TAO/EIGEN, MU/AMD/
MRVL, SPY/IWM/DIA) through the P1B indicators with filters like "RSI under
35" or "volume 3× normal," then applies the regime gate: a setup that looks
great numerically but sits in a hostile regime gets its recommendation
stripped — you see the setup *and* the reason not to take it. We ran it
live against Kraken this week and it returned real, current setups.

**Phase 1 is done.** The machine can now see (data), measure (indicators),
judge conditions (regime), size honestly (Kelly/ATR), and hunt (scanner).
Phase 2 gives it discipline: the thesis contract and the policy engine —
the part that forces every trade idea to be written down, adversarially
reviewed, and graded against its own stated predictions.

## Infographic prompts (paste into Microsoft 365 Copilot)

1. *"Create an infographic titled 'Market Regimes: Trade the Weather, Not
   Just the Forecast'. Three weather-style panels: sunny 'Calm Trend'
   (trend-following strategies OK), stormy 'High-Vol Chop' (mean-reversion
   only, small size), tornado 'Breakdown' (no new positions). Below, a
   two-layer safety diagram: 'Statistical model (weekly)' with a fast
   'Volatility circuit breaker (every call)' overriding it when readings
   spike. Clean flat design, weather icons."*

2. *"Create a one-page infographic titled 'Position Sizing: The Only Thing
   You Fully Control'. Left panel: ATR sizing — a candlestick chart with a
   bracket labeled 'normal daily swing', caption 'size so a stop-out costs
   exactly 1%'. Right panel: Quarter-Kelly — a dial from Full Kelly (red,
   volatile) to Quarter Kelly (green, chosen). Center badge: 'We take the
   SMALLER of the two'. Bottom warning strip: 'Negative edge → size = 0.
   Revenge betting is structurally impossible.'"*

3. *"Create a diagram titled 'Three Coins, One Bet?'. Show ETH, SOL, and
   LINK price lines moving almost identically, with a correlation meter
   reading 0.9 labeled 'moves in lockstep'. Caption: 'High correlation
   means your three 1% risks can become one 3% risk on the same bad day.'
   Side panel: a matrix grid with one cell greyed out labeled 'not enough
   shared history — reported as unmeasured, never guessed'."*
