# Agent metrics — producing-agent assessments per review round

Accumulating register: one section per review round. Defect counts are those
attributable to the agent's own scope (a test gap that fails to catch an
implementation bug counts against BOTH agents).

## Round 1 — 2026-07-12 — P0 M0.2/M0.3 (commits d446ffb, 5f93f15)

Reviewer: code-reviewer agent. Verification: `uv run pytest` (49 passed),
`uv run ruff check .` (clean), `uv run mypy` (clean, 15 files). All defects
below were confirmed by executing reproduction scripts, not by inspection alone.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p0 | tests/ (38 test fns), ASSUMPTIONS.md | 1 (shared) | 1 (shared) | 3 | B+ | Exemplary assumption-pinning discipline and assertion messages; but the golden-path bias let the one HIGH through — quantize tested only on power-of-ten ticks, tamper tests cover only 2 of 7 hashed columns. |
| dev-p0 | src/tradekit/{contracts,ledger} | 1 | 3 | 3 | B | Clean architecture, deep-module discipline honored, FTS/hash/retry mechanics solid; but the G2 quantize guarantee is falsified for non-power-of-ten ticks, and two silent-coercion paths (naive datetimes, Decimal payloads) violate TD-17/ASSUMPTIONS-10 quietly. |

Shared defects: D1 (quantize grid — dev wrote the bug, tdd's tick coverage
missed it); D2 (EventFilter naive-datetime — ASSUMPTIONS never pinned
awareness on filters, impl inherited the hole).

Out-of-scope carried risk noted for the M0.1 producer (prior round, ungraded):
pyproject.toml claims deep-module import enforcement but
`ban-relative-imports = "parents"` does not ban cross-module absolute imports
of `_internals` (probe-verified). DESIGN §1 requires this lint "from day one".

## Round 2 — 2026-07-14 — P1A data layer (commits 7643c29..e85e083)

Reviewer: code-reviewer agent (Opus). Verification: `uv run pytest` (165
passed), `uv run ruff check .` (clean), `uv run mypy` (clean, 31 files).
Alpaca crypto response shape confirmed against Alpaca's own OpenAPI spec
(MultiBarsResponse: `bars` is an object keyed by symbol, not a list); cache
mixed-range behavior confirmed by executing a probe. Verdict: FIX-FIRST.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p1a (Sonnet) | stories 3-5 tests (cache, kraken, ratelimit) + ASSUMPTIONS 27-31 | 1 (shared) | 1 (shared) | 0 | B- | Kraken/ratelimit unit pins are exemplary (real Kraken body shape, fake-clock discipline, no-real-sleep structural pin). But the cache suite never tests a MIXED closed+live range — exactly story 3's headline "only the live bar refetches" — so the write-only-in-production gap shipped green; and ratelimit is pinned only in isolation, nothing asserts it is wired into any provider, letting the orphan through. |
| dev-p1a (Sonnet) | stories 3-5 src (cache.py, kraken.py, ratelimit.py, errors.py, port.py) | 1 (shared) | 3 | 1 | B- | Kraken normalization (pair-spelling split, epoch→aware-UTC, Decimal-via-str) is clean and the range-guard-before-HTTP is correct. But ratelimit.py is dead code (no provider imports it), the cache serves cached closed bars only when `end` lands exactly on a bar boundary (D-cache), Kraken maps every non-200 → ProviderUnavailable so HTTP 4xx never becomes ProviderRequestError despite its own docstring (D-taxonomy), and malformed 200 bodies raise untyped KeyError/InvalidOperation despite the docstring promising ProviderUnavailable (D-malformed). |
| tdd-p1a-2 (Sonnet) | stories 6-8 tests (alpaca, coingecko, port conformance) | 1 (shared) | 1 (shared) | 1 | C | The Alpaca crypto fixture uses a flat `{"bars":[...]}` list for BOTH equity and crypto, but the multi-symbol crypto endpoint returns `bars` keyed by symbol — the test pins the mock, not reality, and hid a live-API-breaking bug behind green (D-alpaca-crypto). The conformance suite also can't catch Decimal-from-float noise (the contract coerces float→Decimal, so the isinstance check always passes) and never asserts stale is False. Auth/env/pagination/taxonomy pins are otherwise strong. |
| dev-p1a-2 (Sonnet) | stories 6-8 src (alpaca_data.py, coingecko.py) | 1 (shared) | 2 (shared) | 0 | C+ | Equity path, env-var guards, timeframe map, and Decimal(str(x)) precision handling are correct. But the crypto path iterates `body.get("bars", [])` as a list; against the real symbol-keyed dict it raises TypeError on the first row — the crypto half of story 6 does not work outside the fixture (D-alpaca-crypto), and both providers inherit the non-200→ProviderUnavailable (D-taxonomy) and untyped-malformed-body (D-malformed) holes from the story-4 pattern. |

Shared defects: D-alpaca-crypto (HIGH — dev-p1a-2 coded the flat-list parse,
tdd-p1a-2's fixture shape hid it); D-ratelimit-orphan (HIGH — dev-p1a left the
module uncalled, tdd-p1a pinned it only in isolation); D-taxonomy /
D-malformed (MED — cross-provider, seeded by the story-4 Kraken pattern and
copied into Alpaca/CoinGecko).

## Round 3 — 2026-07-15 — P1B indicators + golden vectors (commits 31efe59..e519719)

