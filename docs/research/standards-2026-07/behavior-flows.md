# Research: Codifying User Flows as a Meta Test Suite (+ LLM-simulated-user practice)

Date: 2026-07-24
Trigger: S1 silence (scan produced zero tickets for days, no test caught it — unit tests
covered pieces, no test walked the real end-to-end flow) + the HUD Confirm-button
incident (no feedback, not idempotent, operator double-booked events by re-clicking —
no test covered the "confused user" path). CTO wants (a) core user flows codified as a
first-class, growing meta-suite, and (b) an assessment of LLM-driven user simulation as
a discovery tool for edge flows.

---

## 1. Key findings, by required coverage area

### 1.1 BDD/ATDD lineage — where it delivers, where it rots

- Dan North's original 2006 post, "Introducing BDD," reframed TDD around behavior/language
  to fix the ambiguity programmers hit doing TDD raw — what to test, what to call tests,
  how much to test at once. It is a communication technique first, tooling second.
  [Introducing BDD — Dan North](https://dannorth.net/blog/introducing-bdd/) ·
  [Cucumber history](https://cucumber.io/docs/bdd/history/)
- Gojko Adzic's *Specification by Example* (2011, Jolt Award) generalizes BDD into seven
  patterns: derive scope from goals, specify collaboratively, illustrate with examples,
  refine the specification, automate validation without changing intent, validate
  frequently, evolve a documentation system. The core claim: tests-as-specs and
  specs-as-tests, kept living via continuous automation — not a one-time artifact.
  [Adzic — Specification by Example](https://gojko.net/books/specification-by-example/)
- **Circa-2024–2026 honest verdict, well evidenced**: Gherkin/Cucumber adoption commonly
  fails ~1 year in. The Cucumber team itself documents the recurring failure pattern:
  scenarios get written *after* the code (or by developers alone), which "flips BDD on
  its head" — scenarios stop driving design and become decorative test names ("ceremony
  rot"). The promised business/dev collaboration rarely materializes; feature files are
  nominally readable by non-engineers but in practice are maintained by engineers only.
  Glue-code maintenance overhead frequently cancels out Gherkin's readability benefit as
  suites grow. [303 Software — BDD/Cucumber 2025 reality check](https://www.303software.com/insights/behavior-driven-development-cucumber-testing-2025-reality) ·
  ["Cucumber is Dying" retrospective](https://vocal.media/geeks/cucumber-is-dying-what-did-we-learn-part-1-the-facts) ·
  [TestQuality — Gherkin pitfalls](https://testquality.com/cucumber-and-gherkin-language-best-practices/)
- **Minimal viable version for a solo operator (recommendation, informed by the above)**:
  skip Gherkin/Cucumber entirely. There is no second stakeholder to collaborate with in
  natural language — Mike is both the domain expert and the only reader. Plain
  `pytest` functions named after the user flow (`test_flow_scan_to_ticket_render`,
  `test_flow_confirm_is_idempotent_under_double_click`) capture 100% of BDD's actual
  value here (a named, executable, business-legible scenario) with none of the glue-code
  tax. Gherkin earns its cost only when a non-engineer must read/write scenarios
  directly — not the case in a one-operator shop.

### 1.2 Picking which flows to codify — CUJs, testing trophy vs pyramid

- Google's **Critical User Journeys (CUJ)** concept (SRE Workbook, "Implementing SLOs" /
  "Monitoring Distributed Systems" chapters) frames CUJs as end-to-end sequences a user
  takes to accomplish a goal, chosen *before* SLIs/SLOs are defined — the journey is the
  unit of reliability engineering, not the individual service call. A commonly cited
  pitfall: **teams enumerate too many CUJs** and dilute focus; mature practice keeps the
  list small and ruthlessly prioritized to what the business actually depends on.
  [Google UX Director on CUJs](https://www.mindtheproduct.com/measuring-critical-user-journeys-javier-andres-bargas-avila-ux-research-director-google/) ·
  [InfoQ — Monitoring CUJs](https://www.infoq.com/articles/critical-journeys-azure/)
- This maps directly onto tradekit: "~5 core flows" is not an arbitrary number — it's
  the CUJ discipline correctly applied to a small system.
- **Testing trophy (Kent C. Dodds) vs test pyramid (Cohn/Fowler)**: the pyramid optimizes
  for speed/cost of the test suite and pushes weight to unit tests; the trophy optimizes
  for *confidence-per-test* and weights integration tests highest, on the premise "the
  more your tests resemble how the software is actually used, the more confidence they
  give you." [Kent C. Dodds — Testing Trophy and Classifications](https://kentcdodds.com/blog/the-testing-trophy-and-classifications) ·
  [Baytech — Pyramid vs Trophy](https://www.baytechconsulting.com/blog/test-pyramid-vs-testing-trophy-whats-the-difference)
- **Placement verdict**: user-flow tests are not a replacement for unit tests, and not
  where most tests live — they sit at the trophy's integration/E2E layer, deliberately
  *few and expensive*, existing specifically to catch what unit tests structurally
  cannot: an assembly-time defect where every unit is individually correct but the
  seam between them is wrong. S1 (an enum-value mismatch between the scanner's output
  vocabulary and the HUD's filter) is the textbook example of a defect invisible to unit
  tests and visible only to a flow test that runs scan → HUD with real data shapes.

### 1.3 Unhappy-path taxonomy and the Confirm-button incident

- NN/g's Heuristic #9 ("Help Users Recognize, Diagnose, and Recover from Errors") and
  Heuristic #5 ("Error Prevention") are the two heuristics of Nielsen's ten devoted
  entirely to failure handling. Concrete guidance: error states must be **visible**
  (not silent), located near the point of failure, phrased in plain language, and must
  tell the user what to do next — not just that something went wrong.
  [NN/g — Error-Message Guidelines](https://www.nngroup.com/articles/error-message-guidelines/) ·
  [NN/g — Hostile Patterns in Error Messages](https://www.nngroup.com/articles/hostile-error-messages/)
  The Confirm-button bug is a direct violation of both: no visible success/failure
  state at all (silent), and no error-prevention guard against a repeat action with
  side effects (a "serious consequence" per Heuristic #5, which explicitly calls for a
  confirmation or guard before such actions — tradekit's failure was the *inverse*,
  missing guard on an already-taken action).
- Industry taxonomy of non-happy flows (informal but consistent across sources):
  **sad path** (anticipated failure — rejected auth, a 500 from a downstream service),
  **edge case** (boundary input — empty universe, zero candles), **corner case**
  (multiple low-probability conditions compounding). The tradekit-specific fourth
  category the taxonomy doesn't name well but the incident demands: **confused-operator
  path** — user re-does an already-successful action because the system gave no
  feedback. This is a UI/idempotency defect, not an input-validation defect, and needs
  its own test category.
  [Sad path testing overview](https://medium.com/qualitynexus/happy-paths-vs-sad-paths-testing-why-both-are-essential-3614db1ea89b)
- **Idempotency-under-repeated-action** is a well-established backend/frontend pattern:
  disable-on-click + idempotency key + uniqueness constraint at the persistence layer +
  (for browser forms) Post/Redirect/Get. The generalizable principle for tradekit: any
  advisory-ticket "Confirm" action must (a) be guarded by an idempotency key derived
  from the ticket, so repeat submits are no-ops, not new events, and (b) always render a
  visible terminal state (success/failure), never silence.
  [Idempotent frontend design](https://trillionclues.medium.com/building-for-certainty-designing-idempotent-frontends-in-a-system-that-cant-afford-mistakes-7d531c4a6781) ·
  [Preventing duplicate requests](https://khalidabuhakmeh.com/preventing-duplicate-web-requests-to-aspnet-core)

### 1.4 Model-based / state-machine testing of flows

- Hypothesis's `RuleBasedStateMachine` models a system as states + `@rule`-decorated
  transitions, then Hypothesis searches for *sequences of actions* (not just single
  inputs) that break an invariant, shrinking failing sequences to a minimal repro. This
  is exactly "multiple clicks in some order" as a first-class thing to fuzz, rather than
  a single hand-written double-click test.
  [Hypothesis — Rule Based Stateful Testing](https://hypothesis.works/articles/rule-based-stateful-testing/) ·
  [Hypothesis stateful docs](https://hypothesis.readthedocs.io/en/latest/stateful.html)
- **Fit assessment for tradekit (honest)**: strong conceptual fit — tradekit is
  event-sourced, so "the state" a stateful test needs (event log → derived read models)
  is already the system's native data model, not something to bolt on. A `HUDStateMachine`
  with rules `scan()`, `click_confirm(ticket_id)`, `click_confirm_again(ticket_id)`,
  `refresh()` could let Hypothesis discover double-submit and out-of-order-click bugs
  the team wouldn't think to hand-write. Cost: state machines model *system* behavior,
  not *user* behavior — they won't generate "impatient" or "confused" click *timing/intent*,
  only combinatorial *sequences*. Complementary to, not a substitute for, human-modeled
  flow tests. Right-sized as a v2 addition once the meta-suite exists, not a v1
  requirement.

### 1.5 LLM-as-simulated-user — real vs hype

- **Academic (real, active, mixed results)**:
  - Dialogue-systems literature has a mature line of "user simulator" work predating
    LLMs (rule-based, agenda-based), now shifting to LLM-based simulators for
    task-oriented dialogue evaluation — explicitly used to catch failure modes
    (verbosity, role drift, goal drift) an automated eval alone would miss.
    [LLMs as user-agents for evaluating TOD systems](https://arxiv.org/pdf/2411.09972) ·
    [ChatChecker — non-cooperative user simulation for dialogue testing](https://arxiv.org/pdf/2507.16792)
  - GUI-agent testing research (2024-2026) is a distinct, fast-moving thread: LLM agents
    driving mobile/web GUIs to find defects (scenario-guided testing, exploratory defect
    discovery). Reported accuracy is still modest — one survey cites ~51% goal-inference
    accuracy on unseen websites — meaning these agents are useful for *coverage/fuzzing*,
    not yet trustworthy as a stand-in for judgment about whether behavior is "right."
    [GUI Agents: A Survey](https://arxiv.org/html/2412.13501v2) ·
    [Scenario-Guided LLM Mobile GUI Testing](https://arxiv.org/html/2506.05079v4)
  - Park et al.'s "Generative Agents: Interactive Simulacra of Human Behavior" (Stanford/
    Google, UIST 2023) is the foundational reference for LLM agents with persistent
    memory/reflection producing "believable" (not necessarily *accurate*) behavior —
    frequently over-cited by synthetic-user vendors as validation of accuracy claims it
    doesn't make; the paper's own bar is *believability*, explicitly not fidelity to any
    specific real population. [Park et al. 2023](https://arxiv.org/pdf/2304.03442)
- **Industry/product ("synthetic users") — hype-heavy, credible critiques**:
  Practitioner writeups in 2025 are consistently blunt: synthetic-user tools are "more
  marketing than evidence"; in head-to-head e-commerce tasks, LLM agents "followed neat
  paths while real users wandered, second-guessed, and gave up" — synthetic users
  systematically under-produce the confusion/hesitation/abandonment that real usability
  testing exists to surface. A 9-model evaluation found most LLMs fail to reproduce
  human-like behavior distributions. Consensus recommendation: legitimate as a
  pre-research / triage / augmentation tool, not a replacement for testing with real
  users. [MeasuringU — Review of Experiments with Synthetic Users](https://measuringu.com/review-of-experiments-with-synthetic-users/) ·
  [ACM Interactions — Challenges of Synthetic Users](https://interactions.acm.org/blog/view/the-challenges-of-synthetic-users-in-ux-research) ·
  [UX Army — Synthetic Participants: Hype or Future?](https://uxarmy.com/blog/synthetic-participants-ux-research/)
- **Net read for tradekit**: the specific idea in the mission — "an LLM operator
  following OPERATIONS.md against the real HUD in a temp-ledger rehearsal, injecting
  stochastic confusion/impatience" — is closer to the *dialogue-system user-simulator*
  literature (goal-directed agent executing a real procedure against a real system,
  evaluated for whether the system handles deviation) than to the *synthetic-UX-research*
  product category (which tries to predict subjective human reaction and is where the
  hype/critique concentrates). Tradekit's use case does not need the LLM to *feel* like
  a real trader — it needs the LLM to *behave* unpredictably enough (repeat clicks,
  wrong order, abandon mid-flow, re-read stale state) to exercise paths a scripted test
  wouldn't think to write. That is a much lower, achievable bar than "simulate Mike's
  psychology," and it's where current LLM-GUI-agent capability (~real, if immature)
  actually applies — not where synthetic-user hype lives.

### 1.6 DORA/DevOps Handbook framing

- *Accelerate* and *The DevOps Handbook* (Forsgren, Humble, Kim, et al.) place continuous
  testing early in the deployment pipeline: automated unit + integration tests running
  on every commit, gating the fast flow from Dev to Ops; the highest-performing orgs in
  DORA's own data have the shortest integration windows and rely on the pipeline (not
  manual QA) as the safety net. [DevOps Handbook overview](https://dev.to/raoulmeyer/book-review-accelerate-the-comprehensive-devops-guide-8h1) ·
  [O'Reilly — DevOps Handbook, deployment pipeline](https://www.oreilly.com/library/view/the-devops-handbook/9781098182281/26-part-3-intro.xhtml)
- **Placement verdict**: flow tests belong in the same automated gate as everything
  else (`uv run pytest -q` per tradekit's CLAUDE.md), not a separate manual pre-release
  ritual — otherwise they decay exactly like Cucumber suites do when kept outside CI's
  daily pressure. The LLM-operator rehearsal (heavier, non-deterministic) is the one
  piece that legitimately sits *outside* the fast commit-gate loop — DORA doctrine treats
  exploratory/manual-style testing as a periodic, lower-frequency check layered on top of
  the continuous pipeline, not a per-commit gate.

---

## 2. Evidence vs. opinion — where to be blunt

**Solid evidence (multiple independent, converging sources):**
- BDD/Gherkin ceremony-rot at the ~1-year mark is well documented, including by
  Cucumber's own team — this is not sour-grapes from competitors, it's the tool
  vendor admitting the common failure mode.
- CUJ-overproliferation as a named anti-pattern (too many journeys diluting focus) is
  consistent across SRE sources.
- Idempotency-under-repeat-click is a solved, boring, well-understood engineering
  pattern — there is no ambiguity or debate here, only whether it was applied.
- Synthetic-user critique (real users wander/abandon, LLMs don't) is now a repeated,
  specific empirical finding across independent practitioner writeups in 2025, not a
  single hot take.

**Opinion / extrapolation flagged as such:**
- The claim that tradekit's "confused-operator path" needs its own named test category
  distinct from sad/edge/corner is this report's synthesis, not an established industry
  term — the industry taxonomy doesn't cleanly name this case; NN/g's error heuristics
  cover the *symptom* (silent failure) but not the taxonomy label.
- The recommendation to route the LLM-operator rehearsal through the dialogue-system
  user-simulator framing rather than the synthetic-UX-research framing is this report's
  judgment call, reasoned from the difference in what each literature optimizes for
  (behavioral fidelity to a psychological population vs. adversarial procedure-execution
  against a real system) — it is a reasonable inference from the cited sources, not
  itself a claim made by any single source.
- [UNVERIFIED-RECALL] Exact CUJ methodology mechanics (workbook chapter numbering,
  specific worked examples) were not fetched from the primary SRE Workbook text in this
  pass — search results and secondary summaries were used. If the CTO wants to cite
  Google's SRE Workbook verbatim, fetch `sre.google/workbook/implementing-slos/`
  directly before quoting it.

---

## 3. Concrete recommendations for tradekit

### 3.1 Codify ~5 core flows as a first-class suite: `tests/flows/`

Add a fourth test category alongside `unit/contract/golden/replay`:
`tests/flows/` — each file is one CUJ, plain pytest, no Gherkin. Candidate initial five
(pick from tradekit's actual daily loop — CTO to confirm exact list, but pattern is):
1. `test_flow_scan_produces_renderable_tickets` — the exact flow S1 broke: scan → HUD
   render, asserting non-zero tickets under a fixture universe known to have valid
   setups, with attrition telemetry asserted at each stage (this is what TICKET-001
   should feed into, not replace).
2. `test_flow_ticket_confirm_records_single_fill` — Confirm clicked once → exactly one
   event recorded, visible success state rendered.
3. `test_flow_ticket_confirm_is_idempotent_under_repeat_click` — Confirm clicked N times
   in a row → still exactly one event, and every click after the first renders an
   explicit "already confirmed" state (not silence, not a duplicate).
4. `test_flow_hud_reflects_gate_rejection` — a policy-gate reject on an order is
   visibly surfaced in the HUD, not silently dropped (the sibling bug class to Confirm).
5. `test_flow_stale_ticket_after_market_move` — a ticket rendered, market moves,
   operator confirms late; system must not silently execute against stale assumptions.

Each flow test runs against the same seams already used elsewhere (`mae._runtime.get_closed_bars`/`_clock`), never mocking tradekit internals — consistent with existing
determinism doctrine.

### 3.2 Meta-suite structure and sprint cadence

- `tests/flows/` gates in CI on every commit (same `uv run pytest -q` command) —
  per the DORA framing, this must not become a side-track ritual.
- Each sprint (tk-tasks/tk-implement cycle) that touches a user-facing action adds or
  extends one flow test as part of "done" — the doc-inventory pattern already used for
  ROADMAP/dev-log applies here: **flow coverage is part of the doc inventory**, add a row
  to CLAUDE.md's table: `tests/flows/ | any new/changed user-facing action`.
  New flows are discovered from (a) production incidents like S1/Confirm — mandatory,
  same sprint, (b) tk-qa findings, (c) the LLM-operator rehearsal (3.4) run periodically
  (suggest: every 2-3 sprints, not every sprint — it's heavier and DORA-style continuous
  pipelines keep exploratory checks lower-frequency than the commit gate).

### 3.3 Unhappy-path taxonomy to apply going forward

Adopt four labels for any new flow test, so "which unhappy paths have we covered" is
answerable at a glance:
- **sad**: expected failure (bad credentials, broker reject, gate reject)
- **edge**: boundary input (empty universe, zero-liquidity symbol)
- **corner**: multiple low-probability conditions compounding
- **confused-operator**: repeat/out-of-order/mistimed actions on an already-valid flow
  (the Confirm-button bug's category) — test via idempotency-key assertions and
  explicit-state-rendering assertions, not input validation.

### 3.4 Scoped v1 of the LLM-operator rehearsal

Given the hype/evidence split in 1.5, keep v1 narrow and mechanical, not a UX-fidelity
exercise:
- **Setup**: temp/throwaway event ledger, real HUD running locally, no real broker
  (Kraken sandbox or the paper-mode already in Phase P4).
- **Driver**: one LLM agent given `docs/OPERATIONS.md` verbatim as its only instructions
  (proving the doc itself is sufficient — a bonus finding if it isn't) plus a stochastic
  "behavior knob": with some probability per step, repeat the last click, click a stale
  ticket, navigate away mid-action, or pause and resume.
- **Oracle**: not "did the LLM feel confused" (that's the synthetic-UX-hype trap) —
  instead, deterministic invariant checks against the event ledger after the run:
  exactly-once-per-confirmed-ticket, no orphaned/duplicate events, every ledger entry
  traces to a visible HUD state the agent could have observed. This reframes the
  rehearsal from "simulate Mike's psychology" (unproven, per 1.5) to "adversarially
  fuzz the procedure against the real system's invariants" (proven pattern, per 1.4/1.5
  dialogue-simulator literature) — cheap to justify, hard to argue is theater.
- **Cadence**: run manually first (1-2 rehearsals) to see if it finds anything beyond
  what flow tests already catch; only automate into a recurring job if it earns its
  keep — do not pre-build tooling for a practice not yet proven valuable on this
  codebase (Simplicity First).

---

## 4. Sources

- [Introducing BDD — Dan North](https://dannorth.net/blog/introducing-bdd/)
- [History of BDD — Cucumber](https://cucumber.io/docs/bdd/history/)
- [BDD & Cucumber Reality Check 2025 — 303 Software](https://www.303software.com/insights/behavior-driven-development-cucumber-testing-2025-reality)
- ["Cucumber is Dying" — Part 1: The Facts](https://vocal.media/geeks/cucumber-is-dying-what-did-we-learn-part-1-the-facts)
- [Gherkin/Cucumber best practices and pitfalls — TestQuality](https://testquality.com/cucumber-and-gherkin-language-best-practices/)
- [Specification by Example — Gojko Adzic](https://gojko.net/books/specification-by-example/)
- [Measuring Critical User Journeys — Javier Bargas-Avila (Google)](https://www.mindtheproduct.com/measuring-critical-user-journeys-javier-andres-bargas-avila-ux-research-director-google/)
- [Monitoring Critical User Journeys — InfoQ](https://www.infoq.com/articles/critical-journeys-azure/)
- [The Testing Trophy and Testing Classifications — Kent C. Dodds](https://kentcdodds.com/blog/the-testing-trophy-and-classifications)
- [Test Pyramid vs Testing Trophy — Baytech](https://www.baytechconsulting.com/blog/test-pyramid-vs-testing-trophy-whats-the-difference)
- [Error-Message Guidelines — NN/g](https://www.nngroup.com/articles/error-message-guidelines/)
- [Hostile Patterns in Error Messages — NN/g](https://www.nngroup.com/articles/hostile-error-messages/)
- [Happy Paths vs Sad Paths Testing — QualityNexus](https://medium.com/qualitynexus/happy-paths-vs-sad-paths-testing-why-both-are-essential-3614db1ea89b)
- [Rule Based Stateful Testing — Hypothesis](https://hypothesis.works/articles/rule-based-stateful-testing/)
- [Hypothesis stateful testing docs](https://hypothesis.readthedocs.io/en/latest/stateful.html)
- [Large Language Models as User-Agents for Evaluating TOD Systems](https://arxiv.org/pdf/2411.09972)
- [ChatChecker — non-cooperative user simulation for dialogue testing](https://arxiv.org/pdf/2507.16792)
- [GUI Agents: A Survey](https://arxiv.org/html/2412.13501v2)
- [Scenario-Guided LLM-based Mobile App GUI Testing](https://arxiv.org/html/2506.05079v4)
- [Generative Agents: Interactive Simulacra of Human Behavior — Park et al. 2023](https://arxiv.org/pdf/2304.03442)
- [A Review of Experiments with Synthetic Users — MeasuringU](https://measuringu.com/review-of-experiments-with-synthetic-users/)
- [The Challenges of Synthetic Users in UX Research — ACM Interactions](https://interactions.acm.org/blog/view/the-challenges-of-synthetic-users-in-ux-research)
- [Synthetic Participants In UX Research: Hype Or Future? — UX Army](https://uxarmy.com/blog/synthetic-participants-ux-research/)
- [Book review: Accelerate — DEV Community](https://dev.to/raoulmeyer/book-review-accelerate-the-comprehensive-devops-guide-8h1)
- [The DevOps Handbook, deployment pipeline chapter — O'Reilly](https://www.oreilly.com/library/view/the-devops-handbook/9781098182281/26-part-3-intro.xhtml)
- [Building for Certainty: Designing Idempotent Frontends — Trillion Clues](https://trillionclues.medium.com/building-for-certainty-designing-idempotent-frontends-in-a-system-that-cant-afford-mistakes-7d531c4a6781)
- [Preventing Duplicate Web Requests — Khalid Abuhakmeh](https://khalidabuhakmeh.com/preventing-duplicate-web-requests-to-aspnet-core)
