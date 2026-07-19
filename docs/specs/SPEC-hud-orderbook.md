# SPEC — hud-orderbook

Branch: `feature/hud-orderbook`. Input: docs/design/HUD-ORDERBOOK.md;
layout authority: docs/handoff/HANDOFF-2026-07-20-hud-commit.md §elements
1–16 ("the transcription is the law").

## Scope

One command (`tk hud`) that walks the strategy funnel for the greenlist
symbols and writes a single self-contained static HTML file rendering
(a) a tabbed "order book" of advisory OSO-bracket tickets — each tab one
ticket, mirroring Kraken's form field-for-field in blacks/grays + burnt
orange — and (b) a per-asset scan report showing indicators, every
gate/check with rationale, and an explicit buy/sell/hold/wait grade.
Advisory only: no code in this feature communicates with any venue or UI.

## Out of scope

- Margin mode, non-limit order types, non-bracket OSO (spot+limit+bracket only).
- Live streaming/server; anything beyond whole-file regeneration.
- Order execution, UIA, vision — nothing touches Kraken Desktop.
- Persistence: HUD holds no state; ledger events remain the only record.
- Changes to policy/R-rules, scanner internals, or metric definitions.

## Interface pins

```python
# src/tradekit/contracts/_hud.py  (exported via contracts/__init__)
class GateResult(FrozenModel):
    name: str
    passed: bool
    observed: str      # rendered value, e.g. "DSR=0.61"
    threshold: str     # e.g. ">= 0.5"
    rationale: str

class ScanReportEntry(FrozenModel):
    symbol: str
    timeframe: str
    indicators: tuple[tuple[str, str], ...]      # (name, rendered value)
    gates: tuple[GateResult, ...]
    grade: Literal["buy", "sell", "hold", "wait"]
    grade_rationale: str

class AdvisoryTicket(FrozenModel):
    pair: str                                   # "LINK/USD"
    side: Literal["buy", "sell"]
    mode: Literal["spot"]
    order_type: Literal["limit"]
    limit_price: Decimal
    quantity: Decimal
    est_total_usd: Decimal
    oso: Literal["bracket"]
    tp_price: Decimal
    tp_distance_pct: Decimal
    sl_price: Decimal
    sl_distance_pct: Decimal
    est_pnl_tp_usd: Decimal
    est_pnl_sl_usd: Decimal
    est_fee_usd: Decimal
    trigger_signal: Literal["last"]
    post_only: bool
    tif: Literal["gtc"]
    warnings: tuple[str, ...]
    thesis_id: str
    verdict_id: str
    created_at: AwareDatetime

class HudState(FrozenModel):
    generated_at: AwareDatetime
    tickets: tuple[AdvisoryTicket, ...]
    report: tuple[ScanReportEntry, ...]
```

```python
# src/tradekit/hud/__init__.py (verbs), _build.py/_render.py (private)
def build_state(symbols: list[str], *, captured_at: datetime) -> HudState: ...
def render(state: HudState) -> str: ...        # full HTML document
```

CLI: `tk hud [--symbols ETH/USD,SOL/USD,...] [--out docs/hud/hud.html]`
default symbols = greenlist (pinned constant in `hud`). Exit 0 on success;
exit 4 on unwritable `--out` (message to stderr); render exceptions
propagate (nonzero exit, traceback).

Pinned arithmetic (buy side; sell mirrors signs):
`fees = round2(limit*qty*0.0004) + round2(exit*qty*0.0004)` per leg's exit
price; `est_pnl_tp = round2(qty*(tp - limit)) - fees_tp`;
`est_pnl_sl = round2(qty*(sl - limit)) - fees_sl`;
`tp_distance_pct = round2(100*(tp-limit)/limit)` (sl analogous, negative);
round2 = cent quantize ROUND_HALF_EVEN per application (ASSUMPTIONS 147).
`est_total_usd = round2(limit*qty)`; `est_fee_usd = fees at entry leg`.

Error taxonomy: no new exception types. Scanner warnings/refusals are data
(failed gates), not exceptions.

## Acceptance criteria

- **AC-1** GIVEN a `HudState` with two tickets and three report entries
  WHEN `render(state)` runs THEN it returns one self-contained HTML string
  (no external resource URLs) containing exactly two ticket tabs labeled by
  pair, and all three report entries.
- **AC-2** GIVEN a ticket (LINK/USD buy, limit 8.30000, qty 12, tp 8.71500,
  sl 8.05100) WHEN rendered THEN the ticket section contains, in order, the
  16 transcription elements' field labels ("Limit price", "Quantity",
  "Est. total", "Attach OSO", "Take profit", "Stop loss", "Est. P&L",
  "Post only", "Time in force", "Review & Buy") and the exact Decimal
  strings from the ticket (no float reformatting).
- **AC-3** GIVEN any state WHEN rendered THEN the document's CSS defines
  the pinned palette tokens `#121212`, `#1d1d1f`, `#c1581f`, `#8a3b12`,
  and the forbidden Kraken-blue token `#5741d9` does not appear anywhere
  in the document.
- **AC-4** GIVEN `build_state` where the funnel passes all gates for a
  symbol AND policy issues an allow verdict WHEN it runs THEN the result
  contains one `AdvisoryTicket` for that symbol whose `verdict_id` equals
  the ledgered verdict and whose est-P&L/fee/distance fields match the
  pinned arithmetic exactly (worked example fixed in the test).
