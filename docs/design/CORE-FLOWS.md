# CORE-FLOWS — the codified user flows of tradekit

> STATUS: **RATIFIED 2026-07-24 (Mike)** — §8 open questions remain open for
> the next sit-down; flows and taxonomy are canon. This document is the
> source of truth for WHICH user flows exist, what happens behind each one,
> where the user-facing gates are, and — critically — **what the user learns
> when a step fails**. Every flow here is a contract the meta test suite
> (tests/flows/, see ENGINEERING-CANON) must protect. A flow not listed here
> is not protected; when we discover one, it gets added HERE first, then
> tested. Reevaluated every sprint (see §6).
>
> Provenance: drafted the morning after the first live trade attempt
> (2026-07-23, dev-log), which traversed F1-F5 for real and surfaced three
> previously-unmapped unhappy paths. Those scars are codified below.

## 0. The actors and the spine

One human operator (Mike) + the toolkit + a venue (Kraken Prop, manual
mobile-only entry). tradekit **never places orders**; it advises, gates, and
remembers. The spine every flow hangs off:

```
scan → report/ticket → [human executes at venue] → Confirm (binding chain)
     → fill recorded → thesis active → graded → ledger forever
```

Design rule inherited from tonight: **every arrow above is a seam, and every
seam must (a) fail loud, (b) tell the user what it knows, (c) be walkable by
a flow test without mocking tradekit internals.**

---

## 1. F1 — Daily scan & decide

**Trigger:** Mike runs `tk hud --equity N --serve` (≤2x/day, after 4h closes).

**Behind the scenes (stages/transitions):**
1. bar fetch per symbol (provider → `mae._runtime.get_closed_bars`)
2. open-position check (ledger projection)
3. data-integrity gate (≥20 closed bars)
4. setup scan (`scan_markets`: macd/volume filters + regime gate)
5. sizing (`mae.size_position`, ATR/quarter-Kelly)
6. preview policy verdict (`policy.evaluate`)
7. render: per-symbol gate table + 0..n ticket tabs

**User-facing gates & what reaches the user:**
| Gate | On pass | On fail — what Mike must learn |
|---|---|---|
| data_integrity | silent | symbol row: reason (bar count / provider error) — WORKS today |
| setup | silent | **TODAY: only "no surviving setup" — attrition-blind. TICKET-001 fixes: per-filter kill + killer-filter summary + scan log** |
| sizing | qty shown | reason (zero qty / ATR insufficient) |
| policy (preview) | ticket renders | rule id + measured-vs-limit — but see BUG: preview always refuses on fresh thesis (R-010/R-012), TICKET-001 §out-of-scope |
| **zero tickets at all** | — | **The report must self-answer "why not?" — a silent all-wait day must be distinguishable from a broken scanner. This is the flow-level lesson of the macd bug.** |

**Flow-test status:** ZERO end-to-end coverage on the real config (audit
finding — the only real-scanner E2E uses a disjoint filter set). Meta-suite
test M-F1: real `_SETUP_FILTERS`, synthetic bars engineered to pass, assert a
ticket forms; and the inverse: bars engineered to fail each filter, assert the
report names that filter.

---

## 2. F2 — Ticket → venue execution → Confirm (the money seam)

**Trigger:** a ticket tab exists and Mike decides to act.

**Behind the scenes:**
1. Mike transcribes ticket fields into the venue (MOBILE app; Desktop is
   banned for entry as of tonight; **plain limit + manual exits — venue has
   no working bracket flow; OPERATIONS.md step 3 must be rewritten**)
2. Mike clicks **Confirm** → POST /ack →
3. binding chain (all-real): thesis.draft → submit (snapshot + SizingComputed)
   → human-confirm-as-review → approve → **fresh policy.evaluate** →
   AdvisoryTicketAcked(confirmed)
4. 204 on allow; **409 on refuse** (thesis/verdict untouched on Failed path)

**User-facing gates & fail information:**
| Event | What Mike must learn (contract) | Today |
|---|---|---|
| Confirm accepted | visible, unmistakable success state + thesis id | **BROKEN: silent (tiny status span). Mike clicked repeatedly → double-booked acks. Needs: loud state change + button disable + idempotency (server dedupe by verdict_preview_id)** |
| Confirm → 409 | STOP instruction + which rule refused (measured vs limit) | text exists but same invisible span |
| Failed clicked | "failure booked, nothing else happened" | same silence |
| double-click | second click is a no-op, said out loud | **not idempotent — booked twice tonight** |

**Sub-flow F2b — wrong-venue-account (LIVED tonight):** Mike submitted on the
spot account instead of Prop. tradekit cannot see venue accounts (no advisory
balance feed) — so the CONTRACT is: the ticket tab must carry a prominent
"account: Kraken PROP" line (render-level, cheap) and OPERATIONS mobile
checklist step 1 = verify account switcher. Detection stays human; the flow
doc's job is to make the human check explicit.

