# HANDOFF 2026-07-20 — HUD commit (post-UIA-grade-C pivot)

## TL;DR
T7 probe returned **GRADE C** (Kraken Desktop = single-process custom
GPU-rendered native exe; NO accessibility tree — see
docs/research/uia-probe-kraken-2026-07-19.json). UIA write path is dead.
**Mike has COMMITTED to the advisory-HUD path** (his message 2026-07-20,
binding): tradekit renders ready-to-transcribe order tickets mirroring
Kraken's own OSO bracket form; Mike executes manually;
`record_manual_fill` books fills. DEADLINE PRESSURE: Prop eval accounts
close after **7 days of inactivity** and Kraken Support is silent — some
(small) executed action must happen within days. Kraken may never ship a
Prop API "soon"; do not design around waiting.

## The HUD product decision (Mike's spec, from his screenshot — the
## fresh session does NOT have the image; this transcription is the law)

Mirror Kraken Pro's order ticket layout AS CLOSELY AS POSSIBLE so Mike
can transcribe field-by-field without translation, except recolored:
blacks/grays + **burnt orange/umber** accents (replacing Kraken's blue).

Kraken OSO bracket ticket structure (LINK/USD example, top→bottom):
1. Header: pair badge "LINK/USD".
2. Price row: bid "8.33744 USD" (highlighted button) | spread "1.76 bps"
   | ask "8.33891 USD" (button).
3. Balance row: "0.00 USD" (left) … "37.84930 LINK" (right) with
   depth-bar underline.
4. Side toggle: **Buy | Sell** (full-width, selected side filled).
5. Mode row: **Spot | Margin 10x** toggle + order-type dropdown
   ("Limit").
6. **Limit price** field (USD) with stepper + quick-set buttons:
   `Mid | Bid | -1% | -5% | -10%`.
7. **Quantity** field (asset units) + a small calculator icon; below it
   a 0–100% balance slider.
8. **Est. total** (USD).
9. **Attach OSO** dropdown = "Bracket".
10. **Take profit**: absolute USD field + "+ Distance %" field (paired).
11. **Stop loss**: absolute USD field + "− Distance %" field (paired).
12. **Est. P&L**: "− / −" (computed for TP/SL legs).
13. **Conditional trigger signal** dropdown ("Last price").
14. More options: **Post only** toggle, **Time in force** ("Good till
    canceled").
15. Buttons: `Reset` | `Review & Buy LINK` (primary, side-colored).
16. Status strip: warning line (e.g. "No available balance"), Est. fee,
    "0 open orders / Cancel all", "0 open positions / Close all".

**HUD delta beyond the mirror (Mike's addition):** it's an ORDER BOOK,
not one order — a title-bar area with TABS, one per pending advisory
ticket; cycle through tabs; each tab renders one ticket in the above
format. (Multiple scanner recommendations → multiple tabs.)

**Second deliverable — the scan report:** when the app/scripts run, emit
a per-asset analysis report: key indicators calculated (values), each
check/gate applied (regime, battery filters, metric chain, prop-fit),
comparisons and RATIONALE lines, ending in an explicit
buy/sell/hold/wait grade per asset. This is the transparency layer —
Mike wants to see WHY, not just the ticket. (The nine-stage funnel in
docs/design/STRATEGY-PROCEDURE.md §stages is the checklist the report
narrates; ASSUMPTIONS 156 amendments apply.)

## Next-session execution order
1. tk-bootstrap; confirm collector still running (data/ticks growing;
   Startup launcher installed; do NOT double-start).
2. **tk-design for the HUD** (feature name suggestion: `hud-orderbook`):
   decide render target FIRST — recommendation to evaluate: local web
   page (FastAPI/static + auto-refresh or Textual TUI). Constraints:
   Windows, zero cloud, reads advisory tickets + scan report from
   tradekit verbs; NO order execution anywhere in it (advisory only,
   ManualBroker path; R-rules still gate ticket creation). Reuse: the
   OSO field spec above IS the interface pin source; TicketReadback/
   PropPanelSnapshot contracts exist; `tk bridge snapshot` CLI pattern.
3. tk-spec → tk-tasks → implement (subagent batches per house cycle).
   MVP bar for week 1: ONE command (`tk hud` or `tk scan --report`)
   that produces (a) the tabbed ticket view for current scanner
   recommendations, (b) the scan report. Static regeneration is fine;
   live streaming is NOT MVP.
4. **Inactivity clock**: fastest compliant action = scanner/thesis →
   advisory ticket → Mike transcribes ONE minimal bracket order on the
   Prop account. All money-path discipline applies (thesis, R-rules,
   verdict, record_manual_fill after Mike's fill report). Do NOT invent
   a bypass to "just trade something" — the funnel exists; run it.
5. Parked/background threads: bridge-read merge decision (read verbs +
   parser stay valuable as HUD/CLI substrate — recommend merging after
   removing nothing; CTO call next session); M5.2 backtest engine
   (carries DSR-dispersion fix per ASSUMPTIONS 156a, per-trial SR
   registry, Report-2 cost params); R-017/R-018 prop:* context wiring;
   EmpiricalTradeModel; vision-executor design round is now DEPRIORITIZED
   (HUD replaces it near-term; revisit only if manual transcription
   proves too slow/error-prone).

## State snapshot
- Branch feature/bridge-read @ 9d993f1, pushed; main @ 4ad7d85 pushed.
  Gate green (866+ tests) at 9d993f1.
- Collector LIVE: 11 greenlist pairs → data/ticks/ Parquet (gitignored);
  Startup-folder launcher `tradekit-tick-collector.cmd`; background
  session copy also running (dies on reboot — fine).
- ASSUMPTIONS through 156 (Sol-audit ratifications). STRATEGY-PROCEDURE
  amended. Deep-research reports committed under
  docs/research/deep-research-reports/.
- Prop eval: Starter Eval 1 live, UNTOUCHED (no trades yet). MDL $150/
  day, MDD $300 static, target $500. Venue numbers in ASSUMPTIONS 143/145.
- Mike's uncommitted local edits (CLAUDE.md, perplexity-SME.md) — leave.

## Gotchas carried forward
- commit-gate hook: literal "(red)" required in message for red commits.
- data/ gitignored; never commit ticks.
- pywinauto tests simulate absence via sys.modules None entries (guard
  tests are environment-independent now).
- Kraken Desktop UIA: do not re-probe absent an app update; artifact is
  the evidence of record.
