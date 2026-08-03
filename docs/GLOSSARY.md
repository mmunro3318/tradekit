# GLOSSARY — tradekit's vocabulary source of truth

> STATUS: **RATIFIED 2026-07-24 (Mike).** This file is canon: consult it
> before naming anything that crosses a module boundary (CLAUDE.md
> Conventions). It grows at design time — when a design
> doc coins a cross-module term, the term lands HERE in the same change.
>
> WHY this file exists: on 2026-07-23 we found strategy S1 had silently traded
> nothing for days because `hud/` said `"bullish"` where `mae/_scanner` speaks
> only `"bullish_cross"` — one concept, two names, silent boundary failure
> (docs/tickets/TICKET-001). The academic ancestor of this file is DDD's
> Ubiquitous Language (Evans 2003; Fowler, "UbiquitousLanguage"); the
> "one concept, one name" rule is Deissenboeck & Pizka (2006). Full sourcing:
> docs/research/standards-2026-07/naming-vocab.md.

## How to use this file

- **Schema per term:** Term · Definition · Code form (the ONE canonical
  spelling; enum member where one exists) · Aliases to avoid (banned synonyms).
- **Grouped by module context**, not flat A-Z — bounded contexts legitimately
  let a word mean different things in different modules; a term that IS
  context-local is scoped to its section and cross-referenced under
  ⚠ Ambiguities rather than force-flattened.
- **Enforcement tiers:** (1) shared enums/Literals make drift a mypy/import
  error — preferred wherever a term is a machine value; (2) the "Aliases to
  avoid" column feeds a CI grep gate (planned, ENGINEERING-CANON); (3) "is
  this a new concept or an alias?" stays a review-time human judgment.

## Naming conventions (repo-wide)

- `snake_case` everywhere Python allows it; `UPPER_SNAKE` module constants;
  `PascalCase` classes/contracts (existing repo practice, PEP 8).
- Booleans read as predicates: `is_<state>` / `has_<thing>` / `can_<verb>` /
  `should_<verb>`; plural subjects `are_<state>`. (Convention, not
  evidence-backed — adopted for consistency.)
- Plain attribute access over getter/setter pairs: a pass-through
  `get_x()/set_x()` is banned; reach for `@property` only when behavior hides
  behind the read (Google Python Style Guide ruling; Python's consenting-adults
  doctrine).
- Public module surface = a small set of VERBS on `__init__` (existing deep-
  module convention); events are `NounVerbedPayload` past-tense facts.
- Synonym collapse: each status/state family picks ONE word and lists the
  losers under Aliases to avoid. Don't pre-legislate the whole language —
  collapse a family the first time it appears at a boundary.

---

## scan / mae context

| Term | Definition | Code form | Aliases to avoid |
|---|---|---|---|
| macd signal | direction of the last MACD histogram reading used as a setup filter | `"bullish_cross"` / `"bearish_cross"` (scanner filter value; TICKET-001 will make any other value raise) | ~~bullish~~, ~~bearish~~, ~~macd_up~~ |
| signal tag | strategy-affiliated marker a surviving candidate carries out of the scan | `signal_tags: list[str]`, members like `"macd_bullish"`, `"volume_spike"` | ~~setup_tags~~, ~~signals~~ |
| closed bar | a candle whose interval has completed; the ONLY bar the setup gate may read | `get_closed_bars(...)` | ~~candle~~ (prose ok, not identifiers), ~~finished bar~~ |
| attrition | per-filter count of candidates killed at each scan stage (TICKET-001) | `ScanAttrition*` | ~~funnel loss~~, ~~drop-off~~ |
| ema_above / trend_up | S2 filter: last close strictly > EMA(n) (SMA-seeded); fires tag trend_up (momentum family) — ASSUMPTIONS 174 | `{"ema_above": 50}` -> `"trend_up"` | ~~above ema~~, ~~uptrend~~ |
| rsi_band / pullback | S2 filter: lo <= RSI(14) <= hi inclusive both ends; fires tag pullback (momentum family) — ASSUMPTIONS 174 | `{"rsi_band": [35, 50]}` -> `"pullback"` | ~~rsi range~~ (rsi_max/rsi_min are the open-ended forms) |
| regime | HMM/EWMA market-state classification gating strategy tags | `get_regime`, states incl. `"neutral"` | ~~market mode~~ |

## policy context

