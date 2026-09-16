# Skills-bank hypothesis: telemetry survey (2026-09-16)

Mission: test Mike's hypothesis — "agents are so quick to write scripts directly and
run them in the terminal ... likely it called the wrong tool or piping parameter, so
it fails in the terminal the first or second time, and you're tweaking and
re-running it ... often you're writing the same or similar scripts" — against this
project's own Claude Code session transcripts. Proposed fix under test: a per-project
script/util bank, indexed by name/parameters/function, that agents must save to and
look up in.

Method note up front: the raw transcript store is NOT 17-19 independent sessions.
Claude Code desktop forks/checkpoints a conversation into a new session `.jsonl`
under a new session id, and the new file re-embeds the parent's entire history
(lines carrying the parent's `sessionId`) plus its own new lines. Treating each file
as an independent session would count the same tool calls 2-4x. All counts below are
de-duplicated to distinct conversation lineages (see CORPUS).

## CORPUS

- Primary location checked: `C:\Users\admin\.claude\projects\C--Users-admin-dev-tradekit\*.jsonl`.
  Found 19 `.jsonl` files, ~54 MB total, file-mtimes 2026-09-05 to 2026-09-16;
  the per-session subdirectories alongside them (attachments, not transcripts) date
  back to 2026-07-12, meaning some lineages were checkpointed/resumed over ~2 months.
- Secondary location checked per the mission brief:
  `C:\Users\admin\AppData\Local\Temp\claude\C--Users-admin-dev-tradekit\**`. Confirmed
  this holds only per-session **scratchpad** directories (temp files agents wrote
  during tool use, e.g. this survey's own `387f000f-.../scratchpad/`) — zero `.jsonl`
  transcripts. Not a transcript source; not used further.
- Excluded 2 files as in-progress meta-task sessions dated 2026-09-16 (this survey's
  own session, plus the orchestrating "main" session that dispatched it) — including
  them would measure the act of running this survey, not organic dev work.
- De-duplication: inspected the `sessionId` field distribution per file. Files whose
  lines are >80% a foreign `sessionId` are forks/checkpoints of that parent; the
  fork with the most total lines per lineage was kept as the representative (it is a
  superset of the parent's history plus more). This collapsed 17 remaining files into
  **8 distinct lineages** (~24.8 MB): `6ba713ea`, `378a07c8`, `7d8edc55`, `fffbb6d3`,
  `234146ee`, `d33c557d`, `d6bfd848`, `be2228b3`.
- Sampling: none needed beyond the de-duplication above — all 8 representative files
  were parsed and tallied in full (no truncation), via a one-off Python script run
  through `rtk proxy python3` (kept in the session scratchpad, not committed).
- Schema used: each transcript line is one JSON record; `message.content` is a list
  of blocks; `tool_use` blocks with `name` in `{Bash, PowerShell}` carry the command
  in `input.command`; the matching `tool_result` block (by `tool_use_id`) carries
  output text and sometimes an `is_error` flag or a leading `"Exit code N"` line.

## MEASUREMENTS

total_bash_powershell_calls_deduplicated_corpus: 657
n_script_shaped_calls (heredoc / `python -c` / `-Command "..."` / >=4 chained statements): 314
n_script_shaped_share_of_total: 47.8%
n_readonly_oneliner_calls (ls/cat/grep/git status/git log/...): 127
n_readonly_oneliner_share_of_total: 19.3%
n_other_oneliner_calls (single-statement, not read-only): 216
n_other_oneliner_share_of_total: 32.9%
n_script_calls_flagged_by_automated_error_markers: 11 (3.5% of script-shaped calls)
n_flagged_calls_confirmed_false_positive_on_manual_read: 3 (benign nonzero exit / deliberate negative test / truncated-text mismatch)
n_flagged_calls_confirmed_real_tool_or_workflow_mistake_with_immediate_next-call_fix: 3 (git commit before git add; missing package extra needing `uv sync`; bash `mv` Permission denied fixed by switching to PowerShell `Move-Item`)
n_flagged_calls_confirmed_real_script-syntax_bug_not_retried_in_window: 2 (both the same bash-heredoc "unexpected EOF while looking for matching quote" class, from an unescaped apostrophe inside a `cat >>file <<'EOF'` body — same session lineage, two separate occurrences)
n_flagged_calls_real_code-content_bug_not_tool-misuse: 2 (undefined variable written into a test edit; a runtime Traceback surfaced mid-debugging)
verified_retry-and-fixed_rate: 3 / 314 script calls = 1.0%
verified_any_confirmed_stumble_rate (excludes false positives): 8 / 314 = 2.5%
median_attempts_to_working_for_confirmed_retry_pairs: 2 (fail once, succeed on the very next call, all 3 cases)
automated_similarity-based_retry_detector_result (ratio>0.6, window<=6 calls): 0 events in dedup corpus (undercounts: real retries here switched tool/approach rather than re-running near-identical text, so a text-similarity detector misses them — confirmed only by manual reading)
approx_token_cost_of_the_5_confirmed_real_failure_events (chars of failing command + its output, /4): 9,793 tokens total
approx_token_cost_per_session_average: 9,793 / 8 = 1,224 tokens/session
approx_token_cost_method: sum(len(command)+len(result_text)) over the 5 confirmed real-failure calls (the 3 fix-pairs' failing call, plus the 2 abandoned heredoc bugs), divided by 4 chars/token; two of the five (the heredoc bugs) dominate the total because the failing command embedded a large multi-KB document (24,104 and 8,852 chars respectively) that was lost whole on failure
scripts_dir_files_committed: 28 (`.py`/`.ps1` files in `scripts/`)
scripts_dir_files_matching_a_recurring_cluster_below: 0

## RECURRING CLUSTERS

Counted across the 8 de-duplicated lineages; "sessions" = distinct lineages a
keyword-matched script-shaped command appeared in (not raw file count).

| what it does | sessions | occurrences | representative snippet | already in scripts/? |
|---|---|---|---|---|
| run the pytest+ruff+mypy gate | 7 | 134 | `uv run pytest -q && uv run ruff check . && uv run mypy` (matches CLAUDE.md's own one-line `gate:` definition) | No script; already a documented one-liner in CLAUDE.md |
| read dev-log / handoff docs, or append a dev-log/ASSUMPTIONS entry | 6 | 60 | `cat >> tests/ASSUMPTIONS.md << 'EOF' ... EOF` | No |
| check collector/watchdog process + scheduled-task health | 3 | 29 | `schtasks /query /tn "TradeKit Tick Collector" 2>&1 \| tail -3` | No (scripts/collector_watchdog.ps1 exists but does the watching, not the ad-hoc status check) |
| count/inspect parquet part files in the archive | 3 | 23 | `find /d/tradekit-data/ticks -name "trades-*.parquet" \| wc -l` | No |
| parse/append a digest or handoff file | 2 | 21 | `ls docs/digest \| tail -5` | No |
| git worktree create/inspect/teardown | 2 | 16 | `git -C tradekit worktree add .claude/worktrees/x -b task/x <sha>` | No |
| scheduled task state (`schtasks`/`Get-ScheduledTaskInfo`) | 3 | 16 | `$i = Get-ScheduledTaskInfo -TaskName "TradeKit Paper Cadence"; ...` | No |
| parse this project's own `.jsonl` session transcripts | 4 | 7 | `for f in glob.glob(DIR+"/*.jsonl"): for line in open(f): rec=json.loads(line)...` | No (this survey had to write its own each time, same as prior sessions) |
| tally/fix line endings or inspect `.claude.json` config | 2 | 6 | `python -c "import json; d=json.load(open(r'C:\Users\admin\.claude.json'))..."` | No |
| log a friction entry | 2 | 2 | `python "C:/Users/admin/.claude/skills/tk-friction/scripts/friction.py" --title ... --symptom ... --cause ... --solution ...` | Yes — already a real, indexed script (`tk-friction`), just not counted as "scripts/" since it lives under `.claude/skills/` |
| disk/space check | 1 | 1 | `df -h /d \| tail -1` | No |

Only one cluster (friction logging) is already backed by a real, discoverable
script — and it is discoverable precisely because it is wired into a **skill**
(`tk-friction`), not because it sits in `scripts/`. Every other repeating cluster is
a short, cheap, already-successful read-only inspection query; `scripts/` itself is
100% production data-collection/backfill/compaction code and doesn't overlap with any
of these developer-diagnostic clusters at all.

## VERDICT ON THE HYPOTHESIS

**Partly supported, and the part that IS supported is the cheap part.** The
"same/similar scripts get rewritten across sessions" observation is real — the top
cluster (the pytest/ruff/mypy gate) recurs in 7 of 8 lineages and dev-log/handoff
reads in 6 of 8 — but the "fails the first or second time and you're tweaking/re-running
it" mechanism is not: of 314 script-shaped invocations across the de-duplicated
corpus, only 3 (1.0%) show a confirmed real failure immediately fixed by the very
next call (median 2 attempts, as claimed), plus 2 more real bugs (both the same
bash-heredoc quoting trap) that were abandoned rather than retried. The other 8 of 11
automated failure flags were false positives once read by hand — an automated
"exit code / error string" scan alone overcounts failures roughly 3x for this
codebase's mix of intentional TDD-red commits and deliberate negative tests.

## CHEAPEST FIX

Given the numbers, a full mandatory script bank (write discipline + a lookup step
before every terminal action) is the expensive answer to a problem that mostly isn't
happening: real tool-misuse failures are ~1% of script calls here, already fixed
in one extra call, and cost an estimated ~1,200 tokens/session — noise against
session sizes in the hundreds of thousands of tokens. What IS real and cheap to fix:
(1) the gate command is already the project's de-facto indexed one-liner (it's
printed verbatim in `CLAUDE.md`) — that pattern already works, just extend it with
2-3 more one-line "canonical command" entries for the next-highest clusters (dev-log
tail, scheduled-task status, collector/parquet freshness check) rather than building
new infrastructure; (2) the one genuine recurring bug worth documenting is the
bash-heredoc "unexpected EOF while looking for matching quote" trap (hit twice, and
expensive when it hits a large embedded document — 24KB and 8.8KB lost on the two
occurrences here) — add one line to CLAUDE.md's traps/rules next to the existing
heredoc-backslash-escaping warning, not a script. A full indexed script bank is not
justified by this data; a couple of documented one-liners next to the existing
`gate:` line is.

## FLAGS

- Script vs. one-liner classification is regex-based (newline present, heredoc
  marker, `python -c`/`-Command`/`pwsh -c`, or >=4 chained `&&`/`;`/`||`
  statements). Borderline multi-statement one-liners could be argued either way;
  the 47.8%/19.3%/32.9% split should be read as approximate.
- Automated failure detection needed hand-verification to be meaningful: a naive
  scan for "error"/"Error:"/"ERROR" substrings over-fires on grep output and log
  greps; a narrower marker set (explicit shell/interpreter syntax errors, missing
  modules, permission errors) still caught 3 benign cases that required reading the
  actual transcript text to rule out (a deliberate negative-test probe, a benign
  nonzero PowerShell exit with `-ErrorAction SilentlyContinue`, and one truncated-text
  mismatch). All 11 automated flags in the de-duplicated corpus were read by hand;
  this does not scale to a larger corpus without better heuristics.
- The automated near-identical-rerun retry detector (text-similarity > 0.6 within a
  6-call window) found 0 events in the de-duplicated corpus, undercounting: the 3
  confirmed real retries in manual review involved the agent *changing approach*
  (adding a `git add` step, running `uv sync`, switching from bash `mv` to
  PowerShell `Move-Item`) rather than re-running near-identical text, which a
  similarity metric will not catch. Treat the "0 automated retries" figure as a
  lower bound only; the manually-verified count (3) is the one to trust.
- The fork/checkpoint de-duplication (17 raw files -> 8 lineages) was inferred from
  the `sessionId` field distribution and spot-checked against embedded content
  (git commit messages, dated dev-log entries) for plausibility, not against
  Claude Code's internal fork/checkpoint implementation directly — if that mechanism
  works differently than inferred, the "8 sessions" figure could be off by a file or
  two, though the qualitative conclusion (raw file count heavily overstates distinct
  work sessions) would still hold.
