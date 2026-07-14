# HANDOFF — Interview Workbench — 2026-07-14

## TL;DR

This is a build spec, not a status report on existing code — paste this entire document into OpenAI Codex (or Gemini) and it should be able to scaffold and build the app with no other context. The app: a local-first web tool where an AI agent (Claude Code or similar) posts interview-style questions and Mike answers them asynchronously in a browser, with live draft visibility for the agent and batched feedback for Mike — generalizing a static claude.ai artifact shipped today into a real server-backed app. Nothing described below exists as code yet; the target repo (`C:\Users\admin\dev\interview-workbench`) has not been created. Budget ~2-4 days of Codex/Gemini time — this is CRUD + SSE, not novel engineering, which is exactly why it's being handed off instead of built with Fable/Opus credits.

## State ladder

1. **v0 — shipped 2026-07-14** — static claude.ai artifact, `scratchpad/mikes-desk.html` (see Sources). localStorage-only persistence, manual copy-paste export to hand answers back to the agent in chat. No server, no live sync, no durability beyond one browser's storage. This is the UX reference for card layout, tab structure, and star/pin behavior — **do not re-derive that layout from scratch, port it.**
2. **v1 — this spec, NOT built** — the real app described in this document. Zero lines of v1 code exist. Building v1 is the entire job for whoever receives this handoff.
3. **Target repo**: `C:\Users\admin\dev\interview-workbench` — new repo, sibling to `tradekit`, not nested inside it. Codex/Gemini should `git init` there (or Mike will — confirm before assuming remote setup).

## Narrative of work

- Earlier today, in a live tradekit session, Fable (inline, no subagent) built v0 — `scratchpad/mikes-desk.html` — as a fast answer to Mike's need for a place to park open questions (capital limits, time horizon, model budget, etc.) while work continued in the background. It works, but Mike immediately named its ceiling: no live co-editing visibility, no server-side durability, no structured batch-feedback loop.
- Mike then asked for the generalized version — a real app, not an artifact — and specified he wants it built by Codex or Gemini rather than by Fable/Opus, to conserve the good model's credits for tradekit's quantitative core (grading engine, sizing math, market analysis).
- This handoff document was written by a Sonnet subagent (not Fable, not Opus) per Mike's explicit request, using the `munro-handoff` format template. The subagent read the v0 artifact source directly to ground the UX reference below in the real markup rather than a paraphrase.
- No implementation of v1 has been attempted by anyone. This document is the entire spec.

## Open issues — prioritized

These are real decisions Codex must make or confirm with Mike before/while building. Where a default is stated, take it and move on rather than blocking on an answer.

1. **SSE vs polling for the live draft stream (agent watching Mike type)**
   - First try: implement `GET /api/state` as a plain polling endpoint (agent polls every 2-5s) — trivial, no persistent-connection bugs, good enough for "watching someone type."
   - Real fix: add `GET /api/events/stream` as Server-Sent Events for push-based updates (draft saves, new questions, agent notes) so the UI updates without a refresh and the agent doesn't have to poll to catch a batch submit.
   - Blocks shipping: no — polling-only is a legitimate v1; SSE is the nice-to-have layered on top. Build both if time allows (spec below assumes both exist).

2. **How the agent authenticates as "agent" vs Mike as "Mike"**
   - First try: a fixed request header, e.g. `X-Actor: agent` vs `X-Actor: mike`, unauthenticated, since this only ever binds to `127.0.0.1`. No login, no tokens.
   - Real fix: if this ever leaves localhost (LAN access, see Backlog), add a real auth layer — token per actor, checked in middleware. Not needed day 1.
   - Blocks shipping: no.

3. **File-drop ingest: watched directory (chokidar) vs manual import button**
   - First try: chokidar watching `./inbox/*.json`, since CLI agents (Claude Code) find "write a file" far easier than "make an HTTP call from inside a sandboxed tool run." Watch, ingest, move processed files to `./inbox/processed/`.
   - Real fix: if chokidar's filesystem-event reliability is flaky on Windows (it can miss events under some virtualization/antivirus setups), fall back to a short poll loop (stat the directory every 2s) rather than debugging chokidar edge cases.
   - Blocks shipping: yes, partial — file-drop ingest is an explicit requirement (item 1 below), so *some* working version must land, but it can be the dumb poll loop if chokidar misbehaves.

4. **Windows service/startup story**
   - First try: `npm start` in a terminal window, left running. That's the whole day-1 story — Mike is fine with a terminal tab open.
   - Real fix: if this needs to survive terminal closes, wrap in `pm2` or a Windows Scheduled Task / NSSM service. Not needed day 1.
   - Blocks shipping: no.

