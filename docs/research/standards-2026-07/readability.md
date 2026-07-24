# Readability Standards Research — Comments, Bloat, Verbosity (2026-07)

Scope: ground repo-wide readability rules (targeting AI-generated code's known failure
modes — over-commenting, speculative abstraction, defensive bloat) in cited sources,
not vibes. tradekit's CLAUDE.md already carries "A Philosophy of Software Design" as
canon and a forwarding-wrapper ban; this extends that into an enforceable comment/bloat
standard.

---

## 1. Key Findings

### 1.1 Ousterhout — *A Philosophy of Software Design* (2018/2021, 2nd ed.)

- **Complexity = dependencies + obscurity.** Anything that forces a reader to hold more
  context in their head, or that makes intent non-obvious from the code itself, is
  complexity — regardless of line count. [Already repo canon.]
- **Deep vs. shallow modules.** A deep module has a small interface and large
  functionality; a shallow module's interface is complicated relative to what it does.
  Forwarding wrappers (thin pass-through functions with no independent logic) are the
  canonical shallow-module anti-pattern — this is the documented reason tradekit's
  CLAUDE.md rejects them by default.
- **"Define errors out of existence."** Prefer designs where an invalid state simply
  can't arise (e.g., a selection object that always has a length, zero when empty)
  over designs that require exception handling / defensive branches for cases that
  shouldn't need special-casing. This is Ousterhout's argument against defensive
  bloat: most error-handling paths are themselves a complexity tax, and many can be
  designed away rather than caught.
- **Comments rule (core, precise wording):** comments should describe things that
  *aren't obvious from the code* — rationale, non-obvious constraints, and the
  "why," not a restatement of the "what." Ousterhout advocates writing interface
  comments even for private methods, because contracts get forgotten faster than code
  gets reread.
- Source: John Ousterhout, *A Philosophy of Software Design*, 2nd ed., Yaknyam Press,
  2021. Author's course notes overview: https://web.stanford.edu/~ouster/cgi-bin/aposd.php
  (evidence: primary source / author's own framework, not independently validated
  empirically by third parties — treat as expert opinion, not measured data).

### 1.2 The Ousterhout–Martin ("Uncle Bob") 2024–25 public debate

