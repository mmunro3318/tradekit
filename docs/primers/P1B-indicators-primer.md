# Mike's primer — what we just built (P1B: the indicator library)

> Plain-English explainer, written 2026-07-15 at the close of sprint P1B.
> No action needed from you. Five minutes' read.

## What an "indicator" is

Raw market data is just a stream of candles: for each hour (or day), the
open, high, low, close price and the volume traded. An **indicator** is a
small formula that turns that stream into one number per candle that answers
a specific question:

- **"How violently is this thing moving?"** → ATR (Average True Range).
  If ETH's ATR on the daily chart is $120, a typical day's range is about
  $120. We size positions off this: bigger swings → smaller position, so a
  normal wiggle can't hurt you more than you agreed to risk.
- **"Is it overstretched?"** → RSI. Runs 0-100. Near 80 after a straight-up
  week on SOL means late-to-the-party risk; near 25 means the selling may be
  exhausted. It's a thermometer, not a crystal ball.
- **"Is there an actual trend, or just chop?"** → ADX, moving averages,
  Supertrend. MU grinding above its rising 20-day average with ADX at 30 is
  a trend; NEAR whipsawing across a flat average with ADX at 12 is noise.
- **"Is the crowd paying fair price?"** → VWAP, the volume-weighted average
  price paid today. Institutions benchmark against it; price sitting above
  VWAP all session means buyers kept paying up.
- **"Where are the floors?"** → swing lows and QFL bases: prices where
  buyers showed up before. If AMD bounced hard off $150 twice, $150 is a
  level; if it *cracks*, that tells you something too.

That's the whole library: 17 of these formulas, each answering one question.
Nothing here predicts anything by itself — indicators describe the present
precisely so the strategy layer (next sprints) can make rules like "only
take longs when the trend filter and the volatility filter both agree."

## What an "edge" is (and why we're this paranoid about arithmetic)

An **edge** is any repeatable rule whose wins, minus its losses, minus fees
and slippage, comes out positive over many trades. Not a hunch — a measured,
repeatable tilt in your favor. Casinos run on a 1-5% edge and grind out
fortunes; we're hunting for the same shape of thing in markets, and the
default assumption (per our own metrics gates from M1.3) is that any edge we
think we've found is FAKE until ~30+ trades of evidence say otherwise.

Here's the trap this sprint existed to prevent: every strategy we'll ever
test is built out of these indicator numbers. If RSI is computed *slightly*
wrong — and the classic bug is being off by one bar in the "warm-up"
averaging, which produces numbers that LOOK completely plausible — then
every backtest built on it is quietly testing a different strategy than the
one we'd trade live. You'd "discover" edges that don't exist.

So every indicator was locked to **golden vectors**: frozen test files where
the expected numbers were computed twice, by two separately-written
implementations, and cross-checked against TA-Lib (the 25-year-old industry
reference library) before any real code existed. The code must reproduce
those numbers forever, to nine decimal places. This paranoia paid for itself
within hours: one implementation bug of exactly the classic seed-window
class was caught by the frozen numbers the same afternoon it was written.

## Swing trading vs day trading (where we sit)

- **Day trading**: in and out within hours, dozens of decisions a day,
  competing on speed against machines. High stress, high friction (every
  trade pays fees + spread), and the venue's cut compounds brutally at our
  account size. Not our game.
- **Swing trading**: hold for days to weeks, riding one identified move —
  say, LINK reclaiming its 50-day average after a base holds, targeting the
  prior high. A handful of decisions a week, made calmly against a
  checklist, with time to be wrong slowly. Fees matter less because you
  trade less. **This is what tradekit is being built for.**

The indicator timeframes we default to (1-hour and daily candles), the
session-anchored VWAP, and the ATR-based sizing all assume swing horizons.
Nothing stops shorter-term experiments later, but the machine is being built
to make a few careful decisions, not many fast ones.

## Where this fits

Done so far: contracts + tamper-evident ledger (P0) → market data feeds with
caching and rate limits (P1A) → **indicators (P1B, this sprint)** → metrics
that judge whether results are luck or skill (M1.3, done early).
Next (P1C): the regime detector (is the whole market in risk-on or risk-off
mode?), the scanner that sweeps your universe (ETH/SOL/LINK/NEAR/TAO/EIGEN,
MU/AMD/MRVL, SPY/IWM/DIA) through these indicators, and position sizing.

## Infographic prompts (paste into Microsoft 365 Copilot)

1. *"Create a clean one-page infographic titled 'What Trading Indicators
   Actually Do'. Show a candlestick chart at the top labeled 'raw price
   data', with four arrows flowing down to four labeled boxes: 'ATR — how
   big are the waves?', 'RSI — is it overstretched?', 'Moving averages +
   ADX — is there a real trend?', 'VWAP — what did the crowd actually pay?'.
   Bottom banner: 'Indicators describe the present. Strategy rules decide
   the future.' Modern flat design, blue/slate palette."*

2. *"Create an infographic comparing swing trading and day trading as two
   columns. Swing trading: holds days-to-weeks, a few calm decisions per
   week, lower fees, works at small account sizes. Day trading: holds
   minutes-to-hours, dozens of rushed decisions daily, fees and spreads
   compound, competes with machines on speed. Highlight the swing column
   with a green 'our approach' badge. Simple icons, two-column layout."*

3. *"Create a diagram titled 'Why We Freeze the Math'. Step 1: two
   independent implementations compute the same indicator. Step 2: results
   cross-checked against the industry reference (TA-Lib). Step 3: numbers
   frozen as 'golden vectors'. Step 4: all future code must match them to 9
   decimal places, forever. Side caption: 'A slightly-wrong formula makes
   every backtest a lie — fake edges get discovered, real money gets lost.'
   Flowchart style, four steps left to right, warning-triangle icon on the
   caption."*
