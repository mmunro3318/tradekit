# Friction Log

Tool failures, environment desyncs, wrong-assumed API shapes, and their fixes.
Append-only, newest first below this line. NOT SOLVED entries are review bait —
tk-learn promotes solved+generalizable entries to global memory.

---

## 2026-08-10 — the watchdog task had no boot or logon trigger, and uv resolves only by accident `windows,scheduled-task,boot,ops`
- **Symptom:** Asked whether the pipeline restarts after a reboot. It does not, cleanly: the scheduled task's only trigger was a 15-minute repeating TIME trigger with LogonType=Interactive and StartWhenAvailable=False, so nothing collects until the user logs in, and then up to 15 minutes pass before the first run.
- **Cause:** The task was registered for steady-state babysitting, not for cold start — an easy thing to miss because it looks healthy in every check you would normally run (State Ready, LastTaskResult 0, 8 collectors up). Two further traps found in the same pass: D: is a USB disk (JMicron bridge) and resolve_data_root() silently falls back to <repo>\data when it is missing, so a run firing before USB enumeration would start all eight collectors writing to C: with no error; and the user PATH entry for uv is the literal string '$HOME\.local\bin', which Windows never expands — uv resolves only because a second copy happens to exist in AppData\Local\hermes\bin.
- **Solution:** Added an AtLogOn trigger with a 2-minute delay (lets USB settle) alongside the existing repeating trigger, and set StartWhenAvailable=True. Added a hard guard at the top of collector_watchdog.ps1: if D:\tradekit-data is absent it logs and exits 1 rather than launching anything, because a gap in collection is recoverable and a silently split archive is not. NOT SOLVED: fully headless restart still needs LogonType S4U, and the broken $HOME PATH entry is Mike's environment to change.

## 2026-08-10 — estimated a 10x saving from a Saturday, real figure was 23x `measurement,estimation,data`
- **Symptom:** Told Mike the Kraken book throttle would cut the stream ~10x (89.9%). The actual run dropped 95.7% — 342,389,849 rows to 14,658,656, closer to 23x.
- **Cause:** The estimate came from counting distinct seconds on 2026-08-08, which was a SATURDAY. Crypto book chatter is markedly lower at weekends: ETH/USD averaged 18.0 book updates per second that day against 45.7 on weekdays. One day is not a sample. The second, smaller error: distinct-calendar-seconds overcounts what a SLIDING 1s window keeps, because a window anchored on the last kept row can skip a calendar second entirely.
- **Solution:** Cross-check any per-day extrapolation against the day-of-week profile before quoting it, and prefer running the actual tool in dry-run over hand-computing a proxy metric — the dry run costs a minute and reports the real number. The decision was unchanged, but the figure quoted for approval was wrong by 2.3x and had to be corrected before executing an irreversible delete.

## 2026-08-09 — repartition left empty day dirs and that destroyed the Alpaca cursor `collector,alpaca,cursor,repair-tooling`
- **Symptom:** After repairing equities/alpaca, the poller went from 'rows=0' (correct, market closed) to writing 3.7 MILLION rows per 5-minute pass across 7 symbols, re-storing the same five days of tape over and over.
- **Cause:** Two of my own changes combined. repartition_archive moved every row out of RIOT/2026-08-08 into its true day and deleted the files, but left the empty directory. last_stored_cursor took the single newest day directory, found no files in it, and returned None — which the caller reads as 'nothing stored', so start fell back to the 5-day lookback floor. GLD was unaffected because it happened to keep one file in that day, which is why only 7 of 10 symbols showed the symptom and why the log line looked plausible at a glance.
- **Solution:** Both ends. last_stored_cursor now walks day directories newest-first and stops at the first one that actually yields a timestamp, because an empty day is a real state rather than an impossible one. repartition_archive removes a day directory it has emptied. Caught only because the final health sweep read the collector's own log instead of trusting the earlier green verification — a fix verified at 15:12 was already broken at 14:55.

