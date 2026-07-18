# Mike's primer — what we just built (P3: the paper-trading floor)

> Plain-English explainer, written at the close of sprint P3. The machine can
> now run the ENTIRE loop end-to-end — find, propose, review, gate, trade
> (on paper), grade, report — with zero real dollars at risk. Five minutes.

## What a "broker port" is, and why ours is paranoid

A broker port is the single narrow doorway through which any order reaches
any venue — paper simulator now, Alpaca later. Five functions, nothing more,
and the door has a lock: **an order without a policy verdict token is
physically unsubmittable.** The token isn't a password — it's a receipt
proving the sixteen gates said yes, for *this specific thesis*, and that no
later ruling said no. A token minted for one thesis can't be reused for
another; a stale approval superseded by a denial stops working. The review
round even tried to forge and replay tokens — every path died.

## Why paper fills are simulated pessimistically

Paper trading is only worth anything if it can't lie to you. Three rules:

1. **Every simulated fill pays real-world friction** — the same fee and
   spread tables the backtester and the promotion gates use. One source of
   truth means paper results and gate math can never disagree about costs.
2. **Limit orders don't fill on a touch.** Real retail limit orders often
   sit unexecuted when price merely kisses your level; ours require price to
   trade *through* by a full tick. Pessimism here means paper profits are
   believable.
3. **Every fill carries its receipt** — the exact market snapshot it was
   priced from, stored forever. And fills are deterministic: replay the
   ledger, get byte-identical results.

One honest caveat, recorded in the design doc itself: our simulator is
optimistic about liquidity (no partial fills, no queue). At $25-notional
sizes on liquid symbols, that's negligible — and it's flagged for revisit
before any size increase.

## What reconciliation catches

Reconciliation is the "trust but verify" sweep: compare what the broker says
happened against what our ledger says happened — **in both directions**. A
broker fill our ledger doesn't know about means something traded out-of-band
(stolen key, manual click) → automatic full halt. A ledger fill the broker
never saw means our records claim a trade that didn't happen → same halt.
And the halt is real: this sprint's review round found that a resting limit
order could still fill *after* a halt through the status-polling path —
that hole is now welded shut and pinned by tests.

## The adversarial reviewer

Before any thesis can be approved, it now faces a hostile reviewer — a
*different* AI (Codex or Gemini, not me) that attacks the idea in structured
rounds while the scoring stays deterministic Python (no vibes). Three
auto-fails cost zero tokens: no numeric expected value, no falsifiable
prediction, size that doesn't match the sizing model. And the VOID escape
hatch now requires this reviewer's actual signed verdict — this sprint we
even caught a latent bug where a *failed* review sign-off would have been
accepted; the tests now prove a failed sign-off keeps the void refused.

Your only homework from this sprint: the reviewer's attack rubric is a
draft at `prompts/rubric-thesis-v1.md` — read it and tell me what a hostile
reviewer should press hardest on.

## What's left: P4, the live proof

Everything from here pairs with you: rotate both API keys (they passed
through chat), create Alpaca live keys, fund $50–100. Then: dress rehearsal
through Alpaca's paper API, a real readiness report, your two-key promotion
confirmation, exactly three small live trades with reconciliation after
each, and an independent verification of the results against broker records.
That's the MVP finish line.

## Infographic prompts (paste into Microsoft 365 Copilot)

1. *"Infographic titled 'One Door to the Market'. A vault door labeled
   'Broker Port' with five small windows (account, positions, submit,
   status, fills). The submit window has a keycard slot labeled 'policy
   verdict token — minted per-thesis, expires on any later denial'. Around
   the vault, arrows bouncing off labeled: 'no token', 'wrong thesis',
   'stale approval'. Bank-vault illustration style."*

2. *"Infographic titled 'Paper Trading That Can't Flatter You'. Three
   panels: (1) a price bar kissing a limit line labeled 'touch ≠ fill —
   must trade through'; (2) a receipt stapled to a trade labeled 'every
   fill stores the market snapshot it was priced from'; (3) two ledgers
   side-by-side with a magnifying glass labeled 'reconciled both ways —
   any mismatch halts everything'. Clean flat design."*

3. *"Infographic titled 'Every Trade Idea Meets a Hostile Reviewer'. A
   boxing ring: in one corner 'The Thesis', in the other 'Adversarial AI
   Reviewer (a different model)'. Referee labeled 'Deterministic scoring —
   Python, not vibes'. Three knockout cards on the mat: 'no numbers',
   'nothing falsifiable', 'size ≠ model'. Caption: 'Unresolved attacks
   block approval.'"*
