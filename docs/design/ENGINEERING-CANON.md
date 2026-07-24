# ENGINEERING-CANON — decisions on vocabulary, readability, seams, and behavior testing

> STATUS: **RATIFIED 2026-07-24 (Mike).** Decisions D1-D7 are repo canon. Each carries
> a WHY and its sources. Detailed provenance lives in the four research memos
> under `docs/research/standards-2026-07/` (naming-vocab, readability,
> contract-testing, behavior-flows) — every external claim below is cited
> there; claims the researchers could not re-verify are flagged
> `[UNVERIFIED-RECALL]` in the memos and are NOT load-bearing here.
>
> Instigating incidents (2026-07-23): the macd `"bullish"`/`"bullish_cross"`
> vocabulary-drift bug (silent reject-all, green suite — TICKET-001); the
> policy gate's `all([])` fail-open on unknown action kinds (audit H3); the
> silent, non-idempotent Confirm button. One defect class wearing many masks:
> **unrecognized input coerced into a plausible benign value instead of
> failing loud** (gating-filter-audit closing).

---

## D1 — Vocabulary is governed: GLOSSARY.md + typed enums

**Decision.** `docs/GLOSSARY.md` (seeded, DRAFT) is the source of truth for
cross-module terms: module-grouped, Term/Definition/Code-form/Aliases-to-avoid,
with an explicit Ambiguities section. New cross-module terms land in the
glossary in the same change that coins them (design stage, not cleanup).
**But the doc is the second line of defense — the first is the type system**:
any vocabulary value that crosses a module boundary is a `StrEnum`/`Literal`
both sides import, never a bare `str`.

**Why.** The glossary is DDD's Ubiquitous Language made concrete (Evans 2003;
Fowler, UbiquitousLanguage/BoundedContext); module-grouping respects bounded
contexts instead of flattening them. "One concept, one name" traces to
Deissenboeck & Pizka (2006); the naming→defect link (Butler et al. 2009) is
correlational — stated honestly, not oversold. The macd bug proves prose alone
fails: a shared enum turns tomorrow's drift into an import/mypy error today.

**Enforcement tiers.** (1) enums + mypy (gate already runs mypy); (2) CI grep
gate fed by the Aliases-to-avoid column (build when the glossary stabilizes);
(3) "new concept or alias?" stays human/review judgment.

## D2 — Naming rules (thin, mechanical where possible)

snake_case throughout; booleans as predicates (`is_/has_/can_/should_`,
plural `are_`); no pass-through getter/setter pairs — plain attributes, and
`@property` only when behavior hides behind the read (Google Python Style
Guide; PEP 8). Synonym collapse happens family-by-family at first boundary
contact, recorded in the glossary — we do not pre-legislate the language.
Honesty note: boolean-prefix forms are convention, not evidence-backed; we
adopt them for consistency, not correctness.

## D3 — Readability rules: anti-patterns and review, not metrics

**Decision.** Adopt the 12 numbered rules in
`docs/research/standards-2026-07/readability.md` §3 as the repo's Readability
Rules (they extend, never contradict, the existing Four Principles). The
spine: a comment must say what the code cannot (Ousterhout APoSD ch.13;
convergent with Martin's own good-comment categories per their 2024-25
published debate); narration, hedging, and changelog comments are banned
(hedges route to tests/ASSUMPTIONS.md); **entanglement, not length, is the
split criterion** — no line-count laws; no comment-density targets; no
speculative abstraction/forwarding wrappers (already canon); Surgical Changes
extended explicitly to AI over-editing.