## 2026-08-09 — three collectors each passed arrival time to the sink `collector,partitioning,api-design,time`
- **Symptom:** After fixing the sink to partition on the row's timestamp, measured wrong-hour was still 0.1083% (hour 13). Fixing run_ws_collector took it to 0.0009% (hour 14). Six rows still wrong. Each round of measurement exposed another caller.
- **Cause:** The sink's add(symbol, stream, row, ts) looked like it wanted 'the row's timestamp' but every caller had 'now' in hand and passed it. run_ws_collector passed arrival; collect_perps_hyperliquid is a custom orchestrator that never touches run_ws_collector and passed arrival at its own call site. On chatty feeds arrival and event time differ by milliseconds and only leak at the hour boundary, so the defect is invisible without measuring the whole archive. On Coinbase market_trades, which replays history, they differ by DAYS.
- **Solution:** Stop enforcing it at call sites. PartitionedParquetSink.add now treats its ts argument as the ARRIVAL time — a fallback — and event_ts(row, ts) prefers the row's own stamp whenever it parses. Every caller becomes correct by construction, including orchestrators that bypass the shared runner. The general lesson: when the same mistake is made independently by three callers, the parameter is the bug, not the callers.

## 2026-08-09 — rtk swallows pytest's summary line `rtk,pytest,tooling,gate`
- **Symptom:** 'rtk uv run pytest -q' reported 'Pytest: No tests collected' while the suite actually ran 1314 tests green; even 'rtk proxy uv run pytest -q' returned the warnings block with no 'N passed' line, so there was no way to read a test count from the filtered output.
- **Cause:** rtk's pytest filter did not match this project's output shape. Exit code was 0 throughout, so the failure was purely in the reporting layer — dangerous precisely because 'no tests collected' reads as a red flag when the truth is green.
- **Solution:** Do not read pass counts from rtk-filtered pytest output. Use the tk-gate script, which reports on exit codes and prints a canonical GATE: green/red block. Reserve 'rtk proxy' for cases where the raw tail is needed.

## 2026-08-09 — MIN_PART_ROWS traded file overhead for hour-attribution error `collector,parquet,partitioning,time`
- **Symptom:** The collector_core streams scored WORSE on wrong-hour partitioning than the legacy per-venue sinks they were supposed to improve on: books/okx 5.65% and trades/coinbase 5.90% against ticks' 1.87%, measured over 2026-08-08.
- **Cause:** The 2026-08-08 tiny-file fix made a buffer wait until it earns a file (MIN_PART_ROWS=500). Waiting longer means more buffers are still open when the hour rolls, and the sink named its target file from FLUSH time — so every straggler was filed under the hour it was written in, not the hour it happened in. The fix for one silent cost bought a louder one. The FRICTION entry for that change even states the misfiling rationale as if it were handled ('a buffer is force-flushed before crossing an hour'); the force-flush fired correctly and then wrote the rows into the NEW hour's file, which is the bug it claimed to prevent.
- **Solution:** Partition on the row's own timestamp, never on the clock: PartitionedParquetSink now buffers (ts, row) pairs and one flush writes one part file per (day, hour) the buffer spans. flush() lost its ts parameter entirely, because a parameter that looks like it decides the path but does not is how this survived review. scripts/repartition_archive.py repairs what was already written.

## 2026-08-08 — tiny part files made per-file overhead dwarf the data `parquet,collector,disk`
- **Symptom:** after turning on 8 collectors the archive burned 6.54 GB/day (85 days to fill D:), with Hyperliquid perps alone at 2.57 GB/day and OKX books at 1.96 — against Coinbase's 0.40 on a near-identical schema and pair count
- **Cause:** `flush_all` wrote a part file for EVERY buffer on every 60s tick regardless of size. A parquet file pays fixed footer/schema overhead whether it holds 6 rows or 6000, and at 232 perp assets x 2 streams that meant ~460 files/minute averaging **6 rows/file** (572 bytes/row vs 126 on the same schema elsewhere); OKX books averaged 25 rows/file at 1110 bytes/row. Compaction existed and would have fixed it, but had never been scheduled — it only merges CLOSED hours, so it cannot help the current hour anyway
- **Solution:** a buffer must earn its file — `MIN_PART_ROWS = 500`, with two escapes that keep this from becoming the old data-loss bug: `MAX_BUFFER_AGE_S = 600` bounds how long any row waits, and a buffer is force-flushed before crossing an hour (the filename comes from flush time, so a straggler would be misfiled). `flush_all(force=True)` on shutdown. Plus `compact_archive.py` now runs from the watchdog every 15 min. Result: 6.54 -> 3.27 GB/day, perps 572 -> 117 bytes/row, and row rates verified unchanged (OKX and Coinbase both ~1,550 rows/hr on top symbols)

