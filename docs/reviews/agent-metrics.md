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