Primary source, fetched directly: https://github.com/johnousterhout/aposd-vs-clean-code
(a structured, both-authors-edited document — high provenance, first-person from both
sides). Supplementary coverage: Book Overflow podcast
(https://podwise.ai/dashboard/episodes/4193026) and a third-party recap
(https://tryingthings.wordpress.com/2025/02/25/aposd-vs-clean-code-a-debate/).

**Where they agree:**
- Both value modular decomposition as a tool for reducing cognitive load.
- Both accept that over-decomposition is a real failure mode, not just under-decomposition.
- Both ultimately optimize for reader understanding — they diverge on what reduces it.

**Where they disagree — method length:**
- Martin (Clean Code): "Functions should hardly ever be 20 lines long... the first
  rule of functions is that they should be small. The second rule is that they should
  be smaller than that." Advocates near-mechanical extraction of any nameable chunk
  ("One Thing" rule).
- Ousterhout: rejects "One Thing" as a rule without a stopping condition. Argues that
  below a certain point, further splitting creates **entangled shallow methods** —
  methods that can't be understood in isolation, so a reader has to load several of
  them into working memory simultaneously, which is worse for comprehension than a
  longer, self-contained method. His empirical demonstration: rewriting Martin's
  8-method `PrimeGenerator` (from *Clean Code*) both his way (1 method, dense
  why-comments) and having Martin re-decompose it — Martin's own re-decomposition
  introduced a **3–4x performance regression** from splitting a single validation
  loop into two, which both authors treat as evidence that the decomposition was
  driven by rule-following rather than genuine functional boundaries.
- Martin's partial concession: "We both value decomposition, and we both avoid
  entanglement; but we disagree on the relative weighting of those two values."

**Where they disagree — comments:**
- Martin: "Comments are always failures... their use is not a cause for celebration."
  Treats every comment as a maintenance liability and potential lie ("I look at every
  comment as potential misinformation"). Prefers extremely long, self-documenting
  method/variable names over a short name + comment
  (e.g. `isLeastRelevantMultipleOfLargerPrimeFactor`).
- Ousterhout: would write 5–10x more comments than Martin for the same code. Argues
  long self-documenting names are themselves a tax (they still require parsing, and
  once cryptic enough, need a comment anyway) and that comments carry qualitative,
  causal information ("why") that no identifier length can substitute for. Central
  quantitative claim (Ousterhout's own estimate, not measured): "the cost of missing
  comments is easily 10–100x the cost of incorrect comments" — i.e., the failure mode
  of *no comment* is worse than the failure mode of *a comment that's slightly wrong
  and gets fixed later.*
- Structural critique Ousterhout makes of *Clean Code* itself: its comments chapter
  spends roughly 15 pages on bad comments vs. 4 on good ones, which he argues creates
  an anti-comment bias in readers that isn't justified by the actual cost-benefit.

**CTO-defensible synthesis (for tradekit):**
1. Function length is not a proxy for quality; entanglement is the actual defect.
   Splitting is good only when each piece is independently understandable *and*
   independently correct-preserving (Martin's own regression is the cautionary tale —
   test behavior, not shape, per tradekit's existing TDD doctrine).
2. On comments, side with Ousterhout's empirical asymmetry claim (10–100x) as the
   controlling heuristic, but keep it disciplined: comments must describe what
   *isn't* obvious from the code (Ousterhout's own comments rule) — this rules out
   Ousterhout's own "5-10x more" as a target and instead makes density a function of
   actual non-obviousness, not habit. This is already tradekit's stated rule
   ("comments explain why, not what") — the debate sharpens *why* that rule is right
   and gives it a name-checkable source.

### 1.3 Empirical readability / defect research

- **Buse & Weimer, "Learning a Metric for Code Readability," IEEE TSE 36(4), 2010.**
  https://dl.acm.org/doi/10.1109/tse.2009.70 (preprint:
  https://web.eecs.umich.edu/~weimerw/p/weimer-tse2010-readability-preprint.pdf).
  120 annotators rated 100 Java snippets; a learned model of local surface features
  (line length, identifier/keyword density, nesting, comment presence) predicted human
  readability judgments better than an average individual human rater, and the
  resulting readability score correlated with independent defect reports and code
  churn. **Evidence-grade**, but the model is about *surface* features (structure,
  density) — it does not evaluate comment *content* quality, so it cannot adjudicate
  the Ousterhout/Martin content dispute; it does support the general claim that
  readability (as judged by humans) is measurably linked to defect rates.
- **McConnell, *Code Complete*, 2nd ed. (2004), ch. 7 ("How Long Can a Routine Be?").**
  Reviews multiple decades-old studies (cited secondhand via
  https://dubroy.com/blog/method-length-are-short-methods-actually-worse/ and Code
  Complete's own text) and concludes routines of 100–200 lines are **not** more
  defect-prone than shorter ones once you control for complexity — length alone is a
  weak defect predictor; nesting depth, decision-point count, and variable count
  matter more. **[UNVERIFIED-RECALL: exact defect-rate figures ("1-25 defects per
  KLOC") are widely cited from McConnell but not independently re-verified here —
  treat as textbook synthesis, not primary data.]** This directly undercuts a
  mechanical "functions must be under N lines" rule of the kind Martin proposes.
- **Comment density vs. maintainability:** an empirical large-scale study of 5,229
  open-source projects (cited via search, not independently re-fetched — flag as
  **[UNVERIFIED-RECALL]** on the exact figure) reports "successful" OSS projects
  cluster around ~18.67% comment density, stable across project/team size — weak
  evidence that *some* consistent commenting norm correlates with project health, but
  this is correlational and doesn't establish causation or optimal density.
  Maintainability-index studies using comment density as one input report high
  correlation coefficients (R≈0.89) but the "Maintainability Index" metric itself has
  been criticized as poorly calibrated — see Arie van Deursen, "Think Twice Before
  Using the 'Maintainability Index'" (2014),
  https://avandeursen.com/2014/08/29/think-twice-before-using-the-maintainability-index/.
  **Verdict: comment-density-as-a-target is not well-supported; treat as opinion-grade,
  not a rule to encode.**
- **Comment-code consistency and bugs:** "Investigating the Impact of Code Comment
  Inconsistency on Bug Introducing" (arXiv 2409.10781) — stale/inconsistent comments
  (the "what"-comment that drifts from the code it describes) are associated with bug
  introduction. This directly supports banning changelog/narration comments that go
  stale, and supports why-comments (rationale rarely goes stale) over what-comments
  (restate current code state, which drifts).

### 1.4 Google engineering practices

- Source: Google Engineering Practices / Code Review Developer Guide,
  https://google.github.io/eng-practices/review/ and
  https://google.github.io/eng-practices/review/reviewer/standard.html.
- **Readability certification:** at least one reviewer on any CL touching a language
  must hold a per-language "readability" certification — a track record showing they
  can judge idiomatic, maintainable code in that language. This institutionalizes
  readability as a distinct, trained skill rather than a vibe check.
- **"There is no perfect code, only better code."** Reviewers should approve a CL once
  it improves overall code health, rather than blocking on cosmetic polish — directly
  relevant to *not* demanding exhaustive commenting/defensive coverage as a merge gate.
- **Small CLs, fast review** (from broader Google guidance, not the standard.html page
  specifically): small, focused changes get reviewed faster and more thoroughly;
  this is the review-latency argument for keeping diffs minimal and avoiding
  speculative scope creep in a single change — directly supports tradekit's existing
  "Surgical Changes" principle.
- **Transfer to a solo-human + AI-agents team:** the "readability certification" role
  maps to the CTO/human review gate tradekit already requires before money-path
  commits — one qualified reviewer per language/domain is the minimum bar, not every
  contributor.

### 1.5 AI-generated code style problems (2024–2026, industry writing)

- Sonar's 2026 developer survey (cited via search) reports AI-generated/assisted code
  share rising from ~6% (2023) to ~42% (2026) of committed code — the scale argument
  for codifying rules now rather than case-by-case review.
  **[UNVERIFIED-RECALL: exact survey figures not independently re-fetched from
  primary Sonar report; treat as reported-secondhand.]**
- "AI Code Editing Gone Too Far: Stop Over-Editing Now" (dev.to, 2025/2026,
  https://dev.to/onsen/ai-code-editing-gone-too-far-stop-over-editing-now-444m):
  documents the "ask for a bug fix, get 3 rewritten files" failure mode — over-editing
  scope creep, unsolicited reformatting/renaming. This is the AI-specific instance of
  tradekit's existing "Surgical Changes" principle, and the same failure mode drives
  speculative-abstraction bloat (an unrequested "flexible" refactor bundled into a
  fix).
- No single canonical "AI comment style guide" was found as a discrete artifact in
  this pass — treat the "over-commenting/hedging comments/defensive bloat" framing as
  a widely observed but not yet formally codified industry pattern
  **[UNVERIFIED-RECALL: pattern is broadly reported in practitioner discourse (e.g.
  arXiv 2607.07980, "Opinions on Code Review in an AI World") but I did not find a
  single quotable named source enumerating "hedging comments" as a term of art]**.
  The practical implication: tradekit's own rule-writing (below) is itself the
  primary artifact, not a citation of someone else's finalized taxonomy.

---

## 2. Evidence vs. Opinion — honest labeling

| Claim | Grade |
|---|---|
| Complexity = dependencies + obscurity; deep/shallow modules | Opinion (Ousterhout's framework; internally consistent, widely adopted, not independently measured) |
| Forwarding wrappers are bad | Opinion, but already repo-canonical — treat as adopted policy, not open question |
| "Define errors out of existence" reduces defensive bloat | Opinion (design heuristic), plausible mechanism, not independently quantified |
| Comments should explain "why" not "what" | Opinion, near-universal industry consensus (Ousterhout, Martin, Google all converge here) — treat as closest thing to settled |
| 10-100x cost asymmetry (missing vs. wrong comments) | Opinion — Ousterhout's own estimate, not measured |
| Function length alone predicts defects | **Evidence says no** (McConnell's synthesis of older studies) — reject mechanical LOC caps |
| Readability (human-judged) correlates with defects/churn | **Evidence** (Buse & Weimer 2010) |
| Stale/inconsistent comments correlate with bug introduction | **Evidence** (arXiv 2409.10781) |
| Optimal comment density is ~18.67% | Weak/opinion-grade correlational claim, not a target to encode |
| AI-generated code trends toward over-editing / scope creep | Industry-observed, opinion/anecdote-grade in this search pass |
| Google readability certification improves code health | Institutional practice, not independently RCT-tested, but long-run adopted at scale — treat as strong practitioner evidence |

---

## 3. Draft Readability Rules (ready for repo adoption)

Numbered, one sentence each, WHY + source.

1. **A comment must state something the code cannot say for itself** (rationale,
   a non-obvious constraint, a why-not-the-obvious-approach) — never restate what the
   next line already shows.
   WHY: this is the one point of convergence across every source reviewed
   (Ousterhout's core rule; Martin's own "good comment" categories; Google's review
   guidance treats redundant comments as the default failure mode).
   Source: Ousterhout, *APoSD* ch. 13; Martin/Ousterhout debate,
   https://github.com/johnousterhout/aposd-vs-clean-code.

2. **Anti-pattern — narration comments** (`# increment i`, `# call the API`,
   `# return the result`): banned outright, no exceptions.
   WHY: pure "what" restatement; adds a line that can go stale without ever adding
   information (arXiv 2409.10781 on comment-drift-linked bugs).

3. **Anti-pattern — hedging comments** (`# this should work`, `# I think this handles
   the edge case`, `# TODO: verify`) are not permitted in committed code; resolve the
   uncertainty or file it in `tests/ASSUMPTIONS.md` instead.
   WHY: a hedge in a comment is an unresolved decision masquerading as documentation —
   tradekit's own ASSUMPTIONS protocol already exists for exactly this ambiguity and
   is the correct destination for it.
   Source: tradekit CLAUDE.md ASSUMPTIONS protocol (existing repo policy, not
   external).

4. **Function/method length is not a merge criterion; entanglement is.** Do not
   split a function solely to satisfy a line-count target; split only when each
   resulting piece is independently understandable without reading its sibling.
   WHY: McConnell's synthesis shows LOC alone doesn't predict defects; Ousterhout
   demonstrates (and Martin's own re-decomposition accidentally proves, via a 3-4x
   perf regression from rule-driven splitting) that mechanical extraction can make
   code *harder* to verify, not easier.
   Source: McConnell, *Code Complete* ch.7; Ousterhout/Martin debate (PrimeGenerator
   case study).

5. **No forwarding wrappers / no speculative abstraction layers** unless the module
   underneath genuinely varies (multiple real implementations) or the interface is
   independently useful today.
   WHY: a shallow module's interface complexity isn't repaid by its (near-zero)
   functionality; this is bloat with a good conscience.
   Source: Ousterhout, *APoSD*, deep-vs-shallow modules (already repo-canonical).

6. **Prefer designing invalid states out of existence over defensive branches that
   catch them.** Only write error handling for states that can actually occur given
   the caller's real contract.
   WHY: every defensive branch is a dependency the reader must verify was worth
   adding; unreachable-state guards are pure obscurity cost with no functional payoff.
   Source: Ousterhout, *APoSD*, "define errors out of existence."

7. **Docstrings state the contract (inputs, outputs, side effects, invariants), not
   a re-description of the implementation.** If the docstring and the function body
   say the same thing in different words, delete the docstring content that repeats
   the body.
   WHY: same why/what distinction as rule 1, applied to the interface-comment case
   Ousterhout specifically calls out (even private interfaces need contracts, not
   restatement).
   Source: Ousterhout, *APoSD* interface-comments discussion.

8. **A single diff/CL should not bundle unrequested refactors, renames, or
   reformatting alongside its stated purpose** — extend tradekit's existing Surgical
   Changes principle explicitly to AI-authored diffs.
   WHY: named as a specific, observed AI failure mode ("over-editing") distinct from
   human sloppiness — the fix scope creep this produces is functionally identical to
   speculative abstraction: work nobody asked for, paid for in review time.
   Source: dev.to, "AI Code Editing Gone Too Far: Stop Over-Editing Now" (2025/26);
   tradekit CLAUDE.md Surgical Changes principle (existing).

9. **At least one reviewer (human or designated top-model subagent role) must
   explicitly evaluate readability as its own review dimension**, separate from
   correctness/tests passing.
   WHY: Google's readability-certification practice treats readability as a distinct,
   trained judgment call, not a byproduct of a green test suite — tradekit's existing
   review-round requirement for money-path code should name readability as one of the
   adjudicated dimensions.
   Source: Google Code Review Developer Guide,
   https://google.github.io/eng-practices/review/.

10. **Comment density is not a target metric** (no "must have N% comments" rule, no
    "every function must have a docstring" mechanical requirement) — density is a
    consequence of applying rule 1, not a goal in itself.
    WHY: the empirical support for any specific optimal density is weak/correlational
    (18.67% figure is descriptive of successful OSS projects, not causally validated;
    Maintainability Index critiques apply). Encoding a density target would
    reintroduce the "narrate everything" failure mode AI writers already have.
    Source: van Deursen, "Think Twice Before Using the 'Maintainability Index'"
    (2014); general absence of causal density research.

11. **Anti-pattern — changelog/PR-narration comments** (`# Changed on 2026-07-24 to
    fix bug #123`, `# Previously this used X, now uses Y`) belong in commit messages
    and PR descriptions, never in source.
    WHY: git already owns history; a comment duplicating it is guaranteed to go
    stale the next time the line changes, and is a "what happened" comment, not a
    "why it's this way" comment.
    Source: rule 1's why/what distinction, applied; general version-control practice
    (not independently sourced beyond the why/what taxonomy above).

12. **High-value comment types to keep:** rationale for a non-obvious choice,
    documented invariants/preconditions a caller must uphold, cross-references to an
    issue/ticket/ASSUMPTIONS entry that explains a workaround, and warnings about
    known quirks in a dependency (tradekit CLAUDE.md already has the dependency-quirk
    example: `ttl=0` / `conn.query()` params-cache bug).
    WHY: these are exactly the categories that survive scrutiny in every source
    reviewed — they encode information genuinely absent from the code text itself.
    Source: synthesis of Ousterhout (rationale/interface contracts), Martin (comments
    that "verify code against intent"), tradekit CLAUDE.md existing example.

---

## 4. Sources

1. Ousterhout, J. *A Philosophy of Software Design*, 2nd ed. Yaknyam Press, 2021.
   Overview: https://web.stanford.edu/~ouster/cgi-bin/aposd.php
2. Ousterhout, J. & Martin, R.C. *APoSD vs. Clean Code* (joint debate document, 2024-25).
   https://github.com/johnousterhout/aposd-vs-clean-code
3. Book Overflow podcast, "John Ousterhout and Robert 'Uncle Bob' Martin Discuss Their
   Software Philosophies." https://podwise.ai/dashboard/episodes/4193026
4. Third-party recap: "APoSD vs Clean Code, a debate" (2025-02-25).
   https://tryingthings.wordpress.com/2025/02/25/aposd-vs-clean-code-a-debate/
5. Martin, R.C. *Clean Code: A Handbook of Agile Software Craftsmanship*. Prentice
   Hall, 2008. (Referenced via debate document; not independently re-fetched.)
6. Buse, R.P.L. & Weimer, W. "Learning a Metric for Code Readability." *IEEE
   Transactions on Software Engineering* 36(4), 2010.
   https://dl.acm.org/doi/10.1109/tse.2009.70 ·
   preprint: https://web.eecs.umich.edu/~weimerw/p/weimer-tse2010-readability-preprint.pdf
7. McConnell, S. *Code Complete*, 2nd ed. Microsoft Press, 2004, ch. 7. Discussion:
   https://dubroy.com/blog/method-length-are-short-methods-actually-worse/
8. van Deursen, A. "Think Twice Before Using the 'Maintainability Index'" (2014).
   https://avandeursen.com/2014/08/29/think-twice-before-using-the-maintainability-index/
9. "Investigating the Impact of Code Comment Inconsistency on Bug Introducing."
   arXiv:2409.10781. https://arxiv.org/pdf/2409.10781
10. Google. *Code Review Developer Guide* / Engineering Practices.
    https://google.github.io/eng-practices/review/ ·
    https://google.github.io/eng-practices/review/reviewer/standard.html
11. "AI Code Editing Gone Too Far: Stop Over-Editing Now." dev.to, 2025/2026.
    https://dev.to/onsen/ai-code-editing-gone-too-far-stop-over-editing-now-444m
12. "Opinions on Code Review in an AI World: Building Causal Theory from Practitioner
    Discourse." arXiv:2607.07980. https://arxiv.org/pdf/2607.07980 (context only,
    not directly quoted)
13. tradekit `CLAUDE.md` (repo, existing) — forwarding-wrapper ban, "comments explain
    why not what," Surgical Changes principle, ASSUMPTIONS protocol — cited as the
    existing policy this research extends, not an external source.

**Unverified-recall flags present in this doc (do not treat as confirmed without
re-fetching primary source):** McConnell's exact defect-rate figures (section 1.3);
the 5,229-project / 18.67% comment-density figure (section 1.3); Sonar's 2026
AI-code-share survey percentages (section 1.5); the claim that no single named
"AI comment style guide" artifact exists (section 1.5, absence-of-evidence caveat).