## 2026-08-08 — Binance global WS is geo-blocked, not just the REST API `binance,geo,liquidations`
- **Symptom:** `wss://fstream.binance.com/ws/!forceOrder@arr` connects cleanly and then delivers nothing, which reads as "no liquidations happening"
- **Cause:** the host is geo-blocked like api.binance.com, but the block manifests as silence rather than an error frame or a 451
- **Solution:** control-test with a stream that CANNOT be quiet — `btcusdt@aggTrade` also returned zero frames in 60s, which settles it. Live Binance liquidations are unavailable; the archive's `liquidationSnapshot` is CM-only and stopped 2024-10-14. **OKX `liquidation-orders` (instType SWAP) is the one live public liquidation feed we can reach** — verified, one subscription covers all swaps, and it carries bankruptcy price, size and position side

## 2026-08-08 — part-file numbering restarted at 0 per sink instance, silently destroying rows `parquet,collector,data-loss`
- **Symptom:** a REST poller reported writing rows but the on-disk total did not move; reproduced minimally as two `PartitionedParquetSink` instances writing one row each to the same hour -> one file, one row, first row gone, no error
- **Cause:** part index came from an in-memory counter starting at 0 per instance with no check of what was already on disk, so the second instance wrote `part-0000.parquet` over the first. Hit any poller that builds a sink per pass, and — far worse — ANY collector that dies mid-hour and gets watchdog-relaunched, which would clobber every part written since the top of that hour
- **Solution:** `PartitionedParquetSink._next_part` memoises per (symbol, stream, day, hour) and seeds from disk (`max(existing)+1`) on first write to each hour. One small directory listing per hour; correct across instances, restarts and crashes. Found by a subagent during its own verification, not by the author — cheap independent verification earned its keep here

## 2026-08-08 — Alpaca real-time SIP needs a paid plan; historical SIP is free at T-15min `alpaca,equities,api-shape`
- **Symptom:** `wss://stream.data.alpaca.markets/v2/sip` auth returns `{"T":"error","code":409,"msg":"insufficient subscription"}`; the REST tick endpoint returns 403 for any window ending inside 15 minutes but 200 beyond it
- **Cause:** the account's data entitlement covers the historical consolidated tape but not the real-time SIP stream; free real-time is IEX-only (~2-3% of volume, unrepresentative)
- **Solution:** collect equities as a DELAYED POLLER, not a stream — request `[last_stored_ts, now-16min]` and page the cursor (`scripts/collect_equities_alpaca.py`). For an archive the lag is irrelevant, and the cursor being derived from stored state means restarts resume exactly and outages self-backfill

## 2026-08-08 — Binance global archive reachable although the live API is geo-blocked `binance,geo,archive`
- **Symptom:** `api.binance.com` returns HTTP 451 from this machine (consistent with the existing G6/fapi note), so Binance global was assumed unavailable and only thin Binance.US was collected
- **Cause:** the 451 is applied to the trading/market API hosts, not to the public historical archive bucket
- **Solution:** `https://data.binance.vision/...` serves 200 with real zips — verified `data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08-01.zip` (63 KB). The world's deepest venue is available to us for history even though live streaming is not. (Bybit is 403 and stays unavailable; OKX returns 200 and is usable live.)

## 2026-08-08 — Coinbase level2 caps at 30 products/session then goes SILENT `coinbase,websocket,livelock`
- **Symptom:** expanding the greenlist to 40 Coinbase book pairs produced zero rows; the collector looped `heartbeat timeout — reconnecting` forever
- **Cause:** the 31st product makes Coinbase emit one `{"type":"error","message":"too many L2 streams requested in a single session"}` frame and then stop sending anything. A read loop that only watches for silence cannot distinguish that from a dead socket, so it reconnects, re-subscribes, and livelocks
- **Solution:** binary-searched the cap (30 OK / 31 rejected); shard products across sessions (`MAX_STREAMS_PER_SESSION`) and treat an `error` frame as a raise, never as something to reconnect through. Generalised into `collector_core.VenueSpec.error_of` so every future venue must declare how it signals rejection