5. **Comment anchoring: does a "selected text" comment need stable offsets into the draft, or is a plain substring snapshot enough?**
   - First try: store the selected substring as plain text alongside the comment body — no offset math, no re-anchoring logic. If the underlying draft changes later, the comment just shows its quoted snippet, not a live-tracking highlight.
   - Real fix: store character offsets + a content hash of the draft at comment time, and only show a "stale — draft changed since this comment" badge if the hash no longer matches. Cosmetic, not required for correctness.
   - Blocks shipping: no.

6. **Draft revision history depth**
   - First try: one row per question in `drafts` holding only the current content + `updated_at` — no history, just durability of the latest value.
   - Real fix: an optional `draft_revisions` log (append-only) if Mike ever wants to see "what did I have 20 minutes ago" — genuinely nice for the power-loss acceptance test but not required by it (SQLite WAL durability already covers "don't lose the last save").
   - Blocks shipping: no.

7. **Markdown export escaping**
   - First try: naive concatenation of question titles as `##` headers and answer content as-is under each — works as long as Mike's answers don't themselves contain `#`-leading lines that would be misread as headers when pasted into chat.
   - Real fix: escape or fence any answer content that starts a line with `#`, ``` ``` ```, or other Markdown-significant characters before export, so the pasted result renders as intended in whatever chat client receives it.
   - Blocks shipping: no — the export requirement (item 7 in the requirements list) is satisfied by the naive version; escaping is a polish pass.

## Primer — how to use this

This section is the actual build spec. Follow it in order.

### Tech stack (fixed, do not substitute a framework)

- Node 20+
- Express (Fastify is an acceptable substitute if Codex strongly prefers it — do not add both)
- `better-sqlite3` — synchronous, single-file, WAL mode. One file: `./data/workbench.db`.
- SSE via raw `res.write()` on a `text/event-stream` response — do NOT pull in a websocket library (`ws`, `socket.io`). This is explicitly to avoid websocket complexity for a feature that SSE (one-way push, server→client) fully covers.
- Frontend: vanilla JS or Preact loaded via CDN-free bundling with `esbuild` (`esbuild src/app.jsx --bundle --outfile=public/app.js`). No React, no build-tool churn, no CSS framework — port the v0 artifact's existing CSS variables and layout instead of inventing new design.
- Single `package.json`, single process. No monorepo, no separate frontend/backend deploy.

### Scaffold

```bash
mkdir C:\Users\admin\dev\interview-workbench
cd C:\Users\admin\dev\interview-workbench
npm init -y
npm install express better-sqlite3 chokidar
npm install --save-dev esbuild
mkdir data inbox inbox\processed public src
```

Suggested directory layout once scaffolded:

```
interview-workbench/
  data/               # workbench.db lives here (gitignored)
  inbox/              # file-drop ingest watches this
    processed/        # ingested files get moved here, timestamped
  public/             # static assets + esbuild output (app.js, styles ported from v0)
  src/
    server.js         # Express app, route registration
    db.js             # better-sqlite3 setup, schema migration, WAL pragma
    routes/
      questions.js     # POST/GET /api/questions, draft, star endpoints
      batches.js        # answer-batch and comment-batch submit/export
      state.js          # GET /api/state, GET /api/events/stream
      ingest.js         # chokidar watcher / poll-loop for inbox/
    app.jsx            # Preact (or vanilla) frontend, esbuild entry point
  package.json
  .gitignore           # data/, inbox/processed/, node_modules/
```

better-sqlite3 is a native module — on Windows it needs either a prebuilt binary for the installed Node/Electron ABI (usually just works via `node-gyp` prebuild-install) or the Visual Studio Build Tools (C++ workload) if no prebuilt binary matches. If `npm install` fails on the native build step, that's the first thing to check — don't debug SQLite logic before confirming the module actually loaded.

### Schema (SQLite DDL)

```sql
CREATE TABLE questions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT NOT NULL,
  prose       TEXT NOT NULL,
  tags        TEXT,              -- JSON array, e.g. '["risk","sizing"]'
  source      TEXT NOT NULL,     -- 'api' | 'file-drop'
  starred     INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'answered'
  created_at  INTEGER NOT NULL
);

CREATE TABLE drafts (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id),
  content     TEXT NOT NULL DEFAULT '',
  revision    INTEGER NOT NULL DEFAULT 0,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE batches (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL,    -- 'answers' | 'comments'
  status       TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'submitted'
  label        TEXT,
  created_at   INTEGER NOT NULL,
  submitted_at INTEGER
);

CREATE TABLE answers (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id  INTEGER NOT NULL REFERENCES questions(id),
  batch_id     INTEGER NOT NULL REFERENCES batches(id),
  content      TEXT NOT NULL,
  submitted_at INTEGER NOT NULL
);

