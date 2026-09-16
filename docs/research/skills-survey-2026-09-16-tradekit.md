# Skills Survey — TradeKit friction/lesson corpus (2026-09-16)

Scope: this project only (`C:\Users\admin\dev\tradekit` + its project memory at
`C:\Users\admin\.claude\projects\C--Users-admin-dev-tradekit\memory\`). Read-only
reconnaissance; no code, docs, or git state touched other than this file. Sources
read in full or by targeted grep/read: `docs/FRICTION.md` (168 lines, read whole),
`cc-dev-log.md` (1292 lines), `docs/reviews/agent-metrics.md` (597 lines),
`tests/ASSUMPTIONS.md` (3644 lines), all 32 files in `docs/handoff/`, all 10 files
in `docs/research/` (deep-research-reports/ sub-corpus grep-only, see FLAGS), and
all 12 files in the project memory directory. Dedupe list checked against all 19
skills at `~/.claude/skills/`.

Every line-number citation below was independently verified with `Grep -n` against
the live file at write time (not taken on trust from first-pass extraction) — see
FLAGS for the one exception (a cc-dev-log line range used only for context, not as
a table citation).

## Skill candidates

| skill-name | description | locations | count | impact/complexity |
|---|---|---|---|---|
| subagent-claim-verification | Subagent reports of "it works," a measured number, or a status claim were repeatedly wrong — a quote-currency volume misread as USD, a "working" adapter that produced 0 rows, a stale failing-test count, wrong-cwd file writes — and every one was caught only by independently re-running or recomputing the claim, never by reading the report; a pre-acceptance verification checklist for grunt/dev dispatch reports would catch these before they cost a redo. | HANDOFF-2026-08-09-data-vacuum-expansion.md [198-218]; agent-metrics.md Round 1 [14-19], Round 2 [41-45], Round 11 [274] | 8 | IMPACT: HIGH (prevents wrong decisions built on unverified claims) / CPLX: LOW (checklist, no tooling) |
| irreversible-op-dry-run-check | A weekend-only sample used to justify a proposed ~10x archive downsample was off by 2.3x (real cut was ~23x, crypto book activity varies sharply by day-of-week) and nearly justified an irreversible delete with the wrong number before the actual dry run caught it; any estimate backing a destructive/irreversible action needs a same-tool dry run or a multi-day sample, never a one-day extrapolation. | FRICTION.md [30-33]; cc-dev-log.md [197-203] | 1 | IMPACT: HIGH (near-miss on irreversible data loss) / CPLX: LOW (one-line pre-flight rule) |
| secrets-hygiene-reminder | API keys (Kraken read-only, then Alpaca paper) were pasted directly into chat at least twice and only flagged for rotation after the fact; a standing pre-flight check ("never paste a secret into chat; if one lands there, rotate immediately, .env only") catches this at the moment instead of after exposure. | cc-dev-log.md [1206]; memory tradekit-project-state.md [20] | 2 | IMPACT: HIGH (credential exposure) / CPLX: LOW (one-line rule) |
| worktree-bootstrap-checklist | A fresh git worktree's `uv sync` silently installs only the default dependency group, so `pyarrow`/`websockets` (collector) or `pywinauto` (bridge) go missing and mypy/pytest report false failures that look like real regressions — twice, once blocking a commit-gate hook; always `uv sync --all-groups` in a new worktree and trust the main checkout's gate verdict when a worktree result looks wrong. | FRICTION.md [105-108], [159-162]; memory tradekit-working-rules.md [48-52] | 2 | IMPACT: MED-HIGH (blocks commits, false red) / CPLX: LOW (one setup step + one trust rule) |
| safe-write-for-backslash-content | A Bash-tool heredoc (even with a quoted delimiter) silently turns doubled backslash escapes into real newline/CR/tab bytes, corrupting Windows paths and Python f-strings; struck 4 times in one session (one landed in a commit and needed repair) and left older undetected typos sitting in ROADMAP.md and ARCHIVE-README.md. A one-line pre-write rule ("text with a backslash goes through Edit/Write, never a heredoc") plus a cheap post-edit CR/TAB byte scan ends this class of defect — consider a PreToolUse hook over a skill, since the failure mode is exactly forgetting to check. | FRICTION.md [9-13]; HANDOFF-2026-09-15-paper-record-compaction-automated.md [81-84]; memory bash-heredoc-unescapes-backslashes.md | 4 | IMPACT: MED (corrupted commits/docs, repeat offender) / CPLX: LOW (rule already drafted in memory) |
| money-decimal-rounding-quickref | The same three numeric-precision questions — banker's rounding vs. other modes, `Decimal(str(x))` vs. `Decimal(x)` for JSON floats, "round at application time not storage time" — get re-derived and separately CTO-ratified across many unrelated ASSUMPTIONS entries; a one-page money-arithmetic quickref lets a test-writer pin these by reference instead of re-litigating and waiting on ratification each time. | ASSUMPTIONS.md [5, 35] (ROUND_HALF_EVEN), [162] (Decimal(str(x))), [2855] (quantize at application time) | 3 | IMPACT: MED (saves repeated ratification cycles on money-path) / CPLX: LOW (reference doc, no new process) |
| boundary-semantics-quickref | Every new time/threshold contract re-asks the same question — is the boundary instant itself inside or outside the range — with a different answer pinned each time (some strict `>`, some inclusive both ends, one left deliberately unpinned); a default-and-override quickref ("anti-permissive: round toward breach unless flagged otherwise") cuts the back-and-forth CTO ratification this keeps costing. | ASSUMPTIONS.md [16] (since/until unpinned), [47-50] (AwareDatetime), [2926] (00:30 boundary EXCLUSIVE), [3273-3280] (ema_above strict `>` vs rsi_band inclusive both ends) | 4 | IMPACT: MED (recurring ratification cost on money-path gates) / CPLX: LOW (reference doc) |
| seam-fake-and-injection-conventions | A monkeypatched seam fake written kwargs-only (`def fake(**_)`) pins the production call convention and breaks on a legitimate positional-vs-keyword refactor; this exact defect recurred in three separate review rounds (16, 17, T-MTF-3) even after being promoted to project memory. Folding an explicit `(*args, **kwargs)` requirement into tk-tdd's SEAM rubric — a review-time check — would stop it recurring where a memory entry alone did not. | agent-metrics.md [396], [403], [425]; ASSUMPTIONS.md [2384] (dotted-string monkeypatch convention); memory test-fakes-any-call-convention.md | 3 | IMPACT: MED (recurred past a memory fix) / CPLX: LOW (one rubric line + reference) |
| vocab-drift-boundary-check | A scanner filter's own producing module emitted `macd_signal="bullish"` while the consumer only accepted `"bullish_cross"`/`"bearish_cross"` — same concept, drifted spelling — so the live scan silently matched nothing for 8 weeks with zero errors or warnings; the identical class of typo recurred a second time as a caught near-miss even after GLOSSARY.md was created specifically to prevent it. A boundary-crossing literal/enum cross-reference check (grep every emitter's value set against every consumer's accepted set before merging) would catch this before it ships silently. | cc-dev-log.md [769-775]; ASSUMPTIONS.md [3288]; docs/research/standards-2026-07/naming-vocab.md | 2 | IMPACT: HIGH (8-week silent production failure, recurred once more) / CPLX: MED (needs a real cross-reference step, not just a reminder) |
| windows-unattended-task-hardening | Windows Scheduled Tasks that looked perfectly healthy ("Ready" state, 8 collectors up) were actually dead for hours three separate times: a LogonType requiring an interactive session blocks headless boot; an action pointed at `pwsh` silently resolved to a zero-byte Store app-execution alias that Task Scheduler can't run; Python block-buffers stdout on kill so crash logs came back empty. Each cost hours of unrecoverable market-data collection and was found only by checking `LastTaskResult`, never by trusting "Ready." A pre-registration checklist (S4U logon type, full .exe paths never aliases, verify `LastTaskResult`=0 not state, launch with `python -u`) would catch all three before the next reboot. | FRICTION.md [25-28]; HANDOFF-2026-08-09-data-vacuum-expansion.md [244-257]; docs/research/data-health-2026-09-10-reboot.md [196-227] | 3 | IMPACT: HIGH (repeated hours-long unrecoverable data loss) / CPLX: MED (Windows-Task-Scheduler-specific, several surfaces) |
| silent-degradation-review-checklist | Five separate review rounds found a broad `except Exception`, a permissive fallback, or an unmapped error path that would have silently swallowed a real failure — non-200 HTTP folded into one generic error class, a fabricated `thesis_id` let through a policy gate, an unattended cadence run that could crash with no digest trace — each caught only by an adversarial reviewer reconstructing the failure path by hand. A standing reviewer checklist (grep the diff for bare `except`/fallbacks; confirm every error path is both taxonomy-mapped AND has a killing test) makes this systematic instead of luck-of-the-reviewer. | agent-metrics.md Round 2 [36-40], Round 5 [124], Round 16 [393], Round 20 [482], Round 22 [514-521] | 5 | IMPACT: MED-HIGH (money-path-adjacent error handling, 5 rounds) / CPLX: MED (reviewer procedure, several call sites per round) |
| subagent-cap-recovery | Dispatched dev agents died mid-task at their usage cap three times in one sprint; each was hand-recovered from its own transcript rather than losing the work and redispatching from scratch, but there is no written procedure for how to do that reliably — a short "resuming a capped subagent from its transcript" recipe would make this a known move instead of an improvised one each time. | cc-dev-log.md [1165], [1192], [1215] | 3 | IMPACT: MED (session continuity, avoids a full redo) / CPLX: MED (needs a real recovery recipe, not just a reminder) |
| pyarrow-native-ops-checklist | `repartition_archive`'s first version materialized a 41-column Arrow table via `to_pylist()` per row — 8.5 GB RSS, unfinished after 22 minutes on one symbol-day; rewritten to slice natively in Arrow it did the whole symbol (67.5M rows) in 40 seconds. A one-line reminder ("never `to_pylist()`/`to_pandas()` a full table for row-wise work in a repair/collector script; slice or compute in Arrow") would prevent the next data-pipeline script from repeating a ~30x-slower rewrite. | cc-dev-log.md [209-212] | 1 | IMPACT: LOW-MED (single incident, narrow surface) / CPLX: LOW (one-line convention) |

## ALREADY COVERED BUT STILL BITING

- **tk-tdd** already bans TAUTOLOGY/MOCK-THEATER/IMPL-COUPLED tests and requires
  "discriminating fixtures" and "survives a behavior-preserving refactor" — yet the
  exact failure classes it targets (fragile test slicing inducing a real regression,
  tests pinning call syntax instead of behavior, non-discriminating tests letting a
  mutant survive, vacuous/tautological tests) recurred across at least six separate
  review rounds spanning two months: Round 11 [270-274], Round 13 [318-337], Round
  16 [393], Round 19 [456], Round 21 [504], Round 23 [548], Round 24 [573-576] (all
  in `docs/reviews/agent-metrics.md`). Round 11's own text calls this "the canonical
  defect pattern," meaning the project has already named the recurrence and the
  rubric still isn't stopping it.
- **tk-gate** and **tk-implement**'s FIX stage exist precisely to route dispatched
  agents around `rtk`'s pytest-output filtering (which reads a collection ERROR as
  "No tests collected" and can drop the summary line even at 1314 tests passing) —
  yet a fix-round implementer burned ~300k tokens reverting production code to
  "prove red," re-applying it, then chasing the vanished summary line before being
  stopped by hand. The five guardrails that would have prevented this (tests-first
  no-revert, exit-code-only verdict, an explicit token budget line, stop-and-verify
  in the CTO's own shell, never gate while a reviewer mutates the same worktree)
  exist only in project memory (`tradekit-working-rules.md` [27-47]), not folded
  into either skill's text. FRICTION.md [15-18], [45-48]; agent-metrics.md [542]
  (background-parking), [588-589], [595] (~300k tokens).
- **tk-data-health**'s own workflow cites `scripts/health_snapshot.ps1`,
  `scripts/coverage.py`, and `scripts/audit_tree.py` as steps 1-3; FRICTION.md
  [164-167] and `HANDOFF-2026-09-15-paper-record-compaction-automated.md` [73] both
  record these as **not existing in the repo** as late as 2026-09-15, forcing an
  ad hoc manual workaround each time the skill was invoked. CORRECTED BY THE CTO 2026-09-16: all three exist
  and have since 2026-09-05/06, in the skill's own `scripts/` directory, which is
  what the skill's `scripts/<name>` references mean. Nothing was fixed; two
  sessions simply read the paths as repo-relative. The friction entry and the
  ROADMAP item were both wrong and are now closed.
- **tk-bootstrap**: `cc-dev-log.md` [615] explicitly suggests "a liveness check in
  tk-bootstrap" after a collector was found not running with nobody noticing.
  `tk-data-health` already answers exactly this question ("is the collector still
  running") but isn't wired into tk-bootstrap's session-start orientation, so a
  dead collector can go unnoticed between explicit tk-data-health invocations.

## NOT SOLVED INVENTORY

- FRICTION.md [100-103] — gitnexus FTS write fails on a read-only db even after
  reanalyze (2026-07-25); every Bash hook call spammed a retry warning.
- FRICTION.md [115-118] — Kraken Prop UI's OSO/bracket order flow does not work as
  OPERATIONS.md's step 3 describes (2026-07-23); the fallback manual SL/TP entry hit
  a unit mismatch and cost a realized ~$36.43 loss on a live account.
- FRICTION.md [120-123] — GitNexus FTS index version mismatch, db v42 vs. build v40
  (2026-07-23); same symptom family as the entry above.
- FRICTION.md [164-167] — `tk-data-health` cites three repo scripts that did not
  exist as of 2026-09-10 (see "ALREADY COVERED BUT STILL BITING" above for the
  2026-09-16 discrepancy).

## FLAGS

- The task brief states "the bootstrap hook reports 3 of these" open NOT-SOLVED
  entries, but a plain read of FRICTION.md's literal text found 4 (two of them
  GitNexus-related, dated four days apart). Did not find the hook's own dedup/report
  logic to explain the discrepancy — possible explanations: the two GitNexus
  entries are treated as one topic, or the data-health entry no longer counts as
  open (see next flag). Not resolved; listing all 4 as found in the text.
- RESOLVED BY THE CTO 2026-09-16: this flag was correct to raise and the reading
  was right. The three scripts were never missing — mtimes are 2026-09-05/06, so
  they predate the friction entry that declared them absent. The skill's
  `scripts/<name>` is skill-relative (tk-gate's convention); two sessions read it
  as repo-relative. `coverage.py --help` runs standalone; `audit_tree.py` raises
  ModuleNotFoundError on a bare `python` because it imports pyarrow and needs the
  project environment. Both facts are now in the skill itself.
- Two large sub-corpora were mined by a dispatched read-only sub-agent rather than
  read line-by-line by me directly: `tests/ASSUMPTIONS.md` (3644 lines) and
  `docs/reviews/agent-metrics.md` (597 lines). Every line number that ended up
  cited in the table above was independently re-verified against the live file
  with `Grep -n` before use; any pattern the sub-agent's first pass missed is not
  reflected here.
- `cc-dev-log.md` lines ~638-645 (reported account of GitNexus being fully removed
  from the project) came from a dispatched sub-agent's summary and were used only
  as narrative context in the "ALREADY COVERED" section's GitNexus aside — not
  independently re-verified by direct grep, and not used as a table citation.
- `docs/research/deep-research-reports/*.md` (a ~10-file sub-corpus of general
  trading/ops research) was grep-only, not read in depth — matches were generic
  industry advice ("common mistakes in algo trading"), not TradeKit-specific
  friction, so it was deprioritized under the breadth-over-depth instruction.
- Two dev-log-only findings (a concurrent-repair-tool near-miss at
  `cc-dev-log.md` [214-216], and an ISO-8601 string-vs-instant sort bug at
  `cc-dev-log.md` [204-208]) were considered and dropped from the table: both were
  caught by the project's own tests/locking before shipping, so they read as the
  existing process working correctly rather than a gap a new skill would close.