## 2026-08-08 — Kraken WS v2 renamed XBT->BTC but REST `wsname` did not `kraken,websocket,api-shape`
- **Symptom:** `verify_pairs("BTC/USD")` returned False, which would have silently dropped every BTC pair from the greenlist with only a warning into a 0-byte log
- **Cause:** verification compares against REST `AssetPairs.wsname`, which still carries the legacy `XBT/USD`; WS v2 accepts only `BTC/USD` and rejects `XBT/USD` with "Currency pair not supported"
- **Solution:** translate REST names into WS v2 symbols before comparing (`_ws_v2_symbol`, map `XBT->BTC`, `XDG->DOGE`). Probe both spellings against the live socket when adding any Kraken asset

## 2026-08-08 — collect_ticks had no time-based flush; quiet pairs lost and hour-misfiled `parquet,collector,data-loss`
- **Symptom:** after expanding to 56 pairs only 8 ever wrote files; the process grew ~0.5 MB/s
- **Cause:** `FLUSH_INTERVAL_S` was defined and documented but never used — the only drain was the per-pair 5000-row threshold. Liquid pairs crossed it constantly so the bug stayed invisible at 11 pairs; quiet pairs held rows in RAM for hours. Worse, the hourly filename is computed at FLUSH time, so rows buffered across an hour boundary were written into the wrong hour's file
- **Solution:** added the periodic `flush_all` to the message loop (56/56 pairs write within 4 min). Historical thin-pair data already on disk has some hour misattribution and cannot be recovered. `collector_core.PartitionedParquetSink` avoids the whole class of bug by flushing to append-only part files that a compaction pass merges after the hour closes

## 2026-08-03 — reviewer git-restore wiped uncommitted review target `git,review,subagent`
- **Symptom:** review round 20: reviewer probed a defect by editing the uncommitted implementation, then reverted with 'git restore' -- which restored HEAD and destroyed the green-stage work; had to reconstruct from a captured full-file read (verified byte-faithful via diff-stat + gate)
- **Cause:** git restore on a file whose only current version was uncommitted working-tree state; no stash/backup taken before the destructive probe
- **Solution:** reviewers must 'git stash push -- <file>' (or copy to scratchpad) before any mutate-and-revert probe on uncommitted code; restore via 'git stash pop', never 'git restore'

## 2026-07-25 — gitnexus FTS write fails read-only db even after reanalyze `gitnexus,hooks,mcp`
- **Symptom:** every Bash call hook-spams 'FTS index ensure failed ... Cannot execute write operations in a read-only database' for 5 tables
- **Cause:** MCP server holds the kuzu db read-only while hook/query path tries to create FTS indexes post-reanalyze
- **Solution:** **NOT SOLVED**

