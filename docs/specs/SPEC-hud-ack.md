# SPEC — hud-ack (serve mode + confirm/failed reverse channel)

Branch: main (feature is additive; hud/ + cli only). Input:
docs/design/HUD-ACK.md. Supersedes nothing; extends hud-orderbook.

## Scope

`tk hud --serve` runs a localhost-only HTTP loop: GET / regenerates and
serves the HUD; POST /ack lets Mike confirm ("order submitted on venue")
or fail ("could not submit — technical") a ticket. **Confirm is the
binding moment**: the handler runs the real transactional chain — draft
thesis → submit → approve (the human click IS the approval) → fresh
policy.evaluate → append `AdvisoryTicketAcked` — all through existing
public verbs. Scan-time verdicts remain advisory previews. Failed appends
only the ack event (thesis/verdict untouched). Buttons render in the
static file too but degrade gracefully when no server answers.

## Out of scope

- Veto button (not acting is the veto — bot experience preserved).
- Fill recording (existing `tk fill` path), reconcile pairing, auth/TLS,
  non-localhost binding, multi-user.
- Any change to policy/, broker/, thesis/, ledger/ source (consumed via
  public verbs only).

## Interface pins

```python
# contracts: new event payload (registered like existing event payloads)
class AdvisoryTicketAckedPayload(...):   # follow _event_payloads.py house pattern
    verdict_preview_id: str      # the scan-time ticket's verdict_id (pairing key)
    action: Literal["confirmed", "failed"]
    thesis_id: str | None        # real ledgered thesis (confirmed only)
    verdict_id: str | None       # the BINDING confirm-time verdict (confirmed+allowed only)
    pair: str
    side: Literal["buy", "sell"]
    limit_price: str             # Decimal-as-string, ticket snapshot
    quantity: str
    acked_at: AwareDatetime

# src/tradekit/hud/__init__.py
def serve(*, equity_usd: Decimal, host: str = "127.0.0.1", port: int = 7333) -> None: ...
```

CLI: `tk hud --serve [--port 7333]` (implies `--open`; still requires
`--equity`). Stdlib `http.server` only — no new dependencies. Ctrl-C
(KeyboardInterrupt) exits 0.

Routes:
- `GET /` → 200 text/html; body = `render(build_state(symbols,
  captured_at=clock(), equity_usd=...))` — fresh per request.
- `POST /ack` body `{"verdict_preview_id": str, "action": "confirmed"|"failed",
  "ticket": {pair, side, limit_price, quantity, tp_price, sl_price}}`.
  - `failed` → append AdvisoryTicketAcked (thesis_id/verdict_id None) → 204.
  - `confirmed` → thesis.draft(contract built from the ticket snapshot) →
    thesis.submit → thesis.approve → policy.evaluate(ProposedAction from
    the snapshot) → allow: append event with real ids → 204;
    refuse: NO ack event, 409 with the refusal rationale in the body
    (state changed since the preview — Mike must not send stale orders).
  - Malformed JSON / missing fields → 400, no ledger write.
- Anything else → 404.

Render delta: each ticket tab gains Confirm / Failed buttons + an inline
fetch('/ack', …) snippet posting the pinned body; on non-2xx or network
error the button shows the error text instead of crashing the page. The
snippet is inline JS (self-contained rule unchanged — no external
resources).

## Acceptance criteria

- **AC-A1** GIVEN the server on an ephemeral port with seamed funnel data
  WHEN GET / THEN 200, text/html, body contains the same key content
  `render(build_state(...))` produces at that instant.
- **AC-A2** GIVEN POST /ack action=failed WHEN handled THEN exactly one
  `AdvisoryTicketAcked` event is appended whose payload has action
  "failed", null thesis_id/verdict_id, and the ticket snapshot verbatim;
  response 204.
- **AC-A3** GIVEN POST /ack action=confirmed and policy allows WHEN
  handled THEN the ledger gains, in order: ThesisDrafted (+submit/approve
  events per house lifecycle), a policy verdict event, and one
  AdvisoryTicketAcked whose thesis_id/verdict_id match those events;
  response 204.
- **AC-A4** GIVEN POST /ack action=confirmed and policy refuses WHEN
  handled THEN response 409 carrying the refusal rationale and NO
  AdvisoryTicketAcked event is appended.
- **AC-A5** GIVEN malformed JSON or a missing field WHEN POST /ack THEN
  400 and the ledger is unchanged.
- **AC-A6** GIVEN any state WHEN rendered THEN each ticket tab contains
  Confirm and Failed buttons and the inline ack snippet; a static-file
  open (no server) leaves the page functional (buttons fail gracefully —
  no uncaught page errors; this is asserted structurally: the snippet
  catches fetch rejection).
- **AC-A7** GIVEN the server WHEN KeyboardInterrupt THEN clean exit 0.

## Test plan

AC-A1/A7 SEAM (ephemeral port, http.client, seamed funnel + frozen clock);
AC-A2..A5 BEHAVIOR against a temp ledger (TK_DATA_DIR to tmp_path — the
existing conformance pattern); AC-A6 GOLDEN key-content presence.
Determinism: mae._runtime seams + the four hud._build seams only.

## Unknowns

- Thesis contract minimum fields for draft(): implementer reads
  thesis.draft's validation and builds the smallest honest contract from
  the ticket snapshot; flag anything ambiguous rather than improvise.
- `--serve` + `--out` interaction: serve mode ignores `--out` (documented).
