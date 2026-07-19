# BRIDGE-UIA — synchronous UIA execution middleware (DESIGN, v2)

> CTO design, 2026-07-19 (late), upgraded to tk-design bar 2026-07-20.
> Mike's call: no outbox/inbox files — a synchronous middleware drives
> Kraken Desktop through Windows UI Automation and returns success/fail
> directly. Supersedes the executor-agent sketch. Recon basis: broker
> seam facts verified against `_port.py`/`_manual.py`/conformance suite
> (recon-bridge sweep, 2026-07-20).

## 0. Decision summary

Order flow reuses the entire existing money path; only the last hop is
new:

    thesis -> policy.evaluate -> VerdictToken
        -> broker.get("prop:starter1") -> UiaBroker (BrokerPort)
            -> tradekit.bridge driver (UIA verbs, deterministic)
                -> Kraken Desktop order ticket
        <- OrderAck | VenueRejected | VenueUnavailable | VenueAmbiguous

No AI on the submit path. Mechanics are deterministic UIA element walks
against a pinned element map; any model (Claude read-only included) is
at most a *secondary* reconcile verifier, never an actor.

**NEW DEPENDENCY (flagged per house rule): `pywinauto` (UIA backend;
pulls `comtypes`).** Chosen over raw `comtypes`/`uiautomation` because
it is the maintained, typed-enough, Windows-native UIA wrapper with
wait/timeout primitives we would otherwise hand-roll. Windows-only dep:
declared in an optional dependency group `bridge` so CI/linux installs
stay clean; `tradekit.bridge` import fails loud with install hint.

## 1. Module table (Deep Modules doctrine)

| Module | Interface (verbs × params) | What it hides | Depth verdict |
|---|---|---|---|
| `tradekit.bridge` (driver) | 7 verbs: `snapshot()`, `select_account(name)`, `select_instrument(sym)`, `fill_ticket(ticket)`, `read_ticket()`, `submit_ticket()`, `read_confirmation(timeout_s)` | UIA tree walking, element map resolution + staleness, input method (UIA pattern vs keystroke fallback), waits/retries, Electron-accessibility activation | DEEP — 7 narrow verbs over the entire Win32/UIA/Electron surface |
| `broker.UiaBroker` (adapter) | BrokerPort's 5 verbs (`account/positions/submit/order_status/fills`) | driver orchestration, verdict-token check, client-side caps + kill-switch, confirmation -> `FillRecorded` ledger writes, ambiguity handling | DEEP — same width as every other adapter (conformance suite: one factory entry) |
| element map (`bridge/elementmap_kraken_<ver>.json`) | data, not code | selector churn across Kraken releases | n/a — versioned data artifact, pinned to the probe dump |
| `scripts/probe_uia_kraken.py` | CLI, read-only | — | thin by design (a probe, not a module) |

Rejected shallow alternative: a separate "middleware service" process
with an HTTP API (the pasted agent-desktop pattern). We have exactly one
consumer (tradekit) on the same machine; a local API layer is a
forwarding wrapper. The driver is a library; the *seam* is BrokerPort.

## 2. Data flow

    OrderRequest + VerdictToken
        │ submit()
        ▼
    UiaBroker ── caps/kill-switch/ttl check ──> BrokerTokenRequired /
        │                                       VenueRejected(reason=cap)
        ▼ Ticket (typed: account, symbol, side, qty, type, limit, stop)
    bridge.fill_ticket ──UIA──> Kraken Desktop
        │ read_ticket() -> TicketReadback (every field, from the tree)
        ▼ readback == ticket ? submit_ticket() : VenueUnavailable(set-failed)
    read_confirmation(timeout) ──> ConfirmationEvent
        │                            (positions/orders panel delta = truth;
        │                             toast parsed as advisory corroboration)
        ▼
    OrderAck + FillRecorded(ledger)   |   VenueRejected (venue error text)
                                      |   VenueAmbiguous -> HaltSet + reconcile

## 3. Submit state machine (the only lifecycle)

    IDLE -> NAVIGATED (account+instrument verified from snapshot)
         -> FILLED    (ticket fields set)
         -> VERIFIED  (read_ticket == ticket, exact; else abort SET_FAILED)
         -> SUBMITTED (click; ts recorded)
         -> CONFIRMED (panel delta within timeout)  -> ack
          | REJECTED  (venue error surfaced)        -> VenueRejected
          | AMBIGUOUS (timeout, no delta, no error) -> VenueAmbiguous

Transitions are one-way; any UIA failure before SUBMITTED aborts to a
clean state (nothing at the venue — safe to re-enter from IDLE). After
SUBMITTED, NOTHING retries automatically, ever (double-fill rule).

## 4. Error / rescue map

| Failure | Typed as | Handler | Operator sees |
|---|---|---|---|
| bad/missing VerdictToken | `BrokerTokenRequired` | policy pipeline (existing) | struct-ordered refusal |
| kill-switch file present / dial off / ticket older than `bridge_ticket_ttl_s` (60) / cap or internal-wall violation | `VenueRejected` (reason names the guard) | caller; no UI touched | refusal with named guard |
| app not running, element map miss, tree changed, read-back mismatch (pre-submit) | `VenueUnavailable` | caller may retry from IDLE; map miss also logs the tree diff for re-pin | "bridge unavailable: <element>" |
| venue error toast/inline after submit | `VenueRejected(venue_text)` | caller | venue's own words |
| post-submit timeout, no confirmation, no error | `VenueAmbiguous` (NEW, `VenueError` subclass) | pipeline: `HaltSet` + mandatory `reconcile()` before ANY resubmission | halt + reconcile report |
| UIA exception mid-`submit_ticket` click | `VenueAmbiguous` (click may have landed) | same as above | same |