CREATE TABLE comments (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id   INTEGER NOT NULL REFERENCES questions(id),
  kind          TEXT NOT NULL,   -- 'agent_note' (live, unbatched) | 'mike_comment' (batched)
  target        TEXT NOT NULL,   -- 'question' | 'draft'
  selected_text TEXT,
  body          TEXT NOT NULL,
  batch_id      INTEGER REFERENCES batches(id),  -- NULL until Mike submits the comment batch; NULL always for agent_note
  created_at    INTEGER NOT NULL
);

CREATE TABLE events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  type       TEXT NOT NULL,      -- question_created | draft_saved | starred | answer_batch_submitted | comment_batch_submitted | agent_note_added
  payload    TEXT NOT NULL,      -- JSON
  created_at INTEGER NOT NULL
);
```

Enable WAL mode on startup: `db.pragma('journal_mode = WAL');`. This is what makes the "kill the process mid-write" acceptance test below pass without extra code — WAL + synchronous writes on each save is sufficient; don't build a custom write-ahead buffer.

### REST surface (every endpoint, exact)

**Agent-facing (ingest + read-only visibility):**

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/api/questions` | `{title, prose, tags?: string[]}` | Creates a question, `source='api'`. Returns `{id}`. Emits `question_created`. |
| GET | `/api/state` | — | Full read-only snapshot: all questions + current draft content + starred + comment *counts* (not bodies, unless submitted) + agent_notes + answered batches. This is the "watch Mike type" endpoint — poll it or use SSE. |
| GET | `/api/events/stream` | — | SSE stream of the `events` table as they're inserted. |
| POST | `/api/questions/:id/agent-notes` | `{text}` | Agent attaches a live side-comment. Visible to Mike immediately (SSE + `/api/state`), no batching. Emits `agent_note_added`. |
| GET | `/api/answer-batches/:id/export` | — | Returns `text/markdown` — clean export of one submitted answer batch, ready to paste into chat. |

**File-drop ingest (alternative to POST /api/questions):**

- Watch `./inbox/*.json` with chokidar (or a 2s poll loop — see Open Issue 3).
- Each file is either a single `{title, prose, tags?}` object or a JSON array of them.
- On detect: insert each as a question (`source='file-drop'`), then move the file to `./inbox/processed/<original-name>.<timestamp>.json` (never delete outright — keep an audit trail).

Example file an agent would drop at `./inbox/q-batch-1.json`:

```json
[
  {
    "title": "Position sizing ceiling",
    "prose": "Given the $25 live-trading cap, what's the largest single position (as a % of the cap) you're comfortable with before it feels reckless?",
    "tags": ["risk", "sizing"]
  },
  {
    "title": "Weekend behavior",
    "prose": "Should the paper-trading loop keep running over weekends on crypto pairs, or pause with the rest of the market?",
    "tags": ["scheduling"]
  }
]
```

Example curl calls Codex should use while testing the two ingest paths:

```bash
curl -X POST http://localhost:3000/api/questions \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"Test question\",\"prose\":\"Does this show up live?\",\"tags\":[\"test\"]}"

curl http://localhost:3000/api/state | jq .

curl -N http://localhost:3000/api/events/stream   # -N disables buffering, watch events arrive
```

**Mike-facing (browser UI):**

| Method | Path | Body | Notes |
|---|---|---|---|
| GET | `/api/questions?filter=pending\|all` | — | List questions with joined draft + starred + status. Default `all`. |
| GET | `/api/questions/:id` | — | Single question + draft + comments + agent_notes. |
| PUT | `/api/questions/:id/draft` | `{content}` | Upsert draft, bump `revision`, set `updated_at`. Debounce client-side (~400ms after last keystroke), not server-side. Emits `draft_saved`. |
| PUT | `/api/questions/:id/star` | `{starred: bool}` | Toggle pin to Pending tab. Emits `starred`. |
| POST | `/api/questions/:id/comments` | `{selected_text?, body}` | Adds a `mike_comment` to the currently-open comment batch (auto-create one if none open). NOT visible to the agent until the batch is submitted. |
| POST | `/api/comment-batches/submit` | `{label?}` | Closes the open comment batch (`status='submitted'`), stamps `submitted_at`. Emits `comment_batch_submitted` — this is the point the agent's `/api/state` and SSE stream reveal the comment bodies. |
| POST | `/api/answer-batches/submit` | `{question_ids?: number[], label?}` | Default (no `question_ids`): every question with a non-empty, not-yet-submitted draft. Copies draft content into `answers` rows under a new batch, sets those questions' `status='answered'`. Emits `answer_batch_submitted`. |
| GET | `/api/answer-batches` | — | List batches (for a history view). |

### UI (port v0's layout, don't redesign)

