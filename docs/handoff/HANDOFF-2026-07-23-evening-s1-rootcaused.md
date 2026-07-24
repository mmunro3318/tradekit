# HANDOFF 2026-07-23 (evening) — S1 root-caused, first live trade, two audits in flight

> Written by Opus with Mike, end of the evening session. SUPERSEDES
> HANDOFF-2026-07-23-fable-return-s1-silence.md as the active seed (that doc's
> forward plan is now stale — the "unmeasured root cause" it assumed is FOUND).
> Its red-lines and sanctioned seams remain binding. Read this one first.

## State
- branch: `main`; gate green @ `fdc865f` at session start (1000+ tests).
- **No src changes committed this session** — this was diagnosis + tickets +
  audits. New untracked/uncommitted: `scripts/day5_manual_trade.py`,
  `docs/tickets/TICKET-001-scan-attrition-telemetry.md`,
  `docs/reviews/test-audit-2026-07-23.md`,
  `docs/reviews/test-audit-2026-07-23-sol-brief.md`, dev-log + FRICTION edits,
  and (pending) `docs/reviews/gating-filter-audit-2026-07-23.md`.
- Prop account: **FLAT**, $4963.57 (was $5000; −$36.43 tonight, see below).

## The headline: S1 silence is a one-word bug (CONFIRMED, proven live)
`hud/_build.py` `_SETUP_FILTERS = {"macd_signal": "bullish", ...}` but
`mae/_scanner.py` accepts only `"bullish_cross"` and routes everything else to
`else: return None`. The momentum filter has rejected 100% of candidates,
silently, on every scan since the constant was written. Compounding: even
corrected, tonight yields 0 (all 11 pairs have negative 4h MACD histograms —
genuine broad-crypto weakness). Silence was broken AND correctly-quiet at
once. **Full evidence + fix plan: `docs/tickets/TICKET-001-...md`.**

## FIRST BATCH for the next session: TICKET-001
Enum fix + loud-on-bad-value + scan-attrition telemetry (Mike's log format),
shipped as ONE batch with CTO sign-off. Watch the trap: a current test
(`test_scan_markets_verb.py:490`) codifies the silent drop as correct and will
go RED when the enum raises — invert it deliberately with a numbered
ASSUMPTIONS entry, never edit-to-pass. This is strategy-behavior + R-rule-
adjacent; honor the money-path review round.

## Two audits (both dispatched this session)
1. **Test-suite audit — DONE**: `docs/reviews/test-audit-2026-07-23.md`.
   Verdict: units strong, seams untested; the suite mocks both sides of every
   inter-module contract so the whole S1 bug-class was invisible. Top item: a
   contract test binding `_SETUP_FILTERS` to the scanner's accepted vocabulary
   (would've been red for S1's entire life). External second opinion:
   `docs/reviews/test-audit-2026-07-23-sol-brief.md` — carry to GPT/Gemini.
2. **Gating/filter silent-failure swarm — DONE**:
   `docs/reviews/gating-filter-audit-2026-07-23.md`. 58 chunks sniffed, 59
   suspects, **12 confirmed / 47 cleared**. Systemic pattern named:
   *"undefined/unrecognized input coerced into a plausible benign value instead
   of failing loud"* — the macd bug's whole family. HIGH findings (CTO
   spot-verified H2/H3 against real code):
   - **H1** `_scanner.py:259` — the macd bug, independently re-confirmed (= TICKET-001).
   - **H2** `_sizing.py:30-51` [MONEY-PATH] — `atr_position` guards atr/price/
     equity/risk_pct but NOT `multiplier`; a negative multiplier returns a
     silent negative/wrong-way position size, `0` gives opaque DivisionByZero.
   - **H3** `policy/_rules.py:603` + `_evaluate.py:64` [MONEY-PATH] — the gate
     **fails OPEN** on an unrecognized `action.kind`: empty `applicable` →
     `all([])==True` → `allow=True`, zero rules run. Latent (real mutating kinds
     hit R-001 today), but the fail-open is real in the one place that must fail
     closed. Fix = close `ProposedAction.kind` to a `Literal` and/or fail-closed
     guard. **Two `needs_human` calls block the fix shape — CTO must adjudicate
     the kind-taxonomy closure before coding H3** (see report callout).
   - M1/M2 (bb_position enum, correlation 0/0→0.0) + L1-L5 (missing period
     guards, regime sidecar/HMM observability). Recommended TDD batch order is
     in the report's closing section (money-path bundle behind ONE review round).
   All reports-only; NO code applied (money-path red-line).

## Money-path / venue truth learned tonight (see FRICTION.md)
- **Kraken Prop has no working bracket/OSO order flow**; Kraken Desktop is
  unusable for entry — **mobile only henceforth, manual exits.** OPERATIONS.md
  step 3 is WRONG and must be rewritten.
- **First live trade attempt (day-5 rule)** via `scripts/day5_manual_trade.py`
  (seams only the scan-time PREVIEW policy — binding policy real). NEAR/USD
  long, ~$41. Prop ended flat; −$36.43 was a **fat-finger**: a 4259.7-unit
  (2x-leveraged) take-profit-entered-as-BUY, dumped at market. The actual
  21.8-unit thesis trade lost ~$0.17 — strategy/sizing fine, margin UI not.
  Day-5 inactivity rule is SATISFIED (a trade was placed+closed on prop).
- **Account-attribution trap**: the ~21.8 NEAR + OCO bracket Mike still holds
  is on his REAL/spot account, NOT prop. Prop is flat.
- **HUD-ack UX bug (separate ticket needed)**: Confirm/Failed fire silently
  (subtle glitch only) AND non-idempotently — repeated clicking booked TWO
  `failed` acks (ledger seq 2,3) tonight. Server-side chain is fine. Needs
  visible state feedback + idempotency + disable-after-submit.

## Also open (unchanged from prior seed)
- advisory:kraken has no balance feed → loop settles on paper:alpha $500 dial,
  not real prop equity (ASSUMPTIONS round-20). Ticket-worthy now that it bites.
- MTF-SCAN (T-MTF-1..4) + S2 pullback still queued BEHIND TICKET-001.
- GitNexus index is version-mismatched (db v42 vs build v40) — FTS search
  broken, spams every Bash call; needs `node .gitnexus/run.cjs analyze` or a
  build upgrade (FRICTION.md).
- Ledger has 2 junk `failed` acks (seq 2,3) from the button bug — harmless (no
  thesis/money attached), append-only chain so leave them; note in any query.

## Traps
- 4h cadence = ≤2 meaningful scans/day; don't judge a re-tuned S1 on <3 days.
- Don't tune volume_spike/regime dials before the attrition telemetry gives
  numbers + CTO sign-off (seed red-line).
- Prop leveraged positions accrue daily funding (prop_funding_daily_pct) —
  don't hold idle 2x positions.
