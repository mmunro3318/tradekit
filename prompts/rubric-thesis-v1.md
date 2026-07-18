# Thesis adversarial-review rubric — v1

> **DRAFT for Mike's approval.** Written by the SPRINT P3 batch D TDD pass
> to give `tradekit.review._rubric` something concrete to score against and
> to give `run_review`'s attack/defense prompt something concrete to cite.
> Nothing below is final: category list, wording, and severity scale are
> all open to Mike's edit (sprint doc addendum: "rubric-thesis-v1.md shape
> — draft for his edit"). DESIGN §12.1 is the binding mechanics doc; this
> file is the CONTENT the mechanics run over.

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

## Open questions for Mike

1. Category list/order — is five the right number, or should
   `correlation_awareness` be folded into a general "portfolio context"
   category?
2. Severity scale — 1-5 chosen to match `RuleHit`-adjacent conventions
   elsewhere in the codebase; a 3-point scale (minor/major/fatal) might be
   easier for a reviewer model to apply consistently.
3. Should `unresolved_attack_threshold` be per-category (e.g. any single
   `ev_arithmetic` severity-5 blocks regardless of other categories) rather
   than the current flat count across all categories?