Reference `scratchpad/mikes-desk.html` directly for: card structure (`qid`, title, prose, star button, autosaving textarea, saved-timestamp chip), tab bar (Status / Needs / Questions / Pending / Side Quests — collapse to whatever tabs v1 actually needs, minimum: Questions, Pending), the pending-count badge, and the toast-on-save pattern. Swap the localStorage read/write in that file for `fetch()` calls against the endpoints above; keep the visual design (CSS variables, dark/light `prefers-color-scheme` handling) as-is — it's already done and Mike likes it.

New UI needs beyond v0: a way to select text in the prose or in the draft and attach a comment (textarea appears near the selection, "add to batch" button, running list of "N comments pending — Submit batch" sticky bar), and a place agent notes show up per-question (small inline callout, appears live via SSE without a page reload).

### Acceptance tests (checklist — run all before calling this done)

- [ ] Start the server, type into a draft, **kill the process** (Ctrl+C or `taskkill`) mid-keystroke after the debounce has fired at least once, restart with `npm start`, reload the browser — draft content matches the last saved keystroke, not empty, not stale.
- [ ] Star a question, refresh the browser — still starred, still listed in the Pending tab.
- [ ] `curl -X POST http://localhost:PORT/api/questions -d '{"title":"t","prose":"p"}' -H "Content-Type: application/json"` — new card appears in the running browser UI without a manual refresh (via SSE or the poll interval).
- [ ] Drop a JSON file into `./inbox/` while the server is running — question appears within a few seconds, file is moved to `./inbox/processed/`.
- [ ] Type in a draft in one browser tab; in a second tab (or via `curl /api/state`) confirm the in-progress text is visible without the first tab saving-and-refreshing anything else.
- [ ] Add 3 comments to a question, do NOT submit the comment batch — `GET /api/state` (simulating the agent) shows a comment *count* but not comment bodies. Submit the batch — bodies now present/exportable.
- [ ] Submit an answer batch, then `GET /api/answer-batches/:id/export` — valid Markdown, one heading per question, answer body beneath each.
- [ ] Hard-kill the node process (`taskkill /F`) mid-write (e.g. spam draft saves in a loop while killing it) — `workbench.db` reopens cleanly on next start, no corruption (WAL mode is what buys this — verify it's actually enabled, don't assume).

## Conventions and gotchas

- **Sandbox boundaries**: none apply here — this is a fresh repo Codex builds from scratch on Mike's own machine, not a shared/sandboxed tradekit workspace.
- **Compute economy** (why this app is going to Codex/Gemini and not Fable/Opus):
  - Opus: judgment calls, cross-doc consistency, architecture decisions
  - Sonnet: well-specified algorithms, test-driven implementation
  - Copilot: mechanical work — file renames, sed sweeps, git commands, installs
  - This app is CRUD + SSE with a fully-specified schema and endpoint list above — it needs none of Opus's judgment budget. That's the whole reason it's being handed off rather than built in-session.
- **SQLite file location**: `./data/workbench.db` — gitignore the `data/` directory (and `inbox/processed/`) so the repo stays clean; the whole point of SQLite here is "one file, easy backup," so don't scatter state elsewhere.
- **No auth, but don't hardcode that assumption in**: bind to `127.0.0.1` only, but keep actor identification (`X-Actor` header) as a distinct concept from "trusted because localhost" so a real auth layer can slot in later without a rewrite (see Open Issue 2).
- **Don't reach for a websocket library.** Every live-push requirement here (draft visibility, agent notes appearing without refresh) is one-directional server→client, which SSE handles natively with zero dependencies. A websocket lib is unnecessary complexity for what this app needs.
- **Windows-specific**: `better-sqlite3`'s native build step is the most likely install failure — check for it first if `npm install` errors. Chokidar's reliability under some Windows AV/virtualization setups is known-flaky; if file-drop detection misbehaves, downgrade to a poll loop rather than fighting chokidar (see Open Issue 3).

## Backlog

- [ ] Question topic tags & filtering (schema already has a `tags` column — just needs a UI filter)
- [ ] Multiple agents (currently assumes one agent identity; would need per-agent actor IDs)
- [ ] Response quality voting (Mike rates an agent's follow-up notes or answers)
- [ ] Import questions from a claude.ai artifact export (parse v0's downloaded `.md` backup format)
- [ ] Mobile layout pass (v0's CSS is desktop-first; not tested narrow)
- [ ] Auth for LAN use, if this ever needs to be reachable from another device on the network

## Sources

[mikes-desk.html](computer://C%3A%5CUsers%5Cadmin%5CAppData%5CLocal%5CTemp%5Cclaude%5CC--Users-admin-dev-tradekit%5Cd33c557d-6824-4e0d-868c-9912d5329338%5Cscratchpad%5Cmikes-desk.html)

[cc-dev-log.md](computer://C%3A%5CUsers%5Cadmin%5Cdev%5Ctradekit%5Ccc-dev-log.md)
