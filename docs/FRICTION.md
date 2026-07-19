# Friction Log

Tool failures, environment desyncs, wrong-assumed API shapes, and their fixes.
Append-only, newest first below this line. NOT SOLVED entries are review bait —
tk-learn promotes solved+generalizable entries to global memory.

---

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
