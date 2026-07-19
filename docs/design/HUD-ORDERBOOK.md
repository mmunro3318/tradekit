# DESIGN — hud-orderbook (advisory HUD, post-UIA-grade-C)

Input: docs/handoff/HANDOFF-2026-07-20-hud-commit.md (Mike's binding HUD
commitment + the OSO ticket transcription, which is the law for layout).
Advisory ONLY: nothing in this feature clicks, types, submits, or talks to
any venue. Mike is the executor; fills come back via
`broker.record_manual_fill`.

## Decision 1 — render target: static HTML file (chosen)

| Option | Verdict |
|---|---|
| **Static HTML written by `tk hud`** | **CHOSEN.** Zero server, zero new runtime deps (stdlib string templating), CSS reproduces the OSO ticket geometry/colors far more faithfully than any TUI, `<meta http-equiv="refresh" content="30">` gives free periodic reload of the regenerated file. Matches MVP bar: "static regeneration is fine; live streaming is NOT MVP." |
| FastAPI/uvicorn local server | Rejected for MVP: new dependency group, a process to babysit, buys only live push we explicitly don't need yet. Clean upgrade path later (same `render()` output served instead of written). |
| Textual TUI | Rejected: cannot mirror the Kraken form visually (the whole point — field-for-field transcription with zero translation). |

Blast radius if wrong: one render module swapped; contracts and builder
untouched. Fully reversible.

## Decision 2 — palette (pins for render tests)

Blacks/grays + burnt orange/umber replacing Kraken blue:
`--bg #121212; --panel #1d1d1f; --field #2a2a2c; --text #e8e6e3;
--muted #9a948d; --accent #c1581f` (burnt orange, primary buttons/selected
side) `; --accent-deep #8a3b12` (umber, borders/hover) `; --buy #c1581f;
--sell #7d2e2e; --warn #d9a441`.

## Module table

| Module | Interface (verbs × params) | What it hides | Depth verdict |
|---|---|---|---|
| `contracts._hud` | `AdvisoryTicket`, `GateResult`, `ScanReportEntry`, `HudState` (frozen models) | field vocabulary of the OSO mirror + report grammar | DEEP (data contracts; no behavior) |
| `hud.build_state(symbols, *, captured_at) -> HudState` | 1 verb | the entire funnel walk: scan_markets → regime → metric chain → prop-fit → grade per asset; ticket assembly only for proposals holding a policy verdict | DEEP |
| `hud.render(state: HudState) -> str` | 1 verb | full HTML/CSS of tabbed ticket book + scan report; templating ONLY — every rendered number read verbatim off `HudState`, never recomputed (report-module doctrine) | DEEP |
| `tk hud` CLI | `--out PATH` (default `docs/hud/hud.html`), `--symbols CSV` | wiring: clock → build_state → render → write file | thin by design (CLI shim, sanctioned) |

Information hiding check: only `build_state` knows the funnel; only
`render` knows HTML. The shared secret is `HudState` — that's the contract,
so the boundary is right.

## Data flow

```
greenlist symbols ──list[str]──▶ hud.build_state
  ├─ mae.scan_markets ──dict(matches/regime_context)──┐
  ├─ mae.get_regime / compute_strategy_metrics ───────┤ per-asset funnel
  ├─ policy (R-rules, prop dials/walls) ──Verdict─────┤
  └─────────▶ ScanReportEntry (indicators, GateResults, grade)
              AdvisoryTicket (only if grade==buy/sell AND verdict allows)
                        │ HudState
                        ▼
              hud.render ──str(HTML)──▶ CLI writes --out ──▶ Mike's browser
                                                              │ (manual transcription
                                                              ▼  into Kraken Desktop)
                                              broker.record_manual_fill (existing)
```

## Contracts (pin-quality; tk-spec copies verbatim)

`AdvisoryTicket` mirrors the transcription §elements 1–16 (fields Mike
types, plus context rows): `pair`, `side: Literal["buy","sell"]`,
`mode: Literal["spot"]` (margin out of scope), `order_type: Literal["limit"]`,
`limit_price: Decimal`, `quantity: Decimal`, `est_total_usd: Decimal`,
`oso: Literal["bracket"]`, `tp_price: Decimal`, `tp_distance_pct: Decimal`,
`sl_price: Decimal`, `sl_distance_pct: Decimal`,
`est_pnl_tp_usd: Decimal`, `est_pnl_sl_usd: Decimal`,
`trigger_signal: Literal["last"]`, `post_only: bool`,
`tif: Literal["gtc"]`, `est_fee_usd: Decimal`, `warnings: tuple[str, ...]`,
`thesis_id: str`, `verdict_id: str`, `created_at: AwareDatetime`.

