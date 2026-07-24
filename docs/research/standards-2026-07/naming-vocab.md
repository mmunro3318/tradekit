# Naming & Vocabulary Governance — Research Brief

Prepared for: repo-wide vocabulary/naming canon design (GLOSSARY.md), triggered by the
S1 silence incident (`hud/_build.py` emitted `"bullish"`, scanner filter accepted only
`"bullish_cross"` — same concept, drifted vocabulary, silent reject-all, no error).

Scope: DDD Ubiquitous Language, Python naming standards, naming/defect empirical
research, enforcement tooling, real-world glossary formats.

---

## 1. Key findings

### 1.1 Ubiquitous Language (DDD) — the academic ancestor of GLOSSARY.md

Eric Evans (*Domain-Driven Design*, 2003; reference summary 2014) defines Domain-Driven
Design itself partly as "speak a ubiquitous language within an explicitly bounded
context" — the language and the boundary are one design move, not two.
[Domain-Driven Design Reference PDF](https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf),
[Evans03.pdf](https://fabiofumarola.github.io/nosql/readingMaterial/Evans03.pdf).
The language must be **rigorous** (software tolerates no ambiguity), and it is expected
to **evolve** — Evans is explicit that both domain experts and developers have a duty to
object when a term is "awkward, inadequate, or ambiguous," which is the mechanism that
keeps a glossary alive rather than static documentation nobody reads
([Fowler, "UbiquitousLanguage," bliki, 2006](https://martinfowler.com/bliki/UbiquitousLanguage.html)).

Martin Fowler's companion piece on **Bounded Context** (2014) makes the point most load-
bearing for tradekit's design: a Bounded Context is explicitly a scope inside which one
term has one meaning — and DDD's answer to a large system is *not* one global glossary,
it is **multiple local glossaries stitched together by an explicit context map**
([Fowler, "BoundedContext," bliki, 2014](https://martinfowler.com/bliki/BoundedContext.html)).
The same word ("Order" in Sales vs. "Order" in Fulfillment) is allowed to mean different
things in different contexts *by design*, as long as the boundary is drawn and named
translations exist at the seam.

**Direct implication for the S1 incident:** `"bullish"` vs `"bullish_cross"` was not a
bounded-context split (two modules legitimately meaning different things) — it was
**unintentional vocabulary drift across a boundary that should have shared one term**.
DDD gives the vocabulary for telling these apart: a deliberate Bounded Context needs an
explicit **Anti-Corruption Layer** / translation map at its boundary; an *accidental*
split (this incident) is a defect the glossary should have caught. A single flat
GLOSSARY.md is the right tool only for concepts meant to be shared everywhere (signal
enums, order-state vocabulary, R-rule terms); anything genuinely context-local should be
scoped, not forced into the global file.

### 1.2 Python naming standards

- **PEP 8** (canonical): functions/methods/variables in `lowercase_with_underscores`;
  classes in `CapWords`; constants `UPPER_CASE`; single/double leading underscore for
  non-public/name-mangled members. PEP 8 does **not** mandate `is_`/`has_` boolean
  prefixes explicitly, but does instruct against `if x == True:`-style comparisons,
  implicitly pushing toward boolean-shaped names that read truthily on their own
  ([PEP 8](https://peps.python.org/pep-0008/)).
- **Google Python Style Guide**: function naming should be verb-first
  (`get_foo()`, `set_foo()`), `lower_with_under()` throughout; the guide's decisive
  ruling on properties vs. getters/setters: *"If a pair of getters/setters simply read
  and write an internal attribute, the internal attribute should be made public
  instead."* Properties are reserved for cases where "getting or setting the variable is
  complex or the cost is significant" but access should still *look* like plain
  attribute access ([Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)).
  This is the same doctrine as Guido van Rossum's "we're all consenting adults" position
  — Python favors public attributes over defensive encapsulation; use `@property` only
  when validation/computation genuinely warrants it, not as a default posture
  [UNVERIFIED-RECALL: exact "consenting adults" quote wording/venue not independently
  confirmed in this pass, but the doctrine is widely and consistently attributed to
  van Rossum across secondary sources].
- Boolean prefix convention (`is_`, `has_`, `can_`, `should_`) is close to universal
  practice in production Python codebases though it is a convention enforced by
  linters/review rather than a PEP-level rule — treat it as strong community consensus,
  not formal spec.

### 1.3 Naming quality vs. defect rates — empirical evidence

- **Butler, Wermelinger, Yu, Sharp, "Relating Identifier Naming Flaws and Code Quality:
  An Empirical Study,"** WCRE 2009. Evaluated 8 open-source Java systems against 12
  identifier-naming guidelines and found a **statistically significant association**
  between identifiers that violate naming guidelines and code flagged by FindBugs static
  analysis ([paper PDF](https://oro.open.ac.uk/17007/1/butler09wcreshort_latest.pdf),
  [IEEE listing](https://ieeexplore.ieee.org/document/5328661/)). This is
  **correlational**, not causal — poor naming and poor code quality plausibly share a
  common cause (rushed/careless authorship), and the study doesn't isolate naming as an
  independent causal factor.
- **Deissenboeck & Pizka, "Concise and Consistent Naming,"** Software Quality Journal
  14, 2006 (~333 citations). Proposes a formal model treating naming quality as a
  **bijective mapping between concepts and identifiers** — i.e., exactly one name per
  concept and exactly one concept per name — and built a tool that incrementally builds
  an identifier dictionary as the system is developed to enforce it
  ([Springer](https://link.springer.com/article/10.1007/s11219-006-9219-1),
  [scispace summary](https://scispace.com/papers/concise-and-consistent-naming-19nryqaufm)).
  This paper is the closest formal antecedent to "one canonical term per concept" —
  directly on point for the synonym-collapse ask, and for treating "bullish" /
  "bullish_cross" as exactly the many-names-one-concept violation the model targets.
- **Lawrie, Morrell, et al., "Effective Identifier Names for Comprehension and Memory,"**
  2007 (and companion ICPC work). Empirical study (100+ programmers) found full-word
  identifiers produce the **best comprehension**, but full words vs. good abbreviations
  showed **no significant difference**; single-letter identifiers were significantly
  worse than both
  ([paper PDF](https://www.cs.kent.edu/~jmaletic/cs63902/Papers/Lawrie07.pdf)). This
  bounds the practical claim: consistency and non-triviality of abbreviation matter more
  than "always spell it out."

### 1.4 Enforcement mechanics

- **ruff (pep8-naming / `N` rules)**: mechanically enforces PEP 8 case conventions
  (`N802` invalid function name, `N806` variable-should-be-lowercase, etc.) —
  configurable ignore lists per-name/pattern
  ([Ruff rules docs](https://docs.astral.sh/ruff/rules/)). This catches *casing*, not
  *vocabulary* — it cannot detect "bullish" vs "bullish_cross" because both are valid
  snake_case strings. Vocabulary/synonym enforcement needs a different mechanism.
- **Practical vocabulary-enforcement options** (synthesized, standard industry practice
  — not from a single citation): (a) a CI grep/regex gate that fails on banned-synonym
  strings appearing anywhere they shouldn't (e.g., forbid literal `"bullish"` outside
  the one module that defines the canonical enum); (b) a single source-of-truth Python
  `Enum` for domain vocabulary (signal states, order states) so drift becomes a
  compile-time/import error instead of a silent string mismatch — this is the strongest
  fix for the S1 class of bug specifically, stronger than any glossary-as-prose; (c)
  codespell-style dictionary tools repurposed as a "banned synonym → canonical term"
  dictionary, run in CI against changed files; (d) custom flake8/ruff plugin or AST-based
  check that flags string literals matching a known-synonym list. (a)-(c) are practical
  to automate today; a fully general "same concept, different word" detector is not
  automatable — that's a review-time judgment call, which is exactly why a maintained
  glossary is still needed alongside the enum fix.

### 1.5 Glossary formats that work

- Practitioner "Ubiquitous Language" skill/template (mattpocock, open-source Claude
  skill library): table format with columns **Term | Definition (one sentence) |
  Aliases to avoid**, grouped by subdomain, plus an explicit **Ambiguities** section for
  flagged overloaded/synonymous terms and example developer↔domain-expert dialogue to
  keep it grounded in actual usage
  ([SKILL.md](https://github.com/mattpocock/skills/blob/main/skills/deprecated/ubiquitous-language/SKILL.md)).
  The "Aliases to avoid" column is precisely the synonym-collapse mechanism the CTO is
  designing toward.
- **GitLab's engineering "Software Design" guide** explicitly instructs using ubiquitous
  (product/user-facing) language instead of generic CRUD terminology in code — e.g.
  prefer `Epic::AddExistingIssueService` over `EpicIssues::CreateService` — and uses
  **namespacing as the disambiguation mechanism** at real bounded-context seams (e.g.
  `MergeRequests::Diff` vs `Notes::Diff` legitimately mean different things and are kept
  apart by module path, not by a single flat term)
  ([GitLab Software Design docs](https://docs.gitlab.com/development/software_design)).
  This is a live, large, multi-team open-source codebase actually running the DDD
  bounded-context-plus-shared-language pattern in production — good precedent for
  tradekit's own module boundaries (`policy/`, `broker/`, `scan/`, `hud/`).

---

## 2. What the evidence supports vs. what is opinion

**Well-supported (multiple independent sources, or a controlled empirical study):**
- Consistent, full/descriptive identifiers aid comprehension over single-letter or
  inconsistent names (Lawrie et al., controlled study, N>100 subjects).
- Naming-guideline violations *correlate* with independently-flagged code-quality issues
  (Butler et al., 8-codebase empirical study) — but causality is not established.
- PEP 8 / Google style conventions for case (snake_case, CapWords, etc.) are effectively
  universal and mechanically enforceable — not opinion, they're the de facto Python
  standard.
- DDD's bounded-context model (same word, different meaning, different scope) is
  decades-old, widely adopted practice (Evans 2003, Fowler 2006/2014, GitLab's
  production style guide) — this is closer to established engineering consensus than
  opinion.

**Opinion / convention, not evidence-backed causally:**
- `is_`/`has_`/`should_` boolean prefixes: near-universal convention, but there is no
  controlled study cited here proving it reduces defects — it is readability convention,
  strongly held, not empirically load-bearing.
- "Properties over getters/setters" (Google guide, Pythonic norm): a language-idiom
  preference backed by community authority (Google's style guide, van Rossum's design
  philosophy), not by a defect-rate study.
- The claim that a *single* GLOSSARY.md file format (Term/Definition/Aliases-to-avoid)
  is "the" right structure is precedent-based (one open-source skill template, GitLab's
  broader convention), not validated by any controlled comparison of glossary formats.
- Deissenboeck & Pizka's bijective naming model is a compelling *formal framework*, but
  it is a proposal/tool paper, not a field study proving adoption reduces defects.

**Directly on point but not independently re-verified this pass:**
- The exact wording/venue of van Rossum's "we're all consenting adults" remark
  [UNVERIFIED-RECALL] — the underlying doctrine (public-attribute-by-default,
  encapsulation-by-convention-not-enforcement) is well and consistently attested, but I
  did not locate a single primary-source citation for the quote itself in this pass.

---

## 3. Concrete recommendations for tradekit, ranked

1. **Fix the enum, not just the glossary.** The S1 bug is a same-concept/two-strings
   defect. The highest-leverage fix is a single canonical `Enum` (or `Literal` type) for
   domain vocabulary — signal states, order states, position states — imported by both
   producer and consumer modules, so a drift like `"bullish"` vs `"bullish_cross"`
   becomes an `ImportError`/`AttributeError`/mypy failure, not a silent no-op. This is
   stronger than documentation alone (Deissenboeck & Pizka's bijective-mapping principle,
   applied via the type system rather than prose).
2. **GLOSSARY.md schema**: adopt the Term / Definition (one sentence) / Code form
   (canonical enum member or literal) / Aliases-to-avoid table format
   (mattpocock template, GitLab precedent). Group by subdomain matching tradekit's own
   module boundaries (`policy/`, `broker/`, `scan/`, `hud/`) rather than one flat
   alphabetical list — mirrors DDD's bounded-context structure instead of fighting it.
   Add an explicit **Ambiguities** section for terms flagged as legitimately
   context-dependent (this is where "same word, different meaning across modules" is
   allowed to live, per Fowler's BoundedContext) — distinct from banned-synonym drift,
   which is not allowed.
3. **Enforcement, tiered by automatability:**
   - Automate today: ruff `N` rules for case convention (mechanical, free); a CI grep/
     regex gate against a small banned-synonym dictionary derived from the glossary's
     "Aliases to avoid" column (cheap, catches the exact S1 class of bug going forward);
     mypy/type-checking on the canonical Enum so producer/consumer mismatches fail loud
     at the type level, not silently at runtime.
   - Needs human review, not automatable: whether a *new* term is truly a new concept
     vs. an unrecognized synonym of an existing glossary term — this is a review-gate
     item (tk-gate / PR review checklist), not a linter rule.
4. **Boolean naming**: adopt `is_/has_/can_/should_` prefixes as a house convention
   (community-standard, cheap to enforce via review, not evidence-critical but zero-cost
   to require).
5. **Property vs. getter/setter**: follow the Google Python Style Guide ruling verbatim
   — public attributes by default; `@property` only where access has real cost or
   validation; never ship a getter/setter pair that's a pure pass-through. Low risk,
   well-established Python idiom, easy to state as a one-line rule in CLAUDE.md.
6. **Keep the glossary alive, not frozen**: per Evans/Fowler, make updating
   GLOSSARY.md part of the definition of done for any PR that introduces or renames a
   domain term — tradekit's CLAUDE.md doc inventory mechanism is already the right place
   to wire this in (add GLOSSARY.md as a doc-inventory row, updated whenever a
   vocabulary term changes, same discipline as `tests/ASSUMPTIONS.md`).

---

## 4. Sources

- Eric Evans, *Domain-Driven Design Reference*, 2015 (PDF): https://www.domainlanguage.com/wp-content/uploads/2016/05/DDD_Reference_2015-03.pdf
- Eric Evans, *Domain-Driven Design: Tackling Complexity in the Heart of Software*, 2003 (PDF): https://fabiofumarola.github.io/nosql/readingMaterial/Evans03.pdf
- Martin Fowler, "UbiquitousLanguage," bliki, 2006: https://martinfowler.com/bliki/UbiquitousLanguage.html
- Martin Fowler, "BoundedContext," bliki, 2014: https://martinfowler.com/bliki/BoundedContext.html
- PEP 8 — Style Guide for Python Code: https://peps.python.org/pep-0008/
- Google Python Style Guide: https://google.github.io/styleguide/pyguide.html
- Butler, Wermelinger, Yu, Sharp, "Relating Identifier Naming Flaws and Code Quality: An Empirical Study," WCRE 2009: https://oro.open.ac.uk/17007/1/butler09wcreshort_latest.pdf ; IEEE: https://ieeexplore.ieee.org/document/5328661/
- Deissenboeck & Pizka, "Concise and Consistent Naming," Software Quality Journal 14, 2006: https://link.springer.com/article/10.1007/s11219-006-9219-1
- Lawrie, Morrell et al., "Effective Identifier Names for Comprehension and Memory," 2007: https://www.cs.kent.edu/~jmaletic/cs63902/Papers/Lawrie07.pdf
- Ruff rules documentation (pep8-naming `N` rules): https://docs.astral.sh/ruff/rules/
- mattpocock, ubiquitous-language SKILL.md (glossary template): https://github.com/mattpocock/skills/blob/main/skills/deprecated/ubiquitous-language/SKILL.md
- GitLab Development docs, "Software Design": https://docs.gitlab.com/development/software_design