| Term | Definition | Code form | Aliases to avoid |
|---|---|---|---|
| action kind | the type of proposed mutation the gate evaluates | `ProposedAction.kind` — to become closed `Literal` (audit H3) | ~~action type~~ |
| verdict | the gate's decision artifact; allow iff every consulted rule passed | `Verdict.allow`, `rule_hits` | ~~decision~~, ~~result~~ |
| rule hit outcome | one rule's finding | `"pass" \| "fail" \| "not_configured"`; `insufficient_context` rides `measured` | ~~status~~ |
| halt | the standing kill switch (R-001) | `HaltSet` / `HaltCleared` | ~~pause~~, ~~freeze~~ |
| principal | the account's configured base capital rules scale against | `principal_usd` | ~~balance~~ (that's settled funds), ~~equity~~ (that's live value) |

## broker / ledger context

| Term | Definition | Code form | Aliases to avoid |
|---|---|---|---|
| fill | an execution reported against a thesis; advisory fills carry `actor="mike"` | `FillRecorded` | ~~execution~~, ~~trade~~ (a trade is the whole round trip) |
| account ref | the namespaced account identity | `"paper:alpha"`, `"advisory:kraken"`, `"live:..."` | ~~account id~~ |
| thesis | the falsifiable, reviewed, machine-gradable trade contract | `ThesisContract` | ~~idea~~, ~~setup~~ (a setup is pre-thesis, scan context) |
| graded | terminal thesis judgment vs its own predicates | `ThesisGraded` | ~~done~~, ~~completed~~, ~~closed~~, ~~finished~~ |
| in-kind fee | fee withheld from the RECEIVED asset of a fill (Alpaca crypto buys: in the crypto; sells: in the USD proceeds) — ASSUMPTIONS 170 | `fee_asset_qty` on `FillRecorded` (asset units; 0 = USD-fee physics) | ~~crypto fee~~, ~~asset fee~~ |
| net held qty | position quantity after in-kind withhold; the ONLY legal sell-sizing input | `positions()[i].qty` = Σ(buy qty − fee_asset_qty) − Σ(sell qty) | ~~filled qty~~ (that's the gross fill) |
| strategy registry | the priority-ordered StrategyDef tuple the funnel walks (first match wins) | `mae.STRATEGIES` / `mae.STRATEGY_BY_KEY` / `mae.StrategyDef` (public via mae only) | ~~registry~~ bare (ambiguous vs tag-family registry) |
| tag-family registry | the signal-tag -> strategy-family seed map | `tradekit.strategies.TAGS` / `FAMILIES` | ~~strategy registry~~ (that is mae._strategies) |
| strategy_key | the StrategyDef key that claimed a symbol in the walk; "" = manual/unclaimed (falsy sentinel) | `_SetupResult.strategy_key`, `AdvisoryTicket.strategy_key`, thesis `strategy_tag` | ~~strategy id~~, ~~def key~~ |
| execute_exit | the gated pipeline verb that flattens an active thesis (mirror of execute_order; NET-qty sell, policy-evaluated) | `broker.execute_exit(thesis_id)` | ~~close~~, ~~sell~~, ~~flatten~~ (bare) |
| exit trigger | the pure WHEN-to-flatten decision (stop/target/horizon, inclusive touches, stop-first) | `cadence.exit_trigger(...)` -> `"stop"\|"target"\|"horizon"\|None` | ~~exit signal~~ |
| wound scale | review-exchange severity enum, rank order minor<major<fatal (never lexicographic) — ASSUMPTIONS 171; legacy ints map 1-2/3/4-5 at the parse boundary only | `WOUND_SCALE = ("minor","major","fatal")`, `severity: "minor"\|"major"\|"fatal"` | ~~1..5~~, ~~severity level~~, ~~critical~~ |

## hud / ops context

| Term | Definition | Code form | Aliases to avoid |
|---|---|---|---|
| ticket | a rendered advisory order the human may transcribe to the venue | `AdvisoryTicket` | ~~order~~ (orders live at the venue/broker layer) |
| confirm | the binding human attestation "I submitted it" — triggers the real chain | `AdvisoryTicketAcked(action="confirmed")` | ~~approve~~ (thesis-lifecycle word), ~~ack~~ alone |
| wait | scan grade: no confirmed setup or a gate refused; do nothing | `"wait"` | ~~skip~~, ~~pass~~ (pass is a gate outcome) |

## ⚠ Ambiguities (same word, different contexts — both legal, know which you're in)

- **approve**: thesis lifecycle verb (`thesis.approve`) vs colloquial "policy
  allowed" — in policy context say *allow*.
- **pass**: rule-hit outcome in policy vs gate display in hud — never use for
  "do nothing" (that's *wait*).
- **equity**: live account value (sizing input) vs `_paper_equity` policy
  balance — these differ today by design (advisory has no balance feed);
  qualify which you mean.
