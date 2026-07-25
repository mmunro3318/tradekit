# Thesis adversarial-review rubric — v1

> **RATIFIED 2026-07-25** (Mike answered the open questions; CTO adjudicated —
> see "Adjudication" section at bottom). Originally written by the SPRINT P3
> batch D TDD pass to give `tradekit.review._rubric` something concrete to
> score against and to give `run_review`'s attack/defense prompt something
> concrete to cite. DESIGN §12.1 is the binding mechanics doc; this file is
> the CONTENT the mechanics run over. One pending migration: the wound
> severity scale (see Adjudication #2) — until that batch lands, `_rubric.py`
> continues to pin int 1..5 and this schema block remains the live contract.

## Purpose

`run_review(thesis_id)` sends a reviewer model (Codex CLI default, Gemini
alt — never an Anthropic model, TD-21) an **attack** prompt built from the
thesis contract + market snapshot + MAE context. The reviewer returns a
structured JSON list of attacks; the proposer (the same session that drafted
the thesis) defends each one; the reviewer scores the exchange against the
categories below. `tradekit.review._rubric.score_exchanges` then tallies
those scores **deterministically in Python** — the model argues, the code
decides (§12.1).

## Exchange JSON schema (pinned by `_rubric.py`, DRAFT)

```json
{
  "attack": "string — the specific criticism",
  "category": "one of the five category ids below",
  "severity": "int 1..5 (1 = minor nitpick, 5 = thesis-killing)",
  "defense": "string — proposer's structured rebuttal",
  "resolved": "bool — the REVIEWER's own verdict on the rebuttal, not the proposer's"
}
```

## Rubric categories (v1 draft)

| id | what it checks | example attack |
|---|---|---|
| `catalyst_falsifiability` | Is the stated catalyst something that can actually be proven wrong before `horizon_end`, or is it vibes ("momentum feels strong")? | "Your rationale never states what observation would prove this wrong before Friday." |
| `ev_arithmetic` | Does `ev_block.ev_usd` actually equal `p_win * reward_usd - (1 - p_win) * risk_usd` within rounding, and is `p_win` defensible (not just asserted)? | "p_win=0.55 with no base-rate citation — where does 55% come from?" |
| `invalidation_distinctness` | Is `invalidation` (structural, F1) meaningfully different from `stop_price` (a price level), or is it just the stop restated in prose? | "Your structural invalidation is 'price falls below $57k' — that's the stop, not a structural break." |
| `sizing_discipline` | Does `size_usd` trace to `mae.size_position`'s actual output (the `SizingComputed` event), with no discretionary bump? | "Sized at $30 but SizingComputed recorded $25 — where did the extra $5 come from?" |
| `correlation_awareness` | If this position correlates with existing open positions (R-013), does the rationale acknowledge the combined risk? | "You already hold ETH/USD long; this BTC/USD long is 0.8-correlated per the snapshot — portfolio risk is understated." |

Severity 4-5 in any category that ends `resolved: false` is the class of
attack `unresolved_attack_threshold` (default 1, `config.toml`) is meant to
catch — a single unresolved fatal attack blocks approval outright.

## Void sign-off variant (`verify_claim`, kind="void_signoff")

Same five categories do not apply — the void-signoff prompt kit instead
asks the reviewer a single yes/no question: "does the attested structural
invalidation ({{attestation}}) actually describe a structural break in the
thesis's catalyst, not a garden-variety price move that the stop already
covers?" One exchange, `category: "invalidation_distinctness"` reused,
`resolved: true` on a genuine structural break. `verify_claim` treats a
single unresolved attack (severity >= threshold) as a refusal, same
tally path as `run_review`.

## Adjudication (2026-07-25, CTO — Mike's answers preserved verbatim below)

1. **Categories: keep all five, unchanged.** Mike's answer pins a scope rule,
   not a category merge: his core portfolio and the engine's prop/AI account
   run on permanently separate theses (his 10yr blockchain-as-AI-infra thesis
   vs the engine's market-behavior/statistical edges). Therefore
   `correlation_awareness` is scoped to the ENGINE'S OWN open positions only
   (the R-013 snapshot) — reviewer attacks citing Mike's personal holdings are
   out of rubric scope by definition. `correlation_awareness` is NOT folded
   into a "portfolio context" category; there is no shared portfolio context
   to fold it into.

2. **Wound scale ADOPTED (minor/major/fatal), migration pending.** Severity
   becomes the enum `"minor" | "major" | "fatal"`; `fatal` replaces the old
   "severity >= 4" blocking class everywhere the tally logic reads severity.
   Mapping for any historical exchanges: 1-2→minor, 3→major, 4-5→fatal.
   This changes the exchange JSON schema pinned by `_rubric.py`, so it lands
   as a proper spec'd batch (red→green→gate→review), not a doc edit. Until
   that batch merges, the int 1..5 schema above stays live.

3. **Threshold dial change ABORTED (Mike, 2026-07-25).** Mike's earlier
   impulse to raise `unresolved_attack_threshold` to 2 was, per his own
   follow-up, based on feeling rather than data — the change is withdrawn.
   `unresolved_attack_threshold` stays at its default of 1: a single
   unresolved fatal attack blocks approval. The two ideas inside the original
   answer — per-category thresholds, and a "resolve-pass on unresolved
   attacks when no other thesis stands" fallback — are PARKED as candidates,
   to be revisited only with live review data showing the flat threshold
   misbehaving. No policy dial moves; the policy hash is untouched.

## Original open questions & Mike's answers (historical record)

1. Category list/order — is five the right number, or should
   `correlation_awareness` be folded into a general "portfolio context"
   category?
> [MIKE] Let's keep my core portfolio, and this prop account (or AI's trading account)  separate, because we'll always trade on different theseis (i had the tradekit engine on market behavior and statistical laws, and i stick to my 10+ long-horizon thesis on blackchain as AI infrastructure, and I've been right.)
2. Severity scale — 1-5 chosen to match `RuleHit`-adjacent conventions
   elsewhere in the codebase; a 3-point scale (minor/major/fatal) might be
   easier for a reviewer model to apply consistently.
> [MIKE] I agree -- I really like the wound scale (minor/major/fatal) and would like to adopt it into our workflow, if it would be easy. . 
3. Should `unresolved_attack_threshold` be per-category (e.g. any single
   `ev_arithmetic` severity-5 blocks regardless of other categories) rather
   than the current flat count across all categories?
> [MIKE] Hmmm... My impulse is to say "yes" -- leave the unresolved_attack_threshold to be at least two categories to block. Perhaps we raise the threshold to two, so two unresolveeds are definitely fata... but we have to try. I think if no other theses are standing, we then do a quick pass for the unresolved theses, and spend extra time on analysis to resolve them (why not, there's no other good trades wiith in our ystem.)