- **AC-5** GIVEN a symbol where every gate passes EXCEPT policy refuses
  WHEN `build_state` runs THEN NO ticket is built for it, its report entry
  grade is `wait`, and a failed `GateResult` named `policy_verdict`
  carries the refusal rationale.
- **AC-6** GIVEN a symbol whose bar fetch yields insufficient data
  WHEN `build_state` runs THEN grade is `wait` with a failed
  `data_integrity` gate naming the gap; no exception escapes.
- **AC-7** GIVEN a symbol with an open thesis/position and no exit signal
  WHEN `build_state` runs THEN grade is `hold` and no ticket is built.
- **AC-8** GIVEN `build_state` called twice with identical seamed inputs
  and the same `captured_at` THEN the two `HudState`s are equal
  (determinism; no wall-clock reads inside — `generated_at == captured_at`).
- **AC-9** GIVEN `tk hud --out <tmp>` with seamed data WHEN it runs THEN
  exit 0 and the file at `<tmp>` parses as the same HTML `render` returns;
  GIVEN an unwritable `--out` THEN exit 4, stderr message, and any
  pre-existing file at the target is left byte-identical (temp+rename).
- **AC-10** GIVEN an empty scan (no symbols match anything) WHEN rendered
  THEN the HTML still renders the report section with all-`wait` rows and
  an explicit "no advisory tickets" placeholder — never an empty file.

## Test plan sketch

| AC | Kind | Notes |
|---|---|---|
| AC-1,2,3,10 | GOLDEN (key-content presence) | derivation source: handoff transcription §1–16; frozen HudState fixtures |
| AC-4 | BEHAVIOR + GOLDEN arithmetic | worked example independently hand-derived before freeze (golden-freeze gate) |
| AC-5,6,7 | BEHAVIOR | refusal/degradation paths |
| AC-8 | SEAM | `mae._runtime.get_closed_bars`/`clock` monkeypatches only |
| AC-9 | BEHAVIOR (CLI) | tmp_path; unwritable dir case |
| contracts | CONTRACT | Literal domains, frozen, Decimal round-trip |

## Unknowns register

- Greenlist default constant: ETH, SOL, LINK, NEAR, EIGEN, RENDER, PAXG,
  TAO, XRP, AVAX, AKT (/USD) — pinned from Mike's message; RESOLVED.
- TP/SL level selection (where tp/sl come from): existing sizing/thesis
  outputs (min-ATR stop, quarter-Kelly size per STRATEGY-PROCEDURE stage 8);
  `build_state` consumes them — RESOLVED by reference.
- Wait-vs-hold tie (open position AND data gap): `hold` wins (position
  safety trumps) — RESOLVED, test in AC-7 fixture.

## Addendum — T5 (real funnel wiring), CTO-pinned 2026-07-19

Interface changes (ratify as ASSUMPTIONS on red):
- `build_state(symbols, *, captured_at, equity_usd: Decimal) -> HudState`
  (new required kwarg; CLI gains required `--equity` Decimal option — the
  advisory surface never guesses account equity).
- Sizing seam becomes `size_qty(symbol, limit_price, equity_usd) -> Decimal`;
  DEFAULT is now REAL: `mae.size_position(symbol, account_equity_usd=equity_usd)`
  → qty = Decimal(str(recommended_units)) quantized to 8 dp ROUND_DOWN
  (conservative — never oversize). Zero/negative qty → no ticket, failed
  `sizing` gate.
- Bracket rule replaces interim 1.05/0.97: SL = limit − stop_distance_usd
  (from the same size_position call, min-ATR stop), TP = limit +
  r_multiple_target × stop_distance_usd (2R), both quantized to the limit
  price's exponent ROUND_HALF_EVEN. Sell side mirrors signs (and
  `_build_ticket_fields` + render button label become side-aware), though
  build_state still emits buy-only proposals in this batch.
- Setup gate (new, before policy): `mae.scan_markets("crypto", ["1h"],
  filters={"macd_signal": "bullish", "volume_spike": 1.5}, symbols=[symbol],
  regime_gate=True)`; PASSES iff a match for the symbol survives with ≥1
  signal_tag after the regime gate (doctrine: momentum + volume
  confirmation, STRATEGY-PROCEDURE stage 2). Fail → grade `wait`, gate
  rationale lists the dropped/absent tags; no policy call, no ticket.
- Gate order per symbol: open-position (hold) → data_integrity → setup →
  sizing → policy_verdict. Report entries carry the regime state/confidence
  in `indicators` when available.

AC-11: GIVEN seams driving a symbol through setup+sizing+policy allow WHEN
  build_state runs THEN the ticket's SL/TP equal the pinned ATR-bracket
  arithmetic (worked example frozen in tests) and qty equals the seamed
  size_qty result.
AC-12: GIVEN scan_markets yields no surviving signal_tags WHEN build_state
  runs THEN grade `wait` with failed `setup` gate and NO policy evaluation
  occurs (no verdict gate row present).
AC-13: GIVEN `tk hud` without `--equity` THEN usage error (exit 2, Typer
  default); with `--equity 5000` the value reaches build_state verbatim.
Scan seam: monkeypatch `tradekit.hud._build.scan_setup` (4th sanctioned
seam, same pattern; default = the real scan_markets call above).
