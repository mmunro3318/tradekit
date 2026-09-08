# HANDOFF 2026-09-08 — navigator-artifact (feature seed)

## State (auto-captured, corrected by hand)
- branch: start from `main` (fast-forwarded 2026-09-08, contains everything);
  Mike will fork a dedicated branch for this work — e.g. `feat/navigator`.
- last gate: green 2026-09-08 (1421 tests). This feature touches NO Python;
  the gate still runs before any commit (docs-only commits included).
- The hourly paper cadence runs from the checked-out tree — do not leave
  `main` checked out on a branch state that lacks b63a508.

## Spec
None yet. This starts at **tk-brainstorm** (short — Mike's ask is explicit),
then a design plan, then build. Scope in one line: a living, visual
"game board" of the whole project that a visual learner can open in five
minutes to regain scope and vision — roadmap, progress, forks, drift, the
sustained loops, and where we are now — published as an Artifact and
redeployed at every session seam.

### Mike's own words (2026-09-08), the brief
"a visual guide to the project — the roadmap, the progress we've made
(completed work, forks or divergences from the core roadmap as work has
progressed, milestones drifting out of reach as either priorities change,
or I've lost sight of the original vision) ... basically a game board with
the roadmap and milestones, workflows, sustained loops we're aiming to
solidify and set running (like the data capture on D:/) ... I need scope and
vision again, with a navigator to help orient me / us." He liked the LINK
Impulse Desk Note (artifact 9ac34c64-39b9-4a5f-ade8-d2bd16fd09f8) and wants
the same "beautiful visual artifact you can change/update as we go."
Context that matters: sessions add 10-30k lines he cannot track; task
switching has become hard; he is job-hunting to fund the Alpaca accounts;
the Kraken Prop account is idle; tokens go to waste when he cannot keep up.

## Source inventory (everything the board is built from — all in-repo)
| source | what it gives the board |
|---|---|
| `docs/ROADMAP.md` | the spine: P0-P5 phases, M-boxes (100 [x] / 42 [ ] as of 09-08), dates of completion, deferrals |
| `docs/SCOPE.md` | vision §1, locked decisions D1-D17, promotion ladder §5, phasing §6 |
| `docs/DESIGN.md` | TD-1..TD-24 register, system architecture §4, open questions §18 |
| `docs/handoff/*.md` (chronological) | the FORKS: SPRINT-P1B/P1C/P2/P3-P4/P5-PROP; 2026-07-19 prop pivot; 07-20 hud-commit; 07-27 three-thread fork (paper sprint / indicator lab / stratchpad); 08-09 data-vacuum expansion + event-time partitioning; 09-08 this pair |
| `docs/primers/*.md` | Mike-facing explainers already written (P1B, P1C, P2, P3) — link them from the board |
| `docs/reviews/agent-metrics.md` | 23 review rounds — the quality trail |
| `docs/digest/` | the LIVE loop: hourly cadence runs, entries/exits, promotion counters |
| `docs/ARCHIVE-README.md` | the D: archive: 8 collector streams, 87 pairs, sizes, since-dates |
| `docs/FRICTION.md` | why things took longer than planned |
| `tests/ASSUMPTIONS.md` | 181 ratified laws — the board should count them, not list them |
| `cc-dev-log.md` | session-by-session record (newest first) — the drift evidence |
| memory: `~/.claude/projects/C--Users-admin-dev-tradekit/memory/*.md` | Mike's vision answers (capital, red lines, universe), project-state timeline |

## Facts for the board (so the builder does not re-derive them)
- Core ladder: P0 skeleton -> P1 MAE -> P2 thesis+policy -> P3 paper -> P4
  live proof (redefined 2026-07-26 as Option A: 30-trade paper record with
  positive edge -> T2 -> Mike confirms -> 3 probationary live trades through
  the gated pipeline) -> P5-PROP.
- Drift / divergences worth drawing: (1) P5-PROP pivot 2026-07-19 — Kraken
  Prop has no API, Kraken Desktop has no accessibility tree (UIA grade C,
  ratified dead end), so the execution-bridge line stalled; prop account now
  idle; (2) the paper-record machinery was COMPLETE 2026-08-03 but the
  cadence task was never registered and the scan preview could never ticket
  — the record did not start until 2026-09-07 (five weeks of drift); (3)
  the 2026-07-27 three-thread fork: paper sprint (done), indicator lab
  (experiments/ only, Mike co-pilot), stratchpad charting SPA (never
  started); (4) data vacuum 08-08/09 became its own thread: 11 -> 87 pairs,
  3 -> 8 streams, partitioning bug + repair, compaction rework, 17 GB and
  growing — healthy, autonomous; (5) candlerl experiment (vision candlestick
  classifier + PPO) — parked; (6) live path verified 2026-07-26 ($5 ETH
  round trip) but LIVE remains structurally locked (four locks).
- Sustained loops (draw as running machines with health): 8 collectors on D:
  (watchdog, cold-start on logon, compaction manual since 08-23); hourly
  paper cadence (since 09-07); scheduled-task gotcha: check LastTaskResult.
- "You are here" (2026-09-08): first paper trade open (TAO); T1 tier; series
  8 of the 30-trade ladder; next batch = sizing cap (see the sibling seed
  `HANDOFF-2026-09-08-paper-record-sizing-cap.md`).
- Money on the table: ~$50 Alpaca live (probation stake, untouched), $500
  paper, ~$2,500 Kraken long-horizon (never traded by the engine), Kraken
  Prop Starter eval ($5,000 notional, idle).
- Decisions Mike owes (chips on the board): prop account keep/lapse;
  DEFAULT_SYMBOLS widening; stratchpad thread alive or dead; indicator-lab
  cadence.

## Design direction (CTO, so the artifact reads as one family)
- Same identity as the desk note: Barlow Condensed display, IBM Plex Sans
  body, IBM Plex Mono data, warm near-black ground with burnt-orange accent,
  light theme designed with equal care (tokens on `:root`, dark via
  `prefers-color-scheme` guarded `:root:not([data-theme="light"])` and
  `:root[data-theme="dark"]`).
- Board metaphor, not a slide deck: lanes = threads (core ladder, data
  vacuum, prop, indicator lab, stratchpad); nodes = milestones with a state
  vocabulary of exactly five words (done / active / drifting / parked /
  dead); a marked "you are here"; loops drawn as machines with a health
  light; a drift ledger (milestone, planned, what happened, why) as a table;
  a decisions-owed strip.
- Everything on the board must be a real fact with a date; no lorem, no
  invented milestones. Numbers (tests, ASSUMPTIONS count, pairs, GB) go in
  tiles, not prose.
- Draw with inline SVG generated by a small script from a data object at
  the top of the file (so updating the board = editing data, not markup);
  load `artifact-design` and `artifact-diagramming` before writing;
  consider `artifact-capabilities` for Mike's own checkmarks/notes on nodes
  (load it BEFORE writing if used).
- Source of truth lives in the repo: `docs/navigator/navigator.html`
  (+ `docs/navigator/README.md` explaining the data object). Publish via the
  Artifact tool from that path; redeploys keep the URL. Add
  `docs/navigator/` to the CLAUDE.md doc inventory with "update at every
  tk-ship" so it never rots.

## Current batch
None — stage = brainstorm/design. No pinned interfaces (no code surface).

## ASSUMPTIONS pending ratification
None.

## Next actions (ordered)
1. Mike forks `feat/navigator` from `main`; session starts with
   tk-bootstrap, reads THIS seed and the sibling sizing-cap seed.
2. tk-brainstorm, 10 minutes max: confirm the five-state vocabulary, the
   lanes, and whether Mike wants his own annotations persisted (capability).
3. Design plan (palette/type/layout in writing), then build
   `docs/navigator/navigator.html` from a data object; publish; send Mike
   the link; one round of his feedback.
4. Wire the maintenance rule: CLAUDE.md doc inventory row + a dev-log line;
   the sizing-cap sprint's tk-ship is the first redeploy.
5. Optional follow-up: a Mike-facing primer for P4/P5 (the last primer is
   P3) so the board has something to link for the newest phases.