Est-P&L formulas (pinned): fees at 4 bps/side (ASSUMPTIONS 144);
`est_pnl_tp = qty*(tp_price - limit_price) - fees(entry)+fees(tp exit)` sign
per side; SL leg analogous; cent-quantize ROUND_HALF_EVEN per application
(ASSUMPTIONS 147 convention).

`GateResult`: `name`, `passed: bool`, `observed: str`, `threshold: str`,
`rationale: str`. `ScanReportEntry`: `symbol`, `timeframe`,
`indicators: tuple[tuple[str, str], ...]` (name, rendered value),
`gates: tuple[GateResult, ...]`,
`grade: Literal["buy","sell","hold","wait"]`, `grade_rationale: str`.
`HudState`: `generated_at`, `tickets: tuple[AdvisoryTicket, ...]`,
`report: tuple[ScanReportEntry, ...]`.

Grade rule (pinned): `buy`/`sell` only when every gate passes AND policy
issues an allow verdict; `wait` when data/regime gates fail (setup absent
or regime hostile); `hold` when an open position/thesis exists for the
symbol and no exit gate fires. No verdict → never buy/sell regardless of
metrics.

## Ticket lifecycle (state machine)

```
proposed(gates green + verdict) ─▶ rendered(tab in HUD)
   ─▶ transcribed (Mike reports fill → record_manual_fill, existing path)
   ─▶ closed (thesis exit / cancel)
rendered ─▶ stale (next regeneration drops/replaces the tab; no persistence
             beyond the ledger events that already exist — HUD holds NO state)
```

The HUD is a pure projection: kill the file, regenerate, nothing lost.

## Error / rescue map

| Boundary | Failure | Typed | Handler | Mike sees |
|---|---|---|---|---|
| build_state → mae | insufficient bars / feed gap | scanner's own warnings list | carried into `ScanReportEntry` as a failed data-integrity gate → grade `wait` | a WAIT row with the data-gap rationale, never a silent omission |
| build_state → policy | verdict refused | normal refusal (not an error) | ticket NOT built; refusal rendered as failed gate + rationale | why the trade was blocked |
| render | any exception | bug — let it raise | CLI exit ≠ 0 | stack trace; stale previous HTML stays on disk untouched (write via temp+rename) |
| CLI file write | unwritable path | OSError | CLI exit 4, message | error text |

"Log and continue" appears nowhere: every degradation is a visible WAIT
gate row.

## Test seams

- CONTRACT: `contracts._hud` model validation (Literal domains, frozen,
  Decimal fields).
- GOLDEN: `render(frozen HudState fixture) -> HTML` — assert key content
  presence (pair, prices, palette tokens, tab per ticket, gate rows), not
  full golden strings (report-module precedent). Derivation source: the
  handoff transcription §1–16 checklist.
- BEHAVIOR: `build_state` grade rule (verdict-refused → no ticket + failed
  gate; data gap → wait; passing funnel → ticket with correct est-P&L
  arithmetic per pinned formulas).
- SEAM: clock/bars ONLY via `mae._runtime.clock` / `get_closed_bars`
  monkeypatches (existing sanctioned seams; no new ones). `captured_at`
  is a required kwarg on `build_state` — never wall-clocked inside
  (ASSUMPTIONS 155c precedent).

## Unknowns register carry-forward

- U-HUD-1 render target → RESOLVED (static HTML, Decision 1).
- U-HUD-2 margin mode / non-bracket order types → PARKED out of scope
  (spot + limit + bracket only; matches the one compliant trade needed for
  the inactivity clock).
- U-HUD-3 live streaming / websocket push → PARKED post-MVP (upgrade path:
  serve `render()` output).
- U-HUD-4 exact grade thresholds (DSR screening 0.5 etc.) → RESOLVED by
  reference: STRATEGY-PROCEDURE.md stage gates + ASSUMPTIONS 156 are the
  authority; `build_state` consumes, never redefines them.
- Vision-executor: DEPRIORITIZED (handoff), not part of this design.

No TBDs remain. **NEXT → tk-spec (feature `hud-orderbook`).**
