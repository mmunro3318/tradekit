# Execution Bridge v2 — UIA middleware design (supersedes outbox/inbox sketch)

> CTO design, 2026-07-19 (late). Mike's call: drop the file-based
> outbox/inbox; the bridge is a synchronous middleware that "physically"
> drives Kraken Desktop through the Windows accessibility layer (UI
> Automation) and returns success/fail directly. This doc is the seed for
> SPRINT-P5-BRIDGE pinning.

## Shape: a BrokerPort adapter, not a new pipeline

`UiaBroker` implements the EXISTING `broker._port.BrokerPort` protocol
(`submit / order_status / fills / account / positions`). Nothing upstream
changes: the policy gate (R-rules + VerdictToken) already sits between
every agent action and `submit()`; reconcile/halt machinery already
consumes BrokerPort outputs. The "middleware" is just this adapter plus a
thin UIA driver library it owns:

    thesis -> policy.evaluate -> VerdictToken -> broker.get("prop:starter1")
        -> UiaBroker.submit(order)          # synchronous, timeout-bounded
            -> _uia driver: find ticket -> set fields -> read-back verify
               -> click submit -> read confirmation -> Fill/raise
        <- OrderAck / VenueRejected / VenueUnavailable / NEEDS_RECONCILE

## The driver: deterministic verbs, no AI in the loop

Narrow verb surface (pywinauto, `backend="uia"`), per the
agent-desktop pattern but WITHOUT an agent holding the mouse:

- `snapshot()` — structured dump of the Prop panel (account selector
  value, instrument, balance/MDL/MDD readouts, open positions table).
- `select_account(name)` / `select_instrument(sym)`
- `fill_ticket(side, qty, type, limit_price, stop)`
- `read_ticket()` — read every field BACK off the UIA tree.
- `submit_ticket()` — enabled only after read-back matches the order.
- `read_confirmation(timeout)` — toast/positions-delta.

Mechanics are 100% deterministic UIA element walks pinned to
automation-ids/names captured in a probe (below). No vision model, no
LLM, no coordinates. An optional *secondary verifier* (screenshot ->
any VLM, or Claude read-only) can cross-check `snapshot()` for the
reconcile aid, but it is never on the submit path.

## Non-negotiable safety semantics (each becomes a pinned test)

1. **Read-back-before-submit**: submit is refused unless `read_ticket()`
   equals the order exactly (account, instrument, side, qty, price,
   stop). A UIA set that silently failed must never reach the venue.
2. **Timeout != fail**: if `submit_ticket()`/`read_confirmation()` times
   out, the order state is UNKNOWN — the click may have landed. Return
   `NEEDS_RECONCILE`, never "failed"; the caller must reconcile off the
   positions panel (`snapshot()`) before ANY retry. Blind retry on a
   money surface is the classic double-fill bug.
3. **Failure taxonomy mirrors `broker._port`** (round-25 discipline):
   venue-visible rejection (error toast) -> `VenueRejected`; app not
   running / element not found / tree changed -> `VenueUnavailable`;
   ambiguous -> `NEEDS_RECONCILE`. Nothing fabricated from silence.
4. **Client-side hard caps in the driver itself**: max qty/notional,
   internal walls (0.021/0.036 via `prop_account_walls`), ticket
   staleness expiry, and a kill-switch file checked before every
   `submit_ticket()`. Defense in depth below the policy gate.
5. **Live-lock discipline unchanged**: `UiaBroker` registers behind a
   `bridge_execution_enabled` dial (default false) + the existing
   promotion tiers; Claude remains read-only observer (harness tier +
   policy — executes nothing regardless); Mike flips the dial per-step.
6. **Supervised only** until Kraken's written stop-persistence answer
   (H.164): a human watches every submit in phase 1 of live use.

## Feasibility gate first (phase 0 — do before any driver code)

Kraken Desktop is (probably) Electron/Chromium. Chromium exposes a UIA
tree, but often only once assistive-tech is detected, and element ids
may be unstable per release. Phase 0 is a READ-ONLY probe script:
`scripts/probe_uia_kraken.py` dumps the tree over the Prop page + order
ticket (with and without `--force-renderer-accessibility`-style flags),
and we grade exposure A (semantic ids) / B (names only) / C (canvas —
fall back to the vision-executor plan, docs/handoff sprint sketch).
The probe artifact (tree dump) gets committed under docs/research/ and
the driver's element map is pinned against it, so a Kraken UI update
breaks LOUDLY at the map layer, not silently mid-order.

## Data plane (unchanged from batch-A architecture)

Analysis stays in `mae`: Kraken API primary for crypto, Alpaca for the
general universe; cross-feed divergence flag (>N bps -> distrust both,
no action), prop-basis 2bps placeholder pending Report 2. The bridge
consumes decisions; it never sources them.

## Batches (SPRINT-P5-BRIDGE, after M5.2 or interleaved)

- **A**: phase-0 probe + exposure grade + element map format (read-only).
- **B**: driver read verbs (`snapshot`/`read_ticket`) + reconcile-aid
  integration — useful standalone even if we never automate submits.
- **C**: write verbs + read-back/timeout/kill-switch semantics against a
  UIA test double (goldens for every safety pin above).
- **D**: `UiaBroker` adapter conformance (ring-2 suite, one factory
  entry) + supervised dry-run protocol doc for Mike.

Open flags for pin time: exact staleness expiry; whether `fill_ticket`
uses keyboard-emulation fallback when a field rejects UIA patterns
(grade-B exposure); confirmation source of truth (toast vs positions
delta vs both).