`VenueAmbiguous` is the one new exception; it extends the round-25
taxonomy and is exported from `broker._port` (canonical home rule).

## 5. Ledger + reconcile integration

- CONFIRMED writes `FillRecorded` (actor `"system:bridge"`) with price/
  qty/fees parsed from the confirmation panel; `OrderSubmitted`/
  `OrderAck` events bracket the UI interaction (validate-before-append
  discipline: events only after the corresponding UI truth exists).
- `fills(since)` parses the app's trade-history panel (broker truth,
  independent of our ledger) so the EXISTING `reconcile()` triple-match
  `(order_id, ts_utc, qty)` has two genuinely independent sources.
  Venue UI has no order_id: the bridge stamps its own ULID into the
  ledger AND matches history rows by `(ts within tolerance-0, qty,
  symbol, side)` mapped back to the bridge order — exact mapping is a
  SPEC-level pin (feature 3) informed by the probe's history-panel dump.
- `order_status(order_id)`: open-orders panel parse; unknown id ->
  `status="rejected"` (conformance fail-closed pin).
- `account()`/`positions()`: snapshot parse of the Prop panel readouts
  (balance, MDL/MDD remaining, positions table) — this is ALSO the
  standalone reconcile-aid deliverable (useful before any write verb
  exists).

## 6. Safety invariants (each becomes a pinned test)

1. Read-back-before-submit, exact equality on every field.
2. Timeout ≠ fail: post-submit ambiguity -> `VenueAmbiguous`, halt,
   reconcile before retry. No automatic resubmission, ever.
3. Client-side hard caps below the policy gate: max qty/notional,
   `prop_account_walls` (0.021/0.036), `bridge_ticket_ttl_s`,
   kill-switch file (`TK_DATA_DIR/bridge.KILL`) checked before every
   `submit_ticket()`.
4. `bridge_execution_enabled` dial, default false; `broker.get("prop:*")`
   fail-closed conjunction (dial AND element map present AND app
   reachable), mirroring `LiveTradingDisabled`'s pattern with
   `BridgeExecutionDisabled`.
5. Read verbs never require the dial (reconcile aid is always allowed);
   write verbs always do.
6. Supervised-only until Kraken's written stop-persistence answer
   (H.164): the dry-run protocol (feature 4) requires Mike watching
   each submit; this is process, pinned in the protocol doc, not code.

## 7. Test seams

- **Determinism seam:** the driver takes a `UiaSession` protocol
  (connect/find/read/set/click primitives). Tests inject `FakeUiaSession`
  replaying recorded tree states — the ONLY sanctioned fake for bridge
  tests (mirrors `mae._runtime` discipline; never mock tradekit
  internals). Probe dumps become fixture trees.
- CONTRACT: UiaBroker joins `CASE_BUILDERS` ("prop" entry) — token
  refusal, Decimal money, ascending fills, typed order_status.
- BEHAVIOR: state machine paths (read-back mismatch aborts; ambiguous
  timeout raises + halts; caps refuse pre-UI).
- GOLDEN: snapshot parser over committed probe dumps (panel text ->
  typed readouts, cent-exact).
- SEAM: kill-switch file, ttl expiry vs injected clock (`bridge._clock`
  monkeypatch seam, same shape as `mae._runtime._clock`).

## 8. Unknowns register (carry-forward: resolved or consciously parked)

| # | Question | Status |
|---|---|---|
| U1 | Ticket staleness expiry | RESOLVED (fill-blanks): dial `bridge_ticket_ttl_s = 60` — long enough for UI latency, short enough that a stale thesis price can't execute; revisit with dry-run data. |
| U2 | Keyboard fallback when a field rejects UIA value patterns | RESOLVED (fill-blanks): allowed per-field (grade-B exposure), because read-back is the invariant that makes input method irrelevant — pattern first, keystroke fallback, identical verification either way. |
| U3 | Confirmation source of truth | RESOLVED (fill-blanks): positions/open-orders panel delta is authoritative; toast is advisory corroboration only (transient, missable). |
| U4 | Kraken Desktop UIA exposure grade | PARKED on evidence, by design: phase-0 probe (feature 1) grades A/B/C. Grade C (canvas) -> STOP; fall back to the vision-executor sketch as a NEW design round. Features 2-4 are conditional on A/B. |
| U5 | UI-history -> order_id mapping for `fills()` | PARKED to feature-3 spec, pinned against the probe's actual history-panel columns (can't pin columns we haven't seen; spec blocks on probe artifact). |
| U6 | Stop persistence during disconnect | EXTERNAL (Kraken ticket) — gates autonomy tier only, not this sprint's supervised scope. |

## 9. Feature list (feeds tk-spec / tk-tasks)

1. **probe-uia**: `scripts/probe_uia_kraken.py` read-only tree dump +
   exposure grade + committed artifact. (No spec needed — a probe.)
2. **bridge-read**: element map format + driver read verbs
   (`snapshot`, `read_ticket`) + snapshot parser goldens + reconcile-aid
   CLI (`tk bridge snapshot`). Standalone value.
3. **bridge-write + UiaBroker**: write verbs, state machine, caps/
   kill-switch/ttl, `VenueAmbiguous`+halt wiring, ledger writes,
   conformance entry, `fills()` mapping (U5 resolved here).
4. **dry-run protocol**: supervised execution procedure doc + `tk bridge
   drill` (fills a ticket on the SMALLEST unit and stops before submit;
   Mike clicks or aborts). Process deliverable.

Blast radius: everything below `broker.get("prop:*")` — no existing
adapter, rule, or test changes except additive routing + the new
exception export. Reversal = delete the package + routing branch.
