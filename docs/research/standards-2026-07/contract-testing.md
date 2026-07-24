# Testing inter-module contracts and fail-loud unknown-input handling

Research brief for the S1-silence testing-doctrine upgrade. Incident: config emitted
`"bullish"`, scanner only recognized `"bullish_cross"` → silent `None` return, no trades,
1000+ green tests (both sides of the seam were monkeypatched). Same class found in a
policy gate that fails OPEN on an unrecognized action-kind because `all([]) == True`.

---

## 1. Key findings, with citations

### 1.1 Consumer-driven contract testing — adapting it in-process

Martin Fowler's bliki entry, originally titled "Integration Contract Test," was renamed
**"Contract Test"** once the term became the common industry name
([martinfowler.com/bliki/ContractTest.html](https://martinfowler.com/bliki/ContractTest.html)).
The core idea, independent of network vs. in-process: when module A talks to module B
through a test double of B, the double is only trustworthy if a **separate contract test
suite runs the same assertions against the real B** and is owned/run alongside B's own
tests — so if B's real behavior drifts, the contract suite (not just A's unit tests)
goes red. Fowler pairs this with **narrow integration tests** (small tests that touch the
real boundary, deliberately kept separate from broad/end-to-end tests) — see his
[IntegrationTest bliki entry](https://martinfowler.com/bliki/IntegrationTest.html).

Pact and classic "consumer-driven contracts" are described as service-to-service, but the
practitioner literature explicitly extends the pattern to **modular monoliths**: module
integration tests (spin up the real in-process boundary, no network) plus "a thin but
deliberate layer of contract and architecture tests to protect agreements and structural
integrity" — cross-module events/enums are called out as "the most brittle surface in a
modular monolith" because an implicit contract exists between publisher and handler with
no compiler enforcement (Microsoft's [CDC Testing playbook](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/cdc-testing/); [devleader.ca modular-monolith testing](https://www.devleader.ca/2026/07/20/testing-a-modular-monolith-in-c-unit-and-integration-test-strategies); [fullstackcity.com part 6](https://fullstackcity.com/part-6-testing-strategy-for-modular-monoliths-beyond-unit-tests)).

**Minimal in-repo version** (synthesized from the above, this is the practical distillation,
not a single citable artifact):
1. A **shared vocabulary module** — one enum/Literal that both producer and consumer
   import; there is no second string literal to drift from the first.
2. A **contract fixture test** that is *not* a unit test of either module: it constructs
   real producer output and feeds it to the real consumer (no monkeypatch on either side),
   asserting the round trip is accepted. This is exactly the test tradekit's S1 incident
   was missing — `hud/_build.py`'s emitted value was never fed into the real
   `mae/_scanner.py` in any test.
3. **Round-trip / enum-exhaustion tests**: for every value the shared enum can take,
   assert the consumer has a defined (non-silent) behavior.

### 1.2 Mocking discipline and "don't mock what you don't own"

Fowler's **"Mocks Aren't Stubs"** is the canonical reference distinguishing classicist TDD
(state verification, real collaborators, only mock "expensive" edges) from mockist TDD
(behavior verification, mock every collaborator) —
[martinfowler.com/articles/mocksArentStubs.html](https://martinfowler.com/articles/mocksArentStubs.html).
Freeman & Pryce's *Growing Object-Oriented Software, Guided by Tests* is the mockist-school
source for the discipline; "don't mock types you don't own" is their and the wider
community's rule of thumb, explained well in
[Hynek Schlawack's "Don't Mock What You Don't Own" in 5 minutes](https://hynek.me/articles/what-to-mock-in-5-mins/):
every hand-written mock **encodes an assumption about a contract**, and nothing forces
that assumption to stay true when the real implementation changes — "if one part of the
contract changes you have to manually change the other part manually, which can introduce
bugs." This is precisely the S1 failure mode: the scanner's test mocked/monkeypatched the
producer side with a value that matched the mock's assumption, not the config's real
output.

**Verified fakes**: when a fake stands in for a real collaborator (e.g., a fake broker/fake
scanner-config), it is only trustworthy once **one shared test suite runs against both the
fake and the real thing** — this is described directly in
[pythonspeed.com "Fast tests for slow services: why you should use verified fakes"](https://pythonspeed.com/articles/verified-fakes/):
"To make a fake into a verified fake... you need to write an additional set of tests that
run against both the fake and the real implementation, validating some sort of contract...
If a bug caused by inconsistencies between the fake and real implementation does slip by,
you simply add another test case to this suite, thus guaranteeing the bug will not recur."
This is the direct in-repo analogue of consumer-driven contracts and is cheaper to adopt
than Pact.

### 1.3 Design by Contract — Eiffel heritage, Python libraries

Bertrand Meyer's Design by Contract (Eiffel, 1980s) formalizes preconditions,
postconditions, and invariants as first-class, checked language constructs
([Eiffel Software](https://www.eiffel.com/values/design-by-contract/); Meyer's own
[chapter PDF](https://se.inf.ethz.ch/~meyer/publications/old/dbc_chapter.pdf)). In Python,
**icontract** provides `@require`/`@ensure` decorators with inheritance-aware contract
weakening/strengthening ([PyPI icontract](https://pypi.org/project/icontract/2.0.6/)).
`deal` is a comparable library (not independently confirmed in this pass —
**[UNVERIFIED-RECALL]** on deal's exact current API; icontract is verified, deal is
recalled from training data only).

Cost/benefit for a pydantic-heavy repo: DbC decorators add **runtime** checks, which
duplicate what a well-typed pydantic model + mypy strict should catch at
construction/static-analysis time for the enum-drift class of bug. DbC's marginal value
in tradekit is for *cross-field invariants* (e.g. "stop_price must be on the correct side
of entry for the given direction") that Literal/Enum typing cannot express — not for the
S1 bug class itself, which is fully solvable by parse-time typing (§1.4).

### 1.4 Parse, don't validate + total functions + exhaustiveness

Alexis King's 2019 essay (["Parse, don't validate"](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/))
argues for **total functions**: instead of validating a raw string and continuing to pass
the raw string around (a partial operation with an implicit failure mode later), *parse*
it once into a typed value that makes the invalid states unrepresentable; failure is
pushed to one boundary instead of latent everywhere downstream
([DevIQ summary](https://deviq.com/practices/parse-dont-validate/)). This is the direct
fix for the S1 bug: `"bullish"` should never survive as a bare `str` past the config
boundary.

Concrete Python mechanics, verified:
- `StrEnum` (3.11+) or `Literal["bullish_cross", "bearish_cross", ...]` as the field type
  on the pydantic config model — construction itself rejects `"bullish"`.
- **mypy exhaustiveness checking**: `assert_never()` in the `else`/final branch of an
  `if/elif` (or a non-exhaustive `match`) on a `Literal`/`Enum` value causes mypy to error
  at the *call site that added a new enum member without updating every consumer* —
  [mypy docs, Literal types and Enums](https://mypy.readthedocs.io/en/stable/literal_types.html);
  worked example: [Haki Benita, "Exhaustiveness Checking with Mypy"](https://hakibenita.com/python-mypy-exhaustive-checking);
  [Adam Johnson, "Python type hints: exhaustiveness checking"](https://adamj.eu/tech/2022/10/14/python-type-hints-exhuastiveness-checking/).
  Mypy also has `--enable-error-code exhaustive-match` for `match` statements specifically.
  This is the single highest-leverage, lowest-cost fix available: it converts "silently
  reject-all on a typo" into "mypy fails the gate the moment the enum value is introduced
  anywhere it isn't handled."

### 1.5 Property-based testing (Hypothesis) for gate/filter logic

Hypothesis is confirmed to have found real bugs in CPython's stdlib, NumPy, and "dozens of
other major open-source projects" per its own materials
([hypothesis.works/articles](https://hypothesis.works/articles/); GitHub repo). A 2026
paper shows even LLM-agent-driven Hypothesis test generation finding bugs in
NumPy/pandas ([arxiv 2510.09907](https://arxiv.org/html/2510.09907v1)).

Hillel Wayne's ["Property Tests + Contracts = Integration Tests"](https://www.hillelwayne.com/pbt-contracts/)
is directly relevant to the CTO's gate-filter case: he frames contracts as cheap/narrow and
property tests as wide-but-needing-good-generators, and recommends combining them —
generate structurally-valid-but-adversarial inputs (e.g. an action-kind string that is a
plausible enum value but not one any rule recognizes) and assert the *contract* (deny by
default) holds under property-based fuzzing of the input domain.

**I could not verify a specific Hillel Wayne (or other named industry) write-up of
Hypothesis catching a silent-default bug in financial code** — searches surfaced his
general PBT talks/posts but no matching financial-domain case study.
**[UNVERIFIED-RECALL]**: do not cite a specific financial-Hypothesis anecdote to Mike; the
general "Hypothesis finds real bugs in real projects, including via generated adversarial
values" claim is verified, the "financial code" specificity is not.

Direct applicability to the gate bug (`all([]) == True`): a Hypothesis strategy that
generates arbitrary action-kind strings (including ones sampled from *outside* the known
enum, plus mutated/near-miss variants of real enum values) run against the policy gate,
asserting the gate never returns "permit" for an unrecognized kind, would have caught this
class directly — this is a textbook property (`for all inputs not in KNOWN_KINDS, result
== DENY`), not an example-based test.

### 1.6 Fail-open vs fail-closed — authoritative doctrine

**Saltzer & Schroeder, "The Protection of Information in Computer Systems" (1975)** —
the **fail-safe defaults** principle: "base access decisions on permission rather than
exclusion... the default situation is lack of access." Their key mechanism-design argument:
"A design or implementation mistake in a mechanism that gives explicit permission tends to
fail by refusing permission — a safe situation, since it will be quickly detected. On the
other hand, a design/implementation mistake in a mechanism that explicitly excludes access
tends to fail by allowing access, a failure which may go unnoticed in normal use."
([cs.virginia.edu reproduction of the paper](https://www.cs.virginia.edu/~evans/cs551/saltzer/);
[Wikipedia summary](https://en.wikipedia.org/wiki/The_Protection_of_Information_in_Computer_Systems)).
This is an exact description of the gate bug: `all([]) == True` is a permission-by-absence
mechanism, and it failed silently precisely because Saltzer & Schroeder predicted that
shape of mechanism fails unnoticed.

**NASA/JPL "Power of Ten" (Gerard Holzmann, 2006)**, safety-critical C coding rules — Rule
5: use at least two assertions per function to check conditions that should never occur,
specifically to catch errors before they propagate
([spinroot.com/gerard/pdf/P10.pdf](https://spinroot.com/gerard/pdf/P10.pdf); [Wikipedia](https://en.wikipedia.org/wiki/The_Power_of_10:_Rules_for_Developing_Safety-Critical_Code)).
The applicable doctrine, ported to Python/pydantic: **an unrecognized enum/action-kind
value reaching a decision point is exactly a "should never occur" condition** and should
raise/assert, not fall through a loop that silently produces the permissive default.

General security-engineering framing confirms the vocabulary: "fail open" prioritizes
availability, "fail closed"/"fail-safe" prioritizes security by defaulting to deny —
[AuthZed, "Understanding Fail Open and Fail Closed"](https://authzed.com/blog/fail-open);
[DevSecOps School, "What is Fail Closed?"](https://devsecopsschool.com/blog/fail-closed/).
For a policy gate standing between an agent and money, fail-closed is the doctrine; money
loss from a missed trade (fail-closed false negative) is bounded and recoverable, money
loss from an unauthorized action executing (fail-open false positive) may not be.

---

## 2. Evidence vs. opinion

**Well-evidenced / citable as authority:**
- Saltzer & Schroeder fail-safe defaults (peer-reviewed, 50 years of citation).
- NASA/JPL Power of Ten Rule 5 (published standard, adopted institutionally at JPL).
- Fowler's Contract Test / Mocks Aren't Stubs / don't-mock-what-you-don't-own (widely
  cited industry canon, though Fowler himself frames CDC as service-oriented in origin;
  its in-process adaptation is practitioner consensus, not a single Fowler citation).
- mypy `assert_never` exhaustiveness checking (documented tool behavior, verified against
  current mypy docs).
- Parse-don't-validate (single-author essay, but has become de facto canon across
  Haskell/TS/Python type-driven-design communities; the "total function" framing is solid
  type theory, not just opinion).
- Verified fakes (documented pattern, single strong source — treat as good engineering
  practice, not as universally standardized terminology).

**Opinion / synthesis (mine, not directly sourced):**
- The specific "minimal in-repo contract kit" (§1.1 numbered list) — this is my synthesis
  of the sources, not a quoted recommendation from any one of them.
- Ranking DbC below typing for tradekit's specific bug class (§1.3) — a judgment call
  based on the mechanism of the actual incident, not an industry consensus statement.

**Explicitly unverified — do not present to Mike as sourced:**
- `deal` library's current API/feature set — [UNVERIFIED-RECALL].
- Any specific Hillel-Wayne-or-similar financial-code Hypothesis case study — searched and
  not found; treat the general "Hypothesis finds real bugs" claim as sourced, the
  financial-specificity as absent. **[UNVERIFIED-RECALL]**.

---

## 3. Recommendations for tradekit, ranked

**1. Typing fix first (cheapest, highest leverage, catches the exact bug class at zero
runtime cost).** Replace bare `str` enum fields at every module seam (scanner
signal-kind, policy action-kind) with `StrEnum` or `Literal[...]`. Add an `assert_never()`
(or `--enable-error-code exhaustive-match` for `match` statements) at the final branch of
every consumer that switches on one of these values. This makes `mypy` (already in
`tk-gate`) fail the build the instant a new/misspelled value reaches an unhandled branch —
this alone would have caught `"bullish"` vs `"bullish_cross"` at merge time, not in
production. Cost: one gate command already runs mypy; this is enabding a check that's
already paid for, not adding a new one.

**2. Fail-closed audit + fix on every gate/filter that iterates rules and defaults via
`all()`/`any()` over an empty or non-matching collection.** Grep for this shape repo-wide
(the gating-filter-audit already found one instance; there are likely siblings). Doctrine:
an unrecognized action-kind/signal-kind must raise or return an explicit `DENY` sentinel,
never fall through to a boolean identity value. This is a direct, mechanical Saltzer &
Schroeder / Power-of-Ten application — not new theory, just applying the principle
tradekit's own CLAUDE.md gate already implies.

**3. Minimal in-repo contract-test kit, built in this order:**
   a. A **shared enum module** each side imports (no restating string literals in
      `hud/_build.py` and `mae/_scanner.py` separately).
   b. One **round-trip contract test per seam** that constructs the real producer output
      end-to-end and feeds it to the real consumer — no monkeypatch on either side. Name
      these distinctly (e.g. `tests/contract/test_hud_scanner_seam.py`) so they're visibly
      a different test category from unit tests, per `tests/ASSUMPTIONS.md` conventions.
   c. For any fake/test-double still used at a module seam, add a **verified-fake test**
      that runs the same assertion suite against both the fake and the real object.

**4. Hypothesis adoption — scoped, not repo-wide.** Apply it specifically to gate/filter
decision functions and enum-consuming boundaries: generate the full space of
`str`/near-miss values (not just the known-good enum) and assert the property "unrecognized
kind → DENY, never PERMIT" and "producer's emitted value set ⊆ consumer's recognized set."
Do not use Hypothesis as a general-purpose test-writing tool elsewhere yet — scope
creep risk given the repo's existing 1000+-test surface; start at the two known trouble
spots (scanner enum seam, policy gate) and expand only if it earns its keep.

**5. Design by Contract (icontract) — defer.** Only pull it in for cross-field invariants
that Literal/Enum typing genuinely cannot express (e.g., stop/entry price ordering by
direction). Not warranted for the enum-drift bug class; would be redundant with #1.

**One-paragraph seam test policy (canonizable):**

> Every module boundary that passes a closed-vocabulary value (an enum, a string tag, an
> action kind) must satisfy three things before it ships: (1) the vocabulary is a typed
> `StrEnum`/`Literal`, never a bare `str`, so an invalid value cannot be constructed; (2)
> every consumer that branches on that value ends in `assert_never()` (or mypy's
> exhaustive-match check), so mypy — not a human — fails the gate when a new or misspelled
> value isn't handled everywhere; (3) at least one contract test feeds the *real* producer's
> output into the *real* consumer with no monkeypatch on either side, distinct from and in
> addition to each side's unit tests. Decision points that gate money-moving actions default
> to DENY/raise on anything outside the known vocabulary — never to a boolean identity
> (`all([])`, `any([])`) or a silent `None`/no-op return. A green gate is not evidence a
> seam works; only a contract test that exercises both real sides is.

---

## 4. Sources

- [Martin Fowler — bliki: ContractTest](https://martinfowler.com/bliki/ContractTest.html)
- [Martin Fowler — bliki: IntegrationTest](https://martinfowler.com/bliki/IntegrationTest.html)
- [Martin Fowler — Mocks Aren't Stubs](https://martinfowler.com/articles/mocksArentStubs.html)
- [Hynek Schlawack — "Don't Mock What You Don't Own" in 5 Minutes](https://hynek.me/articles/what-to-mock-in-5-mins/)
- [pythonspeed.com — Fast tests for slow services: why you should use verified fakes](https://pythonspeed.com/articles/verified-fakes/)
- [Microsoft Engineering Playbook — Consumer-Driven Contract Testing](https://microsoft.github.io/code-with-engineering-playbook/automated-testing/cdc-testing/)
- [devleader.ca — Testing a Modular Monolith in C#](https://www.devleader.ca/2026/07/20/testing-a-modular-monolith-in-c-unit-and-integration-test-strategies)
- [fullstackcity.com — Testing Strategy for Modular Monoliths Beyond Unit Tests](https://fullstackcity.com/part-6-testing-strategy-for-modular-monoliths-beyond-unit-tests)
- [Eiffel Software — Design by Contract](https://www.eiffel.com/values/design-by-contract/)
- [Bertrand Meyer — Design by Contract chapter (PDF)](https://se.inf.ethz.ch/~meyer/publications/old/dbc_chapter.pdf)
- [icontract on PyPI](https://pypi.org/project/icontract/2.0.6/)
- [mypy docs — Literal types and Enums / exhaustiveness](https://mypy.readthedocs.io/en/stable/literal_types.html)
- [Haki Benita — Exhaustiveness Checking with Mypy](https://hakibenita.com/python-mypy-exhaustive-checking)
- [Adam Johnson — Python type hints: exhaustiveness checking](https://adamj.eu/tech/2022/10/14/python-type-hints-exhuastiveness-checking/)
- [Alexis King — Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)
- [DevIQ — Parse, Don't Validate summary](https://deviq.com/practices/parse-dont-validate/)
- [Hillel Wayne — Property Tests + Contracts = Integration Tests](https://www.hillelwayne.com/pbt-contracts/)
- [Hypothesis — Articles](https://hypothesis.works/articles/)
- [HypothesisWorks/hypothesis on GitHub](https://github.com/HypothesisWorks/hypothesis)
- [arXiv 2510.09907 — Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem](https://arxiv.org/html/2510.09907v1)
- [Saltzer & Schroeder, "The Protection of Information in Computer Systems" (reproduction)](https://www.cs.virginia.edu/~evans/cs551/saltzer/)
- [Wikipedia — The Protection of Information in Computer Systems](https://en.wikipedia.org/wiki/The_Protection_of_Information_in_Computer_Systems)
- [Gerard Holzmann — The Power of Ten (PDF)](https://spinroot.com/gerard/pdf/P10.pdf)
- [Wikipedia — The Power of 10: Rules for Developing Safety-Critical Code](https://en.wikipedia.org/wiki/The_Power_of_10:_Rules_for_Developing_Safety-Critical_Code)
- [AuthZed — Understanding "Fail Open" and "Fail Closed"](https://authzed.com/blog/fail-open)
- [DevSecOps School — What is Fail Closed?](https://devsecopsschool.com/blog/fail-closed/)