Reviewer: code-reviewer agent (Opus). Verification: `uv run pytest` (255
passed at review time), ruff clean, mypy clean. Reviewer wrote its own
independent from-spec reference and recomputed 11 indicators against the
golden JSONs (all matched to rel 1e-9); confirmed by commit order that no
golden value could have been code-generated (goldens landed in red commits
while stubs raised NotImplementedError). Verdict: **PASS — first clean round
(zero HIGH) in three sprints.**

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p1b (Sonnet) | stories 1-3 tests + goldens + stubs (12 indicators) | 0 | 0 | 0 | A | Golden derivation via independent from-spec script (correctly rejected pandas_ta whose adjust=False seeding contradicts the pinned SMA-seed convention); hand cross-checks at every Wilder seed boundary; correct STOP on the two convention gaps it couldn't derive (supertrend initial direction, ADX seed window) — pinned them in ASSUMPTIONS instead of improvising. |
| dev-p1b (Sonnet) | stories 1-3 src | 0* | 0 | 0 | B+ | One pre-commit defect, caught by the frozen goldens exactly as designed: seeded ADX's Wilder smoothers with the SUM while using the average-form recurrence — invisible at the seed index (ratio of sums == ratio of averages), divergent after. On CTO push-back with exact arithmetic, verified and fixed cleanly. Its instinct to STOP rather than edit the test was correct procedure (diagnosis was wrong; commandment 4's track record holds). *Never reached review as a defect. |
| tdd-p1b-2 (Sonnet) | stories 4-5 tests + goldens + stubs | 0 | 0 | 0 | A | vwap golden spans UTC midnight with both zero-volume-bar cases; qfl vector exercises confirm-lag/active/crack/replace; extended ASSUMPTIONS 39 in place per instruction instead of duplicating. |
| dev-p1b-2 (Sonnet) | stories 4-5 src | 0 | 0 | 0 | A- | Clean first pass, 255 green; reused trend.sma for volume_ratio; documented its one judgment call (confirm-then-crack ordering) honestly. |

Review findings (all LOW, fixed same-day in e519719): LOW-1 invented QFL
acronym expansion in a docstring; LOW-2 silent misbehavior on degenerate
params (sma/bollinger period<1 -> numpy nan; swing/qfl k<1 -> vacuously-true
pivots) — guarded with ValueError + pinning tests; LOW-3 close-out items
(this file, dev-log, ROADMAP boxes).

Process note (what changed vs rounds 1-2): the CTO freeze gate — dual
independent derivation + external TA-Lib cross-check BEFORE the red commit
(ASSUMPTIONS 42/43) — converted the classic Wilder-seeding bug class from a
reviewer catch into an implementation-time catch. The one real defect this
sprint (dev-p1b's ADX seed scale) was caught by a frozen golden vector within
minutes, not by a review round days later.

## Round 4 — 2026-07-17 — P1C regime/scanner/sizing/correlation (commits 6e8b8a9..b4885a1)

Reviewer: code-reviewer agent (Opus). Verification: pytest 328 (at review
time), ruff/mypy clean, state-hygiene probes (cache.db row-count held,
data/models never created), pickle path-validation bypass attempts failed,
hand-recomputed Pearson/weekend-join/Kelly-ATR/EWMA arithmetic. Verdict:
**FIX-FIRST** (1 HIGH, 1 MED, 2 LOW) — fixed same-day, e988c01→b4885a1,
338 tests green after.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p1c (Sonnet) | batch A tests+stubs (macro, runtime seam, sizing verb, correlation) | 0 | 0 | 1* | A- | Exemplary flag discipline (schema ambiguities 47a/b escalated, not improvised). *Shared: its runtime test wrote through the REAL data/cache.db (caught by CTO gate pre-green-commit, not by review) — the seam-for-every-writer lesson now standing. |
| dev-p1c (Sonnet) | batch A src | 0 | 0 | 1* | A- | Clean first pass, 283 green; honestly reported the real-cache test design rather than papering over it. *Shared with tdd-p1c. |
| tdd-p1c-b (Sonnet) | batch B tests+stubs (regime) | 0 | 0 | 0 | A | Flagged 3 ambiguities (51-53) incl. inventing the Windows-backslash pickle vector test; EWMA/grid fixtures fully derivation-scripted. |
| dev-p1c-b (Sonnet) | batch B src (_regime) | 1 | 0 | 1 | B- | The HIGH: implemented the EWMA override with the POOLED feature mean as state_mean_vol while citing ASSUMPTIONS 54 (calmest-state pin) — threshold inflated ~4.8x, override under-fires (the dangerous direction). Its underlying calmest-state-vs-current-state adjudication request was legitimate and CTO-ratified; the defect is the silent mean-term substitution the docstring rationalized. Also LOW-2 (monitor-less model defaulted to converged). Caught by review because the planted spike (0.25/day) cleared either threshold — the discriminating marginal-spike test now exists. |
| tdd-p1c-c (Sonnet) | batch C tests+stubs (scanner) | 0 | 1 | 0 | B+ | Flag discipline again excellent (57a-f); the MED: three filter branches (rsi_min, macd_signal, atr_percentile_min) shipped with zero coverage — enumerated-fixture lists need a completeness check against the filter schema. |
| dev-p1c-c (Sonnet) | batch C src | 0 | 0 | 0 | A- | Died at usage cap ~95% done; landed work was defect-free. CTO finished (equivalence-test swap per its planned-obsolescence note + smoke_scan.py). |
| fix-p1c (Sonnet) | review-fix round | — | — | — | A | Discriminating-test geometry (constant trailing-30 return makes ewma_vol==r exactly, midpoint between the two candidate thresholds) proved the defect both directions before fixing. |

CTO-gate catches this sprint (pre-review): real-cache test pollution (batch
A, six fake BTC bars purged); Kraken pair-map gap for Mike's universe (live
smoke_scan crash → SOL/LINK/NEAR/TAO/EIGEN mapped, result keys verified
against the live endpoint).

Process notes: (1) the freeze-gate discipline held — every hand-derived
fixture re-derived independently before red commits; zero fixture defects
all sprint. (2) The one HIGH lived in exactly the code the sprint doc
pre-registered as Opus-gated (override logic) — the routing rule works.
(3) New standing rule from batch A: ANY module that writes files gets a
path seam and tests must tmp-path it.

## Round 5 — 2026-07-17 — P2 thesis lifecycle + policy engine (commits 23c3897..5b547be)

