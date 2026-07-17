# Mike's primer — what we just built (P2: the thesis contract and the gates)

> Plain-English explainer, written 2026-07-17 at the close of sprint P2. This
> is the sprint that stands between an AI and your money. Six minutes' read.

## What a "thesis contract" is

Before this sprint, the system could *find* setups. Now, nothing can be
traded — ever — without first being written down as a **thesis contract**: a
falsifiable, machine-checkable prediction, locked before the fact.

A thesis says, in structured form: *"I want to go long ETH at $1,900 because
X. I'm right if price touches $2,100 by August 15. I'm wrong if it closes
below $1,780. My model says this is worth risking $12."* Every number is
snapped to the exchange's price grid, the expected-value arithmetic is
recomputed and must check out to the cent, and the market conditions at
submission are snapshotted. After submission the contract is **immutable** —
no editing the prediction after seeing how it went. Changing your mind means
a new thesis, visibly linked to the old one.

Why so rigid? Because vague predictions are ungradeable, and ungradeable
predictions let a storyteller (human or AI) claim credit in hindsight. A
thesis either hit its number or it didn't. The grading is pure arithmetic
over price bars — and where a bar is ambiguous (it touched both your target
AND your stop), the rule is pinned: **the stop wins**. Every ambiguity in
this system resolves against the trader, never for them.

## The escape hatch we welded mostly shut

The classic way to fake a track record is the VOID: "that loser doesn't
count, the situation changed." An agent that voids its losers has a perfect
win rate. So voiding now requires three things: the thesis must have declared
an *invalidation condition* up front; if that condition is measurable, the
math decides — no discretion at all; if it's structural (a judgment call), it
needs a written attestation **plus** an independent reviewer's sign-off, and
a refused void leaves a permanent audit trail. On top of that, if more than
20% of recent grades are voids, the system stops accepting new theses
entirely until a process review happens.

## The sixteen gates

Every action that could touch money now passes through a policy engine —
sixteen rules, each with a plain-English WHY, each deterministic, each
leaving a ledger record when it says no. A few favorites:

- **R-008** blocks trades under $10 — you can't manufacture a good-looking
  track record out of a hundred fee-sized micro-trades.
- **R-012** compares your order size against what the sizing model computed
  *at submission time* — "I'm down, let me bet double to get it back" is
  rejected by arithmetic, not willpower.
- **R-009** freezes new positions when the account is down 10% from its
  30-day peak — losing streaks are when compounding mistakes feels most
  tempting.
- **R-001** is the kill switch: one command halts everything until you clear it.

The full catalog with every WHY is in `rules/RULES.md` — **it's generated
from the code**, so the documentation can never quietly drift from what's
enforced. This is the part I need you to read and sign off on.

## How an AI earns the right to trade real money

Promotion is a ladder with no shortcuts: research → paper trading → a
three-trade live probation. To climb, an account needs **clean 30-day
series**: fixed calendar windows (nothing to cherry-pick), at least ten
graded theses each, zero gate violations, positive expectancy after fees,
and drawdown under 15%. Three of the last four series clean, plus a
statistical edge test that treats "maybe lucky" as "not proven." And the
final step is not automatic: the machine can only *grant* eligibility — a
human (you) must confirm it. Two keys, like a launch console.

This sprint's proudest artifact is the **adversarial test suite**: eleven
scenarios where we play a cheating AI — farming voids, spraying micro-trades,
revenge-sizing, trading through a halt, citing a thesis that never existed —
and prove every scheme dies at a gate, with the denial written to the
tamper-evident ledger. The review round still found one real hole before
sign-off (a subtle accounting bug that let one account's wins hide another's
drawdown), which is exactly why every layer gets attacked before it ships.

## Infographic prompts (paste into Microsoft 365 Copilot)

1. *"Create an infographic titled 'A Trade Idea's Journey'. A pipeline with
   six stations: Draft (a written, falsifiable prediction), Submit (numbers
   locked + market snapshot), Review (independent challenge), Approve, Active
   (live in the market), Grade (arithmetic verdict: PASS or FAIL). A padlock
   icon after Submit labeled 'immutable — no rewriting predictions'. A side
   door labeled VOID with three locks: 'declared upfront', 'attested',
   'reviewer signed'. Clean pipeline diagram, blue/slate."*

2. *"Create an infographic titled '16 Gates Between an AI and Real Money'.
   A castle wall with 16 numbered gates; call out five with icons: kill
   switch (R-001), no micro-trades under $10 (R-008), drawdown freeze at 10%
   (R-009), size must match the model (R-012), void-rate cap 20% (R-015).
   Banner: 'Every NO is written to a tamper-evident ledger.' Fortress
   illustration style."*

3. *"Create a diagram titled 'Earning Live Money: The Promotion Ladder'.
   Three rungs: Research → Paper Trading → Live (3-trade probation). Between
   Paper and Live, a checklist gate: '3 of last 4 months clean · 10+ graded
   predictions each · zero rule violations · profitable after fees ·
   drawdown under 15% · statistical edge proven'. At the top, two keys
   turning together labeled 'machine grants, human confirms'. Ladder
   illustration, green ascending."*