## 2026-07-25 — worktree uv env lacks pywinauto extra -> mypy false-red `worktree,uv,mypy,env`
- **Symptom:** gate mypy in .claude/worktrees/* reports import-not-found for pywinauto (bridge/_pywinauto.py) while main checkout is clean
- **Cause:** uv run in a fresh worktree resolves an env without the windows-bridge extra installed in the main .venv
- **Solution:** trust main-checkout gate for mypy verdicts on worktree branches, or uv sync --all-extras in the worktree before gating

## 2026-07-25 — tk-bootstrap UnicodeEncodeError on Windows cp1252 console `tooling,windows,encoding`
- **Symptom:** bootstrap.py exit 1 printing dev-log section containing U+2192 arrow; orientation output truncated
- **Cause:** print() to cp1252 stdout without utf-8 reconfigure; dev-log uses unicode arrows
- **Solution:** workaround: read dev-log/handoff directly; fix: add sys.stdout.reconfigure(encoding='utf-8', errors='replace') at top of bootstrap.py

## 2026-07-23 — Kraken Prop UI: OSO/bracket order flow does not work as OPERATIONS.md describes `ops,kraken,money-path`
- **Symptom:** Two live attempts tonight (2026-07-23) to place NEAR/USD as an OSO Bracketed Limit Order on the Kraken Prop account both failed to bracket; falling back to a plain limit entry + manual SL/TP resulted in stop-loss/take-profit orders sized 6036.6 and 4259.7 units against a 21.8-unit position (unexplained qty mismatch, likely UI/leverage unit confusion), which had to be flattened at market -- realized loss ~$36.43, account $5000.00 -> $4963.57
- **Cause:** Unconfirmed -- either Kraken Prop's order form does not support the bracket flow OPERATIONS.md step 3 assumes, or the human operator's manual SL/TP entry hit a units mismatch (base qty vs notional/contracts) specific to the Prop margin UI
- **Solution:** **NOT SOLVED**

## 2026-07-23 — GitNexus FTS index version mismatch (db v42 vs build v40) `tooling,gitnexus`
- **Symptom:** Every Bash PreToolUse hook spams FTS 'ensure failed' retry warnings; FTS search unusable
- **Cause:** GitNexus index built by newer kuzu storage version than the currently installed gitnexus build
- **Solution:** **NOT SOLVED**

## 2026-07-19 — Kraken Desktop has no UIA accessibility tree (grade C) `uia,bridge,kraken`
- **Symptom:** UIA probe sees only title-bar chrome; zero child HWNDs; no renderer process
- **Cause:** KrakenDesktop.exe is a single-process custom GPU-rendered native app (not Electron/WebView2); no UIA provider for content
- **Solution:** design U4 STOP triggered: UIA write path abandoned pre-build; pivot to vision-executor design round; probe artifact docs/research/uia-probe-kraken-2026-07-19.json documents evidence

## 2026-07-19 — test_import_guard reload dance leaves stale tradekit.bridge attr `test,imports`
- **Symptom:** later same-session tests comparing exception identity via 'from tradekit import bridge' see corrupted classes
- **Cause:** sys.modules reload/monkeypatch-undo in T2 import-guard test leaves parent package attribute stale
- **Solution:** consumers bind at call time (as main.py does); fixture-scoped reload cleanup in a later hygiene pass

## 2026-07-19 — read-dedupe hook false-positives on first-ever reads `hooks,subagent`
- **Symptom:** reviewer subagent blocked from first reads of test_simulator_parametric.py and test_prop_dials.py (files it had never opened this session); worked around via sed
- **Cause:** dedupe cache key was `path|mtime|offset|limit` scoped only by session_id; subagent tool calls carry the PARENT's session_id, so any file the parent (or a sibling agent) had read within the TTL denied the subagent's first-ever read — but the content was never in the subagent's context
- **Solution:** hook payloads carry `agent_id` (verified empirically via payload dump: subagent reads arrive with their own agent_id, e.g. `a293f7731d57dad5e`/`tk-explorer`); read_guard.py now prefixes the cache key with `agent_id` (fallback "main"), so dedupe tracks per-agent read history. Verified: same-agent re-read denies, different-agent first read allows.

## 2026-07-19 — commit_gate.py blocks documented (red) TDD commits `hooks,git,tdd`
- **Symptom:** P5-PROP batch A (red) commit denied: hook runs pytest and denies on any failure, no escape for the house (red) failing-test convention
- **Cause:** commit_gate.py written without the CLAUDE.md '(red) commits' exception — enforcement drifted from house law
- **Solution:** hook now allows commits whose git command contains the literal '(red)' marker (still runs/blocks everything else); red commits stay auditable via the commit message convention

## 2026-07-19 — pytest basename collision (hud batch 2)
tests/unit/hud/test_cli.py collided with tests/unit/cli/test_cli.py under
pytest prepend import mode (no __init__.py in test tree) — full-suite
collection error while targeted runs passed. Fix: renamed to
test_hud_cli.py. Rule going forward: test basenames must be unique across
the whole tests/ tree (or move the tree to importlib mode as an infra task).
Also re-hit: PreToolUse commit-gate deny blocks the ENTIRE chained Bash
command — keep `git commit` in its own call.