Reviewer: code-reviewer agent (Opus). Verification: full gate green (589 at
review time), state-hygiene probes, five-rule spot-audit vs §7.2, VOID
laundering analysis (probed the void-to-dodge-completeness path — blocked by
construction), R-016 numeraire-reconstruction scale-invariance verified
against _metrics field usage. Verdict: **FIX-FIRST** (1 HIGH, 1 MED, 2 LOW),
fixed same-day be4a8a8→5b547be, 594 green after.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p2 (Sonnet) | batch A tests+payloads+projection scaffolding | 0* | 0 | 0 | A- | 13 real payload models, suite-wide TK_DATA_DIR isolation, honest red/green accounting. *The unguarded transition map it scaffolded became batch B's flagged defect — designed-in, caught in-sprint by the next TDD agent. |
| dev-p2 (Sonnet) | batch A src | 0* | 0 | 0 | A- | Clean; validate-then-append ordering right. *Shared the unguarded-map defect. |
| tdd-p2-b (Sonnet) | batch B tests (grade/void) | 0 | 0 | 0 | A | Found the batch-A unguarded-transition bug while designing void sign-off; its LessonRecorded workaround was overridden (CTO) but the diagnosis was the valuable part. Applied 3 CTO adjustments cleanly. |
| dev-p2-b (Sonnet) | batch B src | 0 | 0 | 0 | A | Guarded transition tables in both derive paths; refused-void audit trail exact; honest frozen-core interface notes. |
| tdd-p2-c (Sonnet) | batch C tests+policy scaffolding | 0 | 0 | 0 | A- | Boundary-exact rule pins; four flags all ratifiable as proposed. |
| dev-p2-c (Sonnet) | batch C src | 1* | 0 | 0 | B+ | *Pre-review CTO catch: implemented a permissive fallback letting FABRICATED thesis_ids pass R-010/R-012 (the test fixture had never earned its allow). Flagged it honestly; on adjudication removed it, strengthened the fixture, added two deny pins. Never reached review. |
| tdd-p2-d (Sonnet) | batch D tests (series/promotion) | 0 | 0 | 0 | A | Freeze-gated expectancy/MDD fixtures; discovered the >=30-non-void redundancy; 11 flags all sharp. |
| dev-p2-d2 (Sonnet) | batch D src | 1 | 1 | 2 | B | The round's HIGH: series MDD equity base pooled ALL accounts (winning sibling dilutes a losing account's drawdown -> dirty series grades clean -> promotion opens; reviewer probe 0.0833 vs 0.25 vs 0.0333). Both derivations shared the bug so the agreement pin passed. Also the wall-clock projection MED. Its TradeRecord numeraire-100 reconstruction and window-anchoring calls were sound and ratified. (First attempt died at a usage cap; reverted cleanly to red, second agent finished.) |
| adversarial-p2 (Opus) | batch E scenarios | — | — | — | A | 11 ring-3 scenarios, real-verb driven, coverage-honest (P3-only vectors flagged); positive controls on the boundary rules. |
| fix-p2 (Sonnet) | review-fix round | — | — | — | A | Discriminating two-account fixture proved the HIGH both directions (0.0788 falsely-clean -> 0.1733 dirty); log-relative completeness restored projection purity. |

CTO-gate catches this sprint (pre-review): the fabricated-thesis-id
permissive fallback (batch C); the unguarded transition map (batch B TDD);
pnl-fabrication override (None, never 0); LessonRecorded-overload override;
dials-drift tripwire test added at batch-D gate.

Process notes: (1) the flag-don't-improvise pattern carried the sprint — 30+
flagged design calls, all adjudicated in ASSUMPTIONS before implementation
built on them; (2) the one reviewer HIGH lived in the pre-registered Opus
focus area (series accounting) for the third consecutive sprint — the
routing rule keeps earning its keep; (3) usage-cap deaths are now routine
and harmless: always `git status` + gate before assuming loss, revert
partial single-file work to the committed red rather than resuming
mid-thought.

## Round 6 — 2026-07-18 UTC — P3 paper trading/review/reporting (commits 6ab872a..425f000)

Reviewer: code-reviewer agent (Opus). Verification: full gate green (774 at
review), fill arithmetic hand-recomputed vs the costs tables, G5/lookahead
probes, token-forgery attempts, state-hygiene sweep. Verdict: **FIX-FIRST
(3 MED, 1 LOW — zero HIGH; the three-sprint HIGH streak in the
pre-registered focus area is broken)**. Fixes 3f207d9→425f000, 781 green.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p3 (Sonnet) | batch A (port/contracts/TD-24) | 0 | 0 | 0 | A- | Collapsed TDD/dev for declarative machinery (authorized); dial migration kept the $500 identity exactly. |
| tdd-p3-b / dev-p3-b (Sonnet) | batch B PaperBroker | 0 | 1* | 0 | A- / A- | Dev's shape-only token seam was proven wrong by the conformance suite (authored first, exactly as designed) — CTO pulled real verification forward; dev's stop-on-conflict was exemplary. *The remaining narrowness (thesis binding, no-newer-deny) became review MED-2. |
| tdd-p3-c / dev-p3-c (Sonnet) | batch C pipeline | 0 | 2* | 0 | B+ / B | Dev edited tests beyond authorization (all survived audit; process note issued). *MED-1 (halt-bypass via resting-limit polling) and MED-3 (one-directional reconcile) originate here. |
| tdd-p3-d / dev-p3-d (Sonnet) | batch D review module | 0 | 0 | 1 | A / A | Dev caught a LATENT P2 bug (void() ignored passed on sign-offs — a failed review would have permitted a void) and stop-and-flagged perfectly. LOW-1 subprocess cap. |
| tdd-p3-e / dev-p3-e (Sonnet) | batch E memory/report | 0 | 0 | 0* | A- / A- | *CTO-gate catches: repo-path report litter (state hygiene), six intra-batch stub-era CLI pins (third occurrence — pattern now named), one CTO over-flip corrected. Done-gate replay green end-to-end. |
| fix-p3 (Sonnet) | review fixes | — | — | — | A | All three MEDs with proven red-first discrimination. |

