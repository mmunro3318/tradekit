# DESIGN — hud-ack (confirm/deny reverse channel + serve mode)

Input: Mike's directive 2026-07-19: the HUD needs "reverse functionality"
— per-ticket **Confirm** ("I sent this order on Kraken") and **Deny/Failed**
("I could not send it — technical failure, not a veto") buttons, preserving
the bot experience. Also: the pipeline should auto-open the page (done —
`tk hud --open`, AC-14) and eventually run one-click (`.bat`, parked until
the pipeline shape settles).

## Decision — serve mode over static-file hacks

A static HTML file cannot POST anywhere durable. Chosen: **`tk hud --serve`**
runs a localhost-only stdlib `http.server` (no new dependencies):

- `GET /` → regenerates the HUD (fresh `build_state` + `render`) per
  request — the page is always current; the meta-refresh keeps it cycling.
- `POST /ack` (JSON `{verdict_id, action}` where action ∈
  `confirmed | failed`) → appends a ledger event and returns 204.
- Bound to `127.0.0.1` only. No auth (localhost, single user). Ctrl-C stops.
- Plain `tk hud` (no `--serve`) keeps writing the static file; the buttons
  render but are marked inert ("serve mode required") when `fetch` fails —
  graceful, not broken.

Rejected: writing acks to a JSON sidecar file (splits the source of truth
away from the ledger); FastAPI (dependency for a two-route server).

## Semantics (pinned)

- **Confirm** = "the order was transcribed and submitted on the venue."
  It is NOT a fill — the fill still arrives later via the existing
  `tk fill` / `record_manual_fill` path with real prices. Confirm just
  timestamps the handoff so reconcile can pair venue orders to tickets.
- **Failed** = "technical failure sending it" (venue down, form rejected,
  ticket stale). The thesis/verdict stays intact; the next `tk hud` run
  may re-emit the ticket if the setup still holds.
- Veto is out of band by design (Mike: "we want to preserve the bot
  experience") — there is no veto button; not acting IS the veto.
- Idempotence: acks are append-only events; a second click on the same
  ticket appends a second event; projections take the latest per
  verdict_id. No state lives in the HUD (still a pure projection).

## Module table

| Module | Interface | Hides | Depth |
|---|---|---|---|
| `contracts` event `AdvisoryTicketAcked` | payload: `verdict_id, action: Literal["confirmed","failed"], acked_at` | ack grammar | data contract |
| `hud.serve(host, port, *, equity_usd)` | 1 verb | the whole HTTP loop, regeneration-per-GET, ack→ledger append | DEEP |
| render (existing) | unchanged signature | buttons + fetch snippet added per ticket tab | unchanged |

## Error map

| Boundary | Failure | Handling | Mike sees |
|---|---|---|---|
| POST /ack malformed | bad JSON / unknown verdict_id | 400, no ledger write | button flashes error |
| ledger append fails | exception | 500; server keeps running | error banner; ticket unacked |
| GET regeneration fails | provider exception | already degrades to wait-gates inside build_state; render errors → 500 with reason | error page, previous static file untouched |

## Test seams

CONTRACT (event payload), BEHAVIOR (POST confirmed/failed → ledger event
appended with exact payload; malformed → 400 + no event; GET returns
current render), SEAM (server exercised via `http.client` against an
ephemeral port; clock via `mae._runtime.clock`). No new sanctioned seams.

## Unknowns

- Port default (suggest 7333) and whether `--serve` implies `--open` —
  decide at spec.
- Reconcile pairing (ack → venue order id) stays manual until the fill
  report flow captures the venue's order id — existing `tk fill` question,
  not this feature's.

**NEXT →** tk-spec `hud-ack` (first implement batch of the next session).