**Flow-test status:** rehearsal script covers happy Confirm with seamed
policy; day-5 dry-run covered it with real binding policy on temp ledger.
Meta-suite M-F2: temp-ledger serve → Confirm → assert chain + 204; M-F2b:
double-POST /ack → assert ONE ack (goes red until idempotency fix); M-F2c:
409 path → assert refusal reason reaches the response body.

---

## 3. F3 — Fill → activation → grading (the memory seam)

**Trigger:** venue reports the entry filled; Mike runs `tk fill …` verbatim.

**Behind the scenes:** FillRecorded(actor="mike") → thesis activation seam →
position projections live → (time passes, 4h closes) → grading vs the
thesis's own machine-checkable predicates → ThesisGraded → series metrics.

**User-facing gates & fail info:**
- `tk fill` rejects malformed/mismatched input loudly (qty/price sanity) — must
  name the field, not stack-trace.
- **Manual-exit duty (new venue truth):** no bracket at venue ⇒ the thesis's
  SL/TP are STANDING HUMAN INSTRUCTIONS. Contract: the fill confirmation
  output must echo "your exits: SL x / TP y — venue holds NO orders for these"
  so the duty transfers explicitly. (Not built; small render addition.)
- First real fill may surface latent projection bugs (seed warning): after
  first live day run `tk ledger verify` + rehearsal — codify as OPERATIONS
  post-trade checklist.

**Flow-test status:** unit-covered (fills, activation, grading separately);
no single test walks fill→active→graded on one thesis. Meta-suite M-F3 does.

---

## 4. F4 — The inactivity backstop (day-5 rule)

**Trigger:** ledger shows no trade in ~5 days on the prop account.

**Behind the scenes:** session model surfaces the day count unprompted
(OPERATIONS duty) → CTO adjudicates minimal manual-thesis trade → full funnel
(never softened) → F2 → F3. Tonight's `scripts/day5_manual_trade.py` is the
canonical tool (seams ONLY scan-preview; binding policy real).

**Fail info contract:** if the funnel REFUSES the backstop trade (policy
deny), that is a fail-closed success — the user learns which rule and takes it
to adjudication; the account expiring is preferable to a bypassed gate.

**Flow-test status:** dry-run proved it once, manually. Meta-suite M-F4:
scripted temp-ledger version of the day-5 path (the script minus the human).

---

## 5. F5 — Trust-but-verify (the operator's confidence flow)

**Trigger:** any session start, any post-change moment, "is it actually working?"

**Stages:** tk-gate → rehearsal script → `tk ledger verify` → collector check
(`data/ticks/<pair>/<today>/`) → day-count check. This IS a user flow — the
product's real deliverable is *justified confidence*, and tonight showed its
gaps (green gate + healthy collector + broken scanner coexisted).

**Contract additions from tonight:** the verification flow must include ONE
un-mocked scan-path probe (post-TICKET-001: the attrition log's summary line
is exactly this — "killer filter: X" vs "tickets: n" tells broken from quiet).

---

## 6. Sprint ritual — flow review (canonized)

At the end of every sprint / large batch:
1. **Touched-flow check:** for each flow whose code was touched — do the
   stages, gates, and fail-info contracts above still hold? Update THIS doc in
   the same PR (doc inventory rule: change isn't done otherwise).
2. **Discovery attempt:** name at least one candidate flow or unhappy path not
   yet codified (tonight yielded three in one evening: wrong-account,
   no-bracket venue, silent-button). Add it here + a meta-suite stub.
3. **Interface-drift pass:** for touched modules only — does the module's
   public verb set still match its docstring contract? (Feeds the
   ENGINEERING-CANON interface-review ritual.)

## 7. Unhappy-path taxonomy (v1 — grow it)

Every flow must enumerate its rows against these classes:
- **U1 wrong-context action** (right action, wrong account/venue/mode) — F2b
- **U2 silent state change** (action succeeded/failed with no signal) — Confirm bug
- **U3 repeated action** (impatient retry; idempotency) — double-ack
- **U4 refused-by-design** (policy 409; venue rejection) — must carry reason
- **U5 abandoned mid-flow** (ticket never confirmed; fill never recorded —
  what does the ledger believe? stale-ticket TTL question → CTO to adjudicate)
- **U6 upstream silence** (provider down, collector stopped, scanner
  structurally mute) — the macd class; distinguishable-from-quiet is the bar

## 8. Open questions for the Mike sit-down

1. F2 ticket rendering for the bracket-less venue: keep TP/SL as "manual
   instructions" panel (my lean) or drop OSO fields entirely?
2. U5: should an unconfirmed ticket expire (TTL) with a ledger note, or is
   scan-refresh overwrite enough?
3. LLM-operator rehearsal (research memo pending): green-light a v1 that
   drives the real serve loop on a temp ledger with stochastic operator
   behavior (impatient double-clicks, wrong-field transcription)?
4. Which flows are BLOCKING for ship vs advisory (M-F1/M-F2 feel blocking;
   M-F4 maybe not)?