CTO-gate catches this sprint (pre-review): delayed-fuse macro tests (fixed-
date fixtures + real clock — new standing rule: gate check is "what happens
to this test in a month"); report-path litter; the token-verification
pull-forward; intra-batch stub-era pin churn (process cost of the
collapsed-batch pattern — next sprint: TDD agents must not author stub-era
CLI pins for verbs their own batch implements).

Process notes: (1) zero HIGH for the first time in a FIX-FIRST round — the
defect mass is migrating from money-math to interaction seams (halt x
polling, reconcile direction), which is what the adversarial-replay style
catches; extend ring-3 scenarios to seam interactions in P4. (2) Dev
stop-and-flag discipline is now reliably good; the batch-C overstep was the
exception and its process note landed. (3) 11 usage-cap deaths across the
project to date; all recovered without loss.

## Round 7 — 2026-07-18 — P4-paper (AlpacaBroker + seam hardening, commits 4f749a4..9b513fc)

Reviewer: code-reviewer agent (Opus). Probes: per-method credential deletion,
flood-kill timing, secret-value scan of the tracked tree (zero hits),
fixture-vs-capture byte comparison, mutation-reasoning on the seam
scenarios. Verdict: **PASS** (1 MED fixed same-day pre-live, 2 LOW).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tdd-p4a (Sonnet) | batch A tests (AlpacaBroker) | 0 | 0 | 1 | A- | Fixtures byte-faithful to the CTO capture; honest regression accounting on the routing change. LOW: stale red-phase docstrings. |
| dev-p4a (Sonnet) | batch A src | 0 | 1* | 0 | B+ | Excellent stop-and-flag on the reconcile-test hole; the fabricated-defaults degradation was REJECTED at the CTO gate (no-creds = loud everywhere) — the conformance harness was the real culprit and got fixed instead. *MED-1 (HTTP taxonomy) originates here; also its live rehearsal claim was env-blocked, CTO ran it (PASSED). |
| tdd-p4b (Sonnet) | batch B seams | 0 | 0 | 0 | A | Won the live_path adjudication with a better argument than the CTO's initial lean (narrow reading); collapsed split flagged honestly; flood-kill test empirically strong. |
| fix-p4a (Sonnet) | review fixes | — | — | — | A | Venue taxonomy with per-failure-mode proven reds (bare JSONDecodeError/KeyError/TypeError each caught). |

CTO-gate catches: fabricated read-verb defaults (rejected pre-review); the
conformance-builder ownership rule; the pre-captured-shapes discipline
(probe BEFORE fixtures — zero fixture-vs-reality divergences all sprint,
the first sprint with none).

Process notes: (1) Mike's background-agent + wakeup-ladder orchestration
pattern used for every dispatch this sprint — no blocking waits; adjudication
rounds turn in ~15-20 min. (2) The pre-registered-focus rule keeps paying:
MED-1 sat exactly in the named focus area. (3) Live remains structurally
unreachable: dial default-false + live-key env absent + two-man promotion +
live_path manual-resume — four independent locks.

## Round 8 — 2026-07-19 — P5-PROP batch A (prop dials + barrier simulator, 4343b0b..1c4cb14)

Reviewer: tk-reviewer (top model). Pre-registered focus: boundary/reset
semantics. Probes executed against the live engine (horizon leak, 00:30
equality), G1 ledger independently re-derived, trailing-MDD kill-check
verified on the golden numbers. Verdict: **FIX-FIRST** (2 MED fixed
same-session with new pins 152/153, 4 LOW: 2 fixed, 1 deferred-by-design
to batch B, 1 accepted).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| green-prop-A (Sonnet) | batch A src | 0 | 1 | 2 | A- | Venue-exact barrier/fee/RNG semantics both engines; caught the config.toml-vs-pin conflict itself and resolved via TD-24 precedent instead of editing the test (exemplary flag-don't-improvise). Docked: unguarded horizon leak (inconsistent result object). |
| CTO red (Fable) | batch A tests/pins | 0 | 1 | 1 | A- | Cent-exact hand-derived goldens with real kill power; docked: wrong 00:30-inclusivity docstring pin, weak largest-rung assertion (accepted LOW). |

CTO-gate catches: goldens re-derived independently pre-freeze (all
confirmed); ASSUMPTIONS 143 amended rather than silently diverging from
the shipped config.toml behavior.

Process notes: (1) commit-gate hook and house (red) convention had
drifted — hook now exempts (red) commits; enforcement follows written
law, not vice versa. (2) The reviewer ran live probes, not just reading
— both MEDs were demonstrated, not conjectured; keep requiring that.

## Round 9 — 2026-07-20 — bridge-read feature review (fec24cc..6a08c16, fixes in next commit)

Reviewer: tk-reviewer (top model). Pre-registered focus: element-resolution
correctness + read-only discipline. 9 probes executed (P1-P7 + ordering +
CLI purity). Verdict: **FIX-FIRST** — 2 HIGH (split-brain resolver:
grade-vs-read divergence would have FALSELY graded C at the U4 gate;
ambiguity fall-through), 5 MED (boundary error typing, CLI catch gaps ->
exit 4 pinned, dead _pywinauto wiring, silent AC-12 stub, F6 tier-start),
2 LOW logged for T7/S1. All fixed same-session + discriminating tests
(866 green).

| Agent | Grade | Note |
|---|---|---|
| red-bridge-1 | B+ | clean goldens/flags; no path/ambiguity probes — both HIGHs invisible to its suite |
| red-bridge-2 | B+ | flag discipline + stream-purity pins; no adversarial fixtures; AC-8 test vacuous (LOW) |
| green-bridge-1 | C | resolver contradicts own docstring; 2/3 tiers; duplication = root cause of both HIGHs |
| green-bridge-2 | B- | correct on tested paths; solid import-guard diagnosis; dead stub wiring + bare errors across boundary |
| fix-bridge-read | A | all 7 items exactly as adjudicated, added the missing adversarial coverage, nothing weakened |

Process: reviewer ran live probes again (both HIGHs demonstrated). Lesson
for red dispatches: REQUIRE adversarial fixtures (ambiguity, malformed
rows, wrong-tier collisions) in the pin list, not just spec-named errors.


## Round 10 — hud-orderbook batch 1 (2026-07-19)
| Dimension | Grade | Note |
|---|---|---|
| Correctness | A- | golden arithmetic exact; fabricated thesis_id docked (fixed: interim prefix + rendered warning) |
| Safety | A | zero I/O/clock/execution; loud size_qty default |
| Test quality | B | AC-1 tab assertion + AC-6 exception path gaps (both fixed post-review) |
| Doctrine | B+ | seams sanctioned/real; sell-path + provenance now in T5 scope |
Per-agent: test-writer B+, implementer B (NotImplementedError trap caught at CTO gate), CTO fix round A-. Verdict: ACCEPT (pass-with-fixes, all MED fixes applied same round).

Round 10b — hud-orderbook batch 2 (tk hud CLI): CTO inline review. Correctness A (atomic write, clock seam, exit 4), safety A (advisory-only; size_qty loud default makes production `tk hud` fail loud until T5 — intended), test quality A- (writer caught nothing to flag; implementer correctly STOPPED on the basename collision instead of hacking import mode — exemplary). Verdict: ACCEPT.

## Round 11 — 2026-07-24 — TICKET-001 (red 8fb4b0c, green uncommitted, fix round in flight)

Reviewer: tk-reviewer (top model). Verification: gate self-verified (pytest
exit 0, ruff clean, mypy 90 files) + CTO gate in own shell. Verdict:
FIX-FIRST (1 HIGH, 2 MED, 3 LOW). Test tree byte-identical to red anchor —
no test-edit violation by implementer.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tk-test-writer (red) | 23 tests, 7 files | 1 (shared) | 1 (shared) | 1 | B- | Excellent P1-P3/P5 pins + the S1-catching un-mocked contract test; but under-pinned P4 (fixtures baked in the setup-collapse) and one vacuous header test (equity never asserted despite the name) — both holes the green walked through. |
| tk-implementer (green) | mae vocab/scanner, hud, contracts, CLI | 1 | 2 | 3 | B | Pin-faithful scanner/vocab/CLI work, zero test edits, good why-comments; but implemented P4's "composes scanner attrition" as a gate-rename collapse — hud discarded the scanner's per-filter telemetry, reproducing the exact blindness the ticket cures (killer filter: "setup" 11/11). |

Shared defect pattern (canonical, feeds the canon): the P4 gap was
test-shaped before it was code-shaped — an under-pinned red let a
plausible-but-wrong green stay green. Same lesson as the macd bug itself.
First round graded on the canon D3 readability dimension: both agents clean
(why-comments, no narration); reviewer flagged one load-bearing coupling
(_precompute_indicators/_evaluate_symbol_timeframe stage-order lockstep)
for a naming comment — folded into the fix round.

Round 11 fix round (focused re-review, ACCEPT): fix-round implementer grade
B — all four amendments landed, HIGH genuinely resolved end-to-end, but the
splice deviated from the ratified 163b "bars mapping" clause (doubled bars
stage) and the new test was blind to it; CTO applied the 2-line dedupe +
count assert directly post-ACCEPT, re-gated green. Remaining LOW carried to
batch 2: ledger append in hud_scan unguarded (unadjudicated — ASSUMPTIONS
164 covers only the log-file write).

Audit-quality note (2026-07-24): gating-filter-audit L3 adjudicated a FALSE
POSITIVE by the batch-2 red test-writer, CTO-verified (_rules._insufficient
emits outcome="fail" w/ field in measured; hud filter already surfaces it).
Swarm adjudicator (Sonnet) erred on L3; H1/H2/H3/M2/L1/L2 independently
confirmed. P5 withdrawn from SPRINT-AUDIT-BUNDLE.

## Round 12 — 2026-07-24 — SPRINT-AUDIT-BUNDLE money-path batch (red 794e9e1, green this commit)

Reviewer: tk-reviewer (top model), mandatory money-path round. Verdict:
ACCEPT (0 HIGH, 0 MED, 4 LOW — three folded into the commit by CTO, one
spun off as a follow-up task). P6 residual-hole probe answered clean: the
ValueError swallow set exactly equals the insufficient-context case
(derivation pre-filters exit<=entry; empty-log raise is the only reachable
swallow), so the narrowing adjudication holds.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tk-test-writer (red) | 14 tests, 6 files, ASSUMPTIONS 165-167 | 0 | 0 | 2 | A- | Rigorous hand-derived vectors; caught audit-L3 FALSE POSITIVE; correct keltner ASSUMPTIONS-FLAG; docked for the mis-fixtured P6 (could never green as written) and one unasserted verb-surface key. |
| tk-implementer (green) | contracts kind Literal, policy _MUTATING/_context, sizing/correlation/indicator guards | 0 | 0 | 2 | A | Surgical diff exactly to pins; correctly STOPPED on the mis-fixtured P6 instead of bending the implementation; honest schema-drift report. Guard-placement nit only. |

## Round 13 — 2026-07-25 — SCAN-AUDIT-LOG batch (red 1b77a13, green eca18ae) + keltner guard micro-batch

Keltner micro-batch (red 7600efd, green cff1d09, merged 7e72390): no formal
review round — 2-line pinned change, CTO-reviewed directly. Red writer A-
(correct module-path discrepancy handling, ASSUMPTIONS 168, correct red
reasons); green implementer A (exact pin, honest env-desync flag on the
worktree pywinauto mypy false-red, verified against pristine red state).

SCAN-AUDIT-LOG review: tk-reviewer (Opus), verdict SHIP-AFTER-FIXES.
Found 1 HIGH (F1: green's check-closure refactor silently dropped dual-RSI
tag emission — rsi_max+rsi_min both set used to emit oversold AND
overbought; changes regime pruning; no test covered dual bounds), 1
FIX-REQUIRED fidelity regression (F2: header degraded to symbol COUNT to
appease a fragile test slice — output weakened to satisfy a weak test
instead of flagging), 1 MED silent semantics move (F3: scan_ts end-read →
start-read under a "byte-identical" pin), plus T1/T2 test defects (header
test doesn't test the header; split-on-symbol slicing INDUCED F2) and the
unpinned slash-sanitization hole. No-recompute invariant, exhaustive-mode
independence, formula accuracy, utf-8 discipline all verified PASS.
CTO adjudications: F1 fix+dual-bounds test; F2 restore list + re-slice on
section markers + strengthen header test (ratified strengthening); F3
revert to end-read; slash pin added; F6 cosmetic text fix; F4 (scan_markets/
hud --audit wiring) deferred to follow-up task.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| tk-test-writer (red) | 12 tests B1-B5, output-root seam pin, 2 ASSUMPTIONS flags | 0 | 2 | 0 | C+ | Genuine no-recompute golden + clean seams/fixtures + both flags raised; but fragile split-on-symbol slicing induced the header regression, header test asserted the wrong region, ratified slash pin never written. |
| tk-implementer (green) | _scan_trace.py (315L) + scan() audit threading | 1 | 2 | 1 | C+ | Gate-clean, no-recompute honored, exhaustive semantics + utf-8 correct; but shipped a real B1 regression (dual-RSI tag drop) inside a "no behavior change" refactor, degraded header fidelity to satisfy a weak test rather than flagging, moved scan_ts read silently. Did flag header deviation in report (credit). |
| tk-reviewer (Opus) | full batch diff adversarial review | — | — | — | A | Pre-registered probes; caught the HIGH via dual-bounds reconstruction no test covered; correctly identified the test-induced-regression pattern (T2); verified all four PASS invariants with live log evidence. |

Round 13 addendum — T-AUDIT-2 wiring batch (red 8a16886, green 86633e7,
CTO fix 2640a82, merged 476fd6d): review-lite (CTO direct, non-money-path
mechanical wiring). Red writer A- (found the real hud->scan_setup->
scan_markets path, 13 tests at the right seams, 3 honest ASSUMPTIONS flags,
docked only for the coincidentally-green W4 noted in its own report). Green
implementer A- (exact adjudicated threading, justified Typer-vs-click
deviation documented in ASSUMPTIONS 169; missed the same-day re-tee hole the
CTO patched post-review: tee now snapshots pre-run audit logs).

## Round 14 — 2026-08-03 — SPEC-inkind-fees money-path batch (red 004a097+5bcfd53, green this commit)

Reviewer: tk-reviewer (top model). Verification: reviewer self-ran full gate
(pytest green, ruff clean, mypy clean 92 files); CTO re-gated post-fix.
Verdict FIX-FIRST — zero code-behavior defects; blocking items were AC-11
docs (undelivered at review time; CTO close-out duty) and one false comment.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-inkind | 7 test files, AC-1..10 | 0 | 0 | 2 | A− | Behavior-first, independently derived goldens, red-for-right-reason discipline; AC-8 anti-double-deduction trap exemplary. Docked: 0.005 sanity-literal typo, golden entry-fee weakness (both CTO-caught), unpinned avg_price. |
| green-inkind | 5 src files | 0 | 1 | 2 | A− | Surgically scoped, every pinned arithmetic path correct, backward compat at every reader, legacy events replay under recorded physics. Docked: false avg_price comment (MED, misleads exit-verb batch), undocumented 3+-fill semantic delta. |

CTO adjudications: golden entry fees_usd 0→realistic (strengthens, catches
double-subtraction); test typo 0.000005→0.005 (self-contradicting literal);
avg_price behavior ACCEPTED as venue-style fill price / comment REJECTED and
rewritten (ASSUMPTIONS 170.2); 3+-fill fee semantics pinned out-of-domain
(ASSUMPTIONS 170.3). Latent watch items (not defects): _alpaca side-default
routes missing-side crypto fills to in-kind branch; ManualBroker legacy
physics would double-count if it ever shared an account_ref with alpaca
in-kind fills (no such ref exists).

## Round 15 — 2026-08-03 — SPEC-wound-scale batch (red d1f50ff, green this commit)

Reviewer: tk-reviewer (top model). Verification: reviewer self-ran full gate;
CTO re-gated post-fix. Verdict FIX-FIRST — MED cluster, no fatal: bool-trap
untested (JSON true would have silently clamped to "minor" if the guard ever
regressed), false loudness docstring + first-stray-value silent tally in
score_exchanges, AC-9 docs absent at review time.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-wound | 5 test files, AC-1..8 | 0 | 2 | 0 | B+ | Discriminating lexicographic-trap test, boundary-via-public-verb, honest ASSUMPTION-FLAG + U1 probe; missed the bool trap, dangled the ASSUMPTIONS reference. |
| green-wound | review/_rubric.py, review/__init__.py, prompts schema block | 0 | 1 | 2 | A− | Minimal rank-based implementation, proactive bool guard, clean shared-taxonomy routing; docked for false loudness docstring and undeclared (justified) prompts-header edit. |

CTO fix round: True/False added to AC-6 parametrize; score_exchanges now
rank-validates EVERY exchange (first-per-category included) and the
docstring states it honestly; ASSUMPTIONS 171 (incl. ratifying the
malformed_output-taxonomy reading), GLOSSARY wound-scale entry. Blocking
invariance verified byte-identical; historical persisted int-severity events
have zero readers through the new code (policy/_context reads kind/artifact_id
only).

## Round 16 — 2026-08-03 — T-MTF-2 scan_confluence batch (red 7ce069b, green+fix this commit)

Reviewer: tk-reviewer (top model), self-ran full gate. Verdict FIX-FIRST:
1 HIGH (provider error escaped the verb — pinned error-map row unimplemented
AND untested; at cadence time a single 5xx would have killed whole funnel
runs), 3 MED (silent duplicate-timeframe overwrite, needless HMM loads on
zero-tag legs, kwargs-only test fake over-constraining call style). Fix
round landed all four + 2 new tests (13 total); CTO diff-checked and
re-gated green (full re-review waived — fixes implement the reviewer's own
prescriptions verbatim).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-mtf2 | test_scan_confluence_verb.py (11) | 1 (shared) | 1 | 0 | B | Behavior-first, real derived fixtures, exact warning pins, honest ASSUMPTION-FLAG; missed error-map row 2 entirely, kwargs-only fake violated refactor-survival. |
| green-mtf2 | _confluence.py + mae/__init__.py | 1 (shared) | 2 | 2 | B− | Genuine reuse (zero forks of evaluation logic), clean deep-module surface; skipped pinned provider containment, burned HMM loads against the module's own cited discipline, silent duplicate-tf collision. |
| fix-mtf2 | fix round (4 items) | 0 | 0 | 0 | A | All four landed cleanly, surfaced that scan() itself has NO provider containment (caller-contained at hud only) — a finding, not just a fix. |

Follow-up chip filed: extract shared filter-vocabulary validation helper
(logic forked between scan()/confluence — drift risk).

## Round 17 — 2026-08-03 — T-MTF-3 strategy registry (red 55b8c10, green+fix this commit)

Reviewer: tk-reviewer (top model), self-ran full gate (1133 collected =
main+10). Verdict FIX-FIRST: MED cluster — mae export pin missed (design's
own page), side not Literal, and the batch's defining catch: min_tags=0
made S1 UNCONDITIONAL under confluence semantics, which under T-MTF-4
first-match-wins would permanently shadow S2; reviewer proved min_tags=1 is
decision-identical to today's hud arm gate. CTO RE-ADJUDICATED S1 to
min_tags=1 (overriding the earlier 0 ruling). Also: one vacuous test
deleted, divergence differential test added, tests/ package plumbing
ACCEPTED (basename-collision fix), two-registries naming hazard resolved via
GLOSSARY (no rename — Surgical Changes).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-mtf3 | test_strategies_registry.py (10) | 0 | 2 | 1 | B | Exemplary ASSUMPTION-FLAG discipline + seam reuse; vacuous iteration test, missed the divergence probe its own min_tags flag begged for, re-introduced the kwargs-only fake round 16 condemned (CTO-widened). |
| green-mtf3 | mae/_strategies.py + tests/ __init__ plumbing | 0 | 2 | 1 | B− | Faithful minimal module, correctly refused to fix the broken differential test (right red-line instinct); missed two explicit pins on the design page it cites (mae export, Literal side). |
| fix-mtf3 | 5-item fix round | 0 | 0 | 0 | A− | All five landed cleanly; one wrong parting claim (strategies.py "does not exist" — it does) with zero consequence. |

ASSUMPTIONS 173 pins the re-adjudication + the T-MTF-4 non-empty-tags
prerequisite. Hygiene backlog: --import-mode=importlib (retire basename
collisions suite-wide).

## Round 18 — 2026-08-03 — STRATEGY-PACK S2 pullback (red fd86be4, green this commit)

Reviewer: tk-reviewer (top model), self-ran gate + mutant probes (>=-mutant,
band-widening mutant, float knife-edge checks) + digit-by-digit golden
re-derivation. Verdict ACCEPT — first clean verdict of the sprint. 1 MED
(pre-flagged S2-1: exclusive-side rsi_band boundary unexercised by bars —
ratified with residual, ASSUMPTIONS 174.3), 3 LOW (garbled docstring line
fixed at close-out; ema_above param loud-but-late per volume_spike
convention; regime_families-vs-tag-family latent tension deferred to
T-MTF-4).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-s2 | 3 test files, 22 tests | 0 | 1 | 0 | A | Hand-derived goldens all float-verified correct; vacuous-at-red trio honestly flagged; doc typo caught per precedent; escape hatch escalated, never improvised. |
| green-s2 | _scanner/_confluence/strategies/_strategies | 0 | 0 | 1 | A− | Surgical wiring, RSI series shared (no recompute drift), one shared validator pre-fetch in both verbs; docked one garbled docstring sentence. |

## Round 19 — 2026-08-03 — STRATEGY-PACK S4 + horizon_hours (red 80dc469, green this commit)

Reviewer: tk-reviewer (top model), self-ran gate (1172 passed) + independent
fixture re-derivation. Verdict ACCEPT (4 LOW, none blocking; F1/F2 comment
touch-ups folded into commit, F3/F4 carried to S3/cadence batches). The
round's substantive work was adjudication: red pinned "(1/2 tags)" against
ASSUMPTIONS 172.1's AND-kill semantics (corrected to 0/2), and two S2-batch
exact-registry pins broke on S4's append (relaxed to prefix/superset per the
round-13 fragile-pin lesson). Green implementer correctly STOPPED on both
rather than improvising — exactly the flag-don't-improvise discipline.

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-s4 | 2 test files, 17 tests | 0 | 1 | 2 | B− | Outstanding S4-1 flag (argued from the scanner's own tag table) + oracle-verified fixtures; shipped a warning expectation contradicting a 3-rounds-old pinned assumption, stale residue, one wrong band number. |
| green-s4 | _strategies.py + _thesis.py | 0 | 0 | 0 | A | Minimal faithful diff, exact money-param Decimals, load-bearing why-comments, stopped-and-flagged on both test defects instead of improvising. |

## Round 20 — 2026-08-03 — T-MTF-4 hud registry walk (red babcd49, green+fix this commit)

Reviewer: tk-reviewer (top model), self-ran gate twice + narrow-and-rerun
empirical probe. Verdict FIX-FIRST: 2 HIGH — (F1) broad except Exception
per def would have silently killed any future misconfigured strategy
forever (the repo's own S1-"bullish" wound class, re-opened); (F2)
attrition stages collapsed to [] on the walk path, regressing A-FIX-1/163b
explainability. Both fixed same-session (narrow ProviderError catch +
fixture fix; walk-synthesized stage dicts naming real killers). F3 (HMM
double-compute) + F5 (S2/S4 audit-invisible) ticketed as chips. Reviewer
incident: destructive git restore on the uncommitted review target,
reconstructed byte-faithful (CTO diff-verified) — friction logged
("stash before destructive probes").

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-mtf4 | test_hud_registry_walk.py (12) | 1 (shared) | 0 | 1 | B+ | Doc-pinned, five escape hatches flagged, fetch-count short-circuit pins exemplary; nothing-fires fixture missing 1h bars + wrong KeyError-tripwire rationale invited the broad except. |
| green-mtf4 | hud/_build.py | 2 | 0 | 1 | C | Conforming scope-disciplined walk, but silenced a fixture with except-Exception (silent-death class) and silently regressed attrition stages — both the anti-silent doctrine's core. |
| fix-mtf4 | 4-item fix round | 0 | 0 | 0 | A | All landed; stage-dict shape correctly matched to the existing consumer; mypy shadowing caught and resolved cleanly. |

## Round 21 — 2026-08-03 — SPEC-cadence T1+T2 joint money-path (reds a872e74+cb4c02e, green this commit)

Reviewer: tk-reviewer (top model), self-ran gate + full R-rule consumer walk
under the ratified _entry_price deviation + mutant analysis of the trigger
table. Verdict FIX-FIRST (narrow): 2 MED — trigger tests pinned only
equality touches (gap-through-stop ==-mutant survived; three CTO test
additions land with this commit) and the exit-freeze surface was
under-documented (R-009 freezes exits exactly when losing, R-007's daily
cap counts exits — both now ratified deliberate in ASSUMPTIONS 177.4 with
a MUST-re-examine-before-live flag). Notable green-stage judgment: the
implementer STOPPED on the CTO's fresh-price exit-reference adjudication
when it collided with side-blind R-rules (a fresh price would deny
profitable exits) and proposed _entry_price reuse — ratified as the
correct design (ASSUMPTIONS 177.3).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-cadence-t1 | 6 test files, 14 assertions | 0 | 0 | 0 | A | Hand-derived S4 bracket golden, disciplined flags, manual-path regression pinned. |
| green-cadence-t1 | contracts/_hud, _strategies, hud/_build, hud/_serve | 0 | 0 | 1 | A− | Spec-exact wiring, falsy trap avoided; docked for the silent build_state unknown-key fallback (asymmetry since ratified 177.5). |
| red-cadence-t2 | test_pipeline + test_exit_trigger (11) | 0 | 1 | 0 | B+ | Real-fixture discipline (real execute_order seeding, real R-001 halt); equality-only trigger table let an ==-mutant survive. |
| green-cadence-t2 | broker/_pipeline, broker/__init__, cadence/__init__ | 0 | 0 | 0 | A | execute_exit mirrors the gated shape faithfully; the fresh-price STOP-and-flag was exactly the money-path discipline the house wants. |

## Round 22 — 2026-08-03 — SPEC-cadence T3 runner (red 80c3af8, green+fix this commit)

Reviewer: tk-reviewer (top model), self-ran gate + guard/funnel bypass
probes + mutant analysis. Verdict FIX-FIRST: 1 HIGH (crash-silent
unattended runs — no digest trace of a failed run) + MED cluster (one
symbol's bar failure killed whole runs; grade coupled into exit's try
could orphan trades out of the promotion record; approved-orphan
accumulation under policy deny; unratified binding-evaluate deviation).
All four core guarantees (paper-only, funnel-only, drought-honest,
policy-gated) held in the happy path. Fix round landed all 8 items; the
binding-evaluate pin proved UNIMPLEMENTABLE literally (R-010/R-012 never
pass vacuously pre-draft) — fixer's evaluate-at-reviewed + reject-on-deny
redesign ratified (ASSUMPTIONS 178.2). CTO harness fixes: policy clock
seam alignment + bracket scale-consistency (both fixture defects the
implementer diagnosed precisely and refused to code around).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-cadence-t3 | test_run_once.py (8) | 0 | 2 | 0 | B+ | Real-verb end-to-end incl. the sprint-defining AC-4 round trip; missed the failure envelope entirely + two harness defects (clock desync, scale-blind bracket). |
| green-cadence-t3 | cadence, ledger accessor, hud refactor, script | 1 | 3 | 3 | B− | Clean happy-path composition + two exemplary STOP-and-flag diagnoses; shipped crash-silent unattended failure mode. |
| fix-cadence-t3 | 8-item fix round | 0 | 0 | 0 | A | Hit an unimplementable pin, proved WHY empirically (R-010/R-012 vacuous-deny), designed the correct alternative, flagged rather than forced — the round's best work. |

## Round 23 — 2026-09-06 — SPRINT-PREVIEW-DEFER (red 20125fa + 749fd21, green+fix this commit)

Reviewer: tk-reviewer (top model), self-ran gate (1421 tests, exit 0) +
crafted-verdict probes + a real-path M4 probe + 7 mutants. Verdict
FIX-FIRST on a MED cluster on the TEST side only: the two restrictions
that make the deferral narrow (rule set exactly {R-010, R-012}; measured
`insufficient_context:*` only) had no killing test — both mutants survived
the full suite, and the rule-set widening was reachable via a legitimate
`advisory:*` default_account_ref. No production defect: every crafted
verdict, the binding re-evaluation trace (cadence -> evaluate_policy_binding
-> policy.evaluate -> execute_order's own evaluate), and the deny-verdict-id
provenance trace all held. Fix round (CTO, in-thread): the duplicate T-A4
replaced by an 11-case predicate contract test (kills M2 + M4), `Any` ->
`RuleHit`. Process friction: the first reviewer parked on a background
pytest and appeared to return nothing; it did deliver on its second
notification — a redo dispatch was started and killed (docs/FRICTION.md).

| Agent | Scope | HIGH | MED | LOW | Grade | Note |
|---|---|---|---|---|---|---|
| red-preview-defer | test_build_state_preview_policy.py (4) + T-A5 | 0 | 2 | 1 | B | Real-path, no-mock harness that kills all/any, fabricated-id, and audit-line mutants; T-A5 is the seam-blind-spot guard the sprint needed. Left both A2 restrictions unpinned and T-A4 duplicated T-A1. |
| red-kraken-pairs | test_kraken.py (+2) | 0 | 0 | 1 | A | Parametrized request+parse pin plus a genuinely two-sided ZEC discriminator; every mapping mutant dies. |
| green-cto-inthread | hud/_build.py, mae/_data/kraken.py, ASSUMPTIONS 181 | 0 | 0 | 1 | A− | Surgical to the pins; predicate correct under every crafted verdict; `Any` where `RuleHit` was available. |
| review-preview-defer | round 23 adjudication | — | — | — | A | Found the real gap (unpinned narrowing, reachable) with a real-path probe, not opinion; clean bypass-hunt with cited paths; docked nothing — the background-park was a harness/process issue, now a dispatch rule. |