**Why we refuse mechanical caps.** The empirical record (Buse & Weimer 2010;
McConnell's synthesis) supports readability-predicts-defects but NOT
function-length or comment-density thresholds — mechanical rules would
re-encode the exact over-commenting failure mode AI writers already exhibit.
Instead: **readability is a named review dimension** (Google eng-practices
readability model) — tk-reviewer's rubric gains a readability line; money-path
review rounds adjudicate it explicitly.

## D4 — The seam-test policy (canonized verbatim)

Adopted word-for-word from the contract-testing memo:

> Every module boundary that passes a closed-vocabulary value (an enum, a
> string tag, an action kind) must satisfy three things before it ships:
> (1) the vocabulary is a typed `StrEnum`/`Literal`, never a bare `str`, so an
> invalid value cannot be constructed; (2) every consumer that branches on
> that value ends in `assert_never()` (or mypy's exhaustive-match check), so
> mypy — not a human — fails the gate when a new or misspelled value isn't
> handled everywhere; (3) at least one contract test feeds the *real*
> producer's output into the *real* consumer with no monkeypatch on either
> side, distinct from and in addition to each side's unit tests. Decision
> points that gate money-moving actions default to DENY/raise on anything
> outside the known vocabulary — never to a boolean identity (`all([])`,
> `any([])`) or a silent `None`/no-op return. A green gate is not evidence a
> seam works; only a contract test that exercises both real sides is.

**Why.** Fowler (ContractTest; Mocks Aren't Stubs) names the exact failure:
seam-mocked suites cannot see producer/consumer drift. Parse-don't-validate
(King) moves the rejection to construction time. Fail-closed is Saltzer &
Schroeder's fail-safe defaults (1975) + NASA/JPL Power of Ten rule 5 — the
`all([])` fail-open (audit H3) is the textbook violation. Design-by-Contract
libraries are DEFERRED (pydantic + mypy already cover most of the value);
Hypothesis adoption is SCOPED to gate/filter inputs first (proven bug-finding
record; the financial-code case study specifically was unverifiable and is
not relied on).

**Immediate applications (already ticketed/audited):** scanner filter values
(TICKET-001), `ProposedAction.kind` → `Literal` (audit H3, needs the taxonomy
adjudication), a `_SETUP_FILTERS`-to-scanner contract test (test-audit item 1).

## D5 — Behavior testing: the flows meta-suite

**Decision.** New first-class test category `tests/flows/` protecting the
flows codified in `docs/design/CORE-FLOWS.md` (M-F1..M-F4 there). Plain
named pytest flow tests — NO Gherkin/Cucumber layer. Flow list stays SMALL
(~5 core journeys); each sprint ends with the CORE-FLOWS §6 ritual: touched-
flow re-check, one discovery attempt (new flow or unhappy path), interface-
drift pass on touched modules. Flow tests run in the normal gate; only the
LLM-operator rehearsal (below) sits outside it, run periodically.

**Why.** BDD's value survives, its ceremony doesn't: 2024-26 practitioner
consensus (incl. Cucumber-team sources) documents Gherkin rot when scenarios
are written post-code — for a solo operator, named pytest tests capture
specification-by-example (North; Adzic) without the glue tax. Small-list
discipline is Google's Critical User Journeys doctrine (SRE Workbook) —
over-enumeration is a named anti-pattern. Placement follows the testing
trophy (Dodds): few, high-confidence flow tests above many units — S1 was an
assembly-time defect invisible to units by construction. DORA/Accelerate puts
them in the continuous commit gate.

**Unhappy paths are enumerated, not improvised**: CORE-FLOWS §7 taxonomy
(U1 wrong-context, U2 silent state change, U3 repeated action/idempotency,
U4 refused-by-design, U5 abandoned mid-flow, U6 upstream silence). NN/g error
heuristics (visibility, prevention, recovery) indict U2/U3 directly — the
Confirm bug is the canonical exhibit. Note honestly: "confused-operator
repeat-click" has no established industry name; the taxonomy entry is our own
synthesis.

## D6 — LLM-as-operator rehearsal: v1, narrowly scoped

**Decision.** Build v1 as **adversarial procedure-fuzzing, not user
simulation**: an LLM agent follows OPERATIONS.md against the real serve loop
on a TEMP ledger (rehearsal harness), with injected stochastic behaviors
drawn from the unhappy taxonomy (double-clicks, out-of-order steps, wrong
field transcription, mid-flow abandonment), and the pass/fail oracle is
**ledger invariants** (hash chain, no duplicate acks, no orphan events) — not
judgments about realism. Periodic, outside the commit gate.

**Why.** Academic LLM user-simulation is real but young; "synthetic user"
UX products demonstrably under-produce genuine confusion — so we buy the
proven half (adversarial fuzzing against invariants, cousin of Hypothesis
stateful testing / RuleBasedStateMachine, which fits an event-sourced core
well but models sequences, not intent) and skip the hyped half.

## D7 — Boundary-condition design duty + interface-drift review

**Decision.** At deep-module creation or refactor time, the designer must
write down, in the design doc: the module's full public verb set, every
closed vocabulary it exports/imports (→ glossary + enum), its behavior on
unrecognized input (default: raise/deny — D4), and its side-effect surface.
Interfaces are designed to RARELY change; modules stay agnostic of each
other's internals. End-of-sprint: the CORE-FLOWS §6 drift pass reviews
touched modules' interfaces for drift/friction, and — as the repo grows —
asks whether the current deep-module decomposition still fits (a deliberate,
occasional re-draw beats silent erosion). This codifies Ousterhout (deep
modules, strategic vs tactical programming) + Parnas-style information hiding
as an operating ritual, not just a taste.

---

## Rollout (proposed batch order — pending sit-down)

1. **Ratify** GLOSSARY.md + this canon (amendments welcome at the sit-down).
2. **TICKET-001 batch** applies D4 to the scanner (first enum + first
   contract test + attrition telemetry) — already queued as next batch.
3. **Money-path audit bundle** (H2/H3/M2/L1/L3) — D4's fail-closed doctrine,
   one reviewed round; H3 blocked on the kind-taxonomy adjudication.
4. **tests/flows/ M-F1 + M-F2** (scan-to-ticket real-config; Confirm chain +
   idempotency — M-F2b goes red until the button fix, which is correct).
5. Reviewer rubric gains the readability dimension (D3) — doc change to
   agent role + metrics table.
6. LLM-operator rehearsal v1 (D6) — after 4, since it drives the same harness.

## Doc-inventory updates this canon implies

- CLAUDE.md: glossary imperative (DONE); add "seam-test policy" pointer to
  Conventions on ratification.
- docs/design/CORE-FLOWS.md: sprint ritual owner (§6).
- docs/reviews/agent-metrics.md: readability column (rollout 5).
