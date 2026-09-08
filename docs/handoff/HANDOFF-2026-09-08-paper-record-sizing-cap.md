# HANDOFF 2026-09-08 — paper-record-sizing-cap (sprint seed)

## State (auto-captured, corrected by hand)
- branch: `main` (fast-forwarded to `fix/hud-preview-defer` this session; that
  branch and `fix/event-time-partitioning` are both fully contained in main)
- anchor: `b2a00f9` + this session's docs commit
- last gate: green 2026-09-08 (1421 tests, ruff clean, mypy clean, 95 files)
- dirty tree: `docs/digest/DIGEST-<today>.md` is APPENDED HOURLY by the
  scheduled task — expect it dirty; commit digests at session seams only.

recent commits:
```
b2a00f9 docs(digest): hourly paper-cadence digests 2026-09-07/08
4320fad docs: paper:alpha account created, first paper trade (TAO s1), open sizing/R-005/R-012 tensions
b63a508 feat(hud): defer R-010/R-012 insufficient_context at scan-time preview; map 9 Kraken pairs (GATE: green)
749fd21 test(hud): preview deferral of R-010/R-012 insufficient_context (red)
20125fa test(mae): Kraken pair mappings for the nine archived-but-unmapped symbols (red)
```

## Mission
The paper record is finally RUNNING (first trade 2026-09-07 07:24 UTC). This
sprint keeps it flowing at pace toward the 30-graded-trade T2 gate by removing
the two sizing/policy tensions that deny most entries, and makes the cadence
loud when its inputs are broken. Paper only. Live stays locked. Mike is not
supplying theses — the funnel drafts them.

## Live facts a fresh session must not re-derive
- Scheduled task `TradeKit Paper Cadence` (hourly, registered by Mike
  2026-09-07) runs `scripts/run_cadence.py` from the CHECKED-OUT working tree
  of `C:\Users\admin\dev\tradekit`. Whatever branch is checked out is what
  trades. Check `schtasks /query /tn "TradeKit Paper Cadence" /v /fo list |
  Select-String "Last Result"` — result 0, a "Ready" state proves nothing.
- Digest: `docs/digest/DIGEST-<UTC date>.md`, one section per run
  (entries / exits / attrition / prefilter kills / promotion / warnings /
  drought). Attrition `killed_by=<stage>` names the LAST stage reached.
- `paper:alpha` account: created 2026-09-07 with principal $500.00
  (`tk account create-paper`), settled cash $457.96 after the first fill.
  Before that the ledger had NO account at all — `broker.get` auto-vivifies a
  $0 shell and sizing dies silently. Never assume the account exists.
- Open position: TAO/USD 0.15765 @ 266.00, sl 235.58 / tp 330.73, thesis
  `01M1XC37T40K9WN939XR8CBA02` (s1_momentum, horizon 168h -> exits by
  2026-09-14 07:25 UTC at the latest). Series 8 window ends 2026-09-28.
- Promotion: T1, graded 0 in series 8, 1 graded ever. T2 needs 3 of last 4
  series clean + >=30 non-void + R-016 metrics.
- Scanner universe: `hud.DEFAULT_SYMBOLS` = the 11-pair greenlist. 20 pairs
  now have Kraken mappings (batch B added ZEC TIA DOT ADA SUI FIL ALGO HBAR
  POL). Widening DEFAULT_SYMBOLS is an open CTO decision (B3).
- Preview deferral (ASSUMPTIONS 181): R-010/R-012 `insufficient_context`
  defer at scan-time preview ONLY; binding re-checks both (178.2). Any other
  rule denies at preview. Do not widen this.

## Per-feature status
| feature | state | next action | blocking? |
|---|---|---|---|
| SPRINT-PREVIEW-DEFER A (preview deferral) | SHIPPED b63a508, review r23 | none | no |
| SPRINT-PREVIEW-DEFER B (9 Kraken mappings) | SHIPPED b63a508 | none | no |
| Paper cadence task | LIVE hourly since 2026-09-07 | watch digests; commit them at seams | no |
| T1 cap-aware sizing (R-005 starves stop_pct < 10%) | UNSPEC'D — tk-spec next | pin, red, green, review (mae + policy touch) | YES — denies LINK/SOL/ETH every hour |
| T2 R-012 notional drift (daily close vs 1h ticket price) | UNSPEC'D — tk-spec next | pin with T1 (same sizing call) | yes — rejected AKT at binding |
| T3 cadence loud on equity <= 0 / missing account | UNSPEC'D, small | one red test + warning line in run_once | no |
| DEFAULT_SYMBOLS widening (B3) | CTO decision open | decide after T1 lands (more pairs = more R-005 denials until then) | no |
| Data thread (CLAUDE.md NEXT 2-5: Binance archive backfill, Coinbase book backfill, Alpaca NBBO for IBIT+GLD, retention re-measure) | untouched this session | separate sprint; collectors healthy | no |
| Kraken Prop eval (P5-PROP) | IDLE — Mike says the prop account sits unused | decision: keep paying attention or let it lapse (7-day inactivity rule) | Mike's call |
| Navigator artifact | seed written: `docs/handoff/HANDOFF-2026-09-08-navigator-artifact.md` | Mike forks a branch; start at tk-brainstorm | no |

## T1 + T2 — what is known, for the tk-spec pass (NOT pinned yet)
- Sizing today: `mae.size_position(symbol, account_equity_usd, risk_pct_per_trade=0.01,
  atr_multiplier=2.0, ...)` -> `recommended_units`, `recommended_size_usd`,
  `stop_distance_usd`, `r_multiple_target`; size = equity*risk_pct/stop_pct.
  `hud._build._default_sizing_info` quantizes units to 8dp ROUND_DOWN.
  `thesis.submit` calls `mae.size_position` AGAIN and records
  `SizingComputed` — R-012 compares the submitted order notional to that
  record within `sizing_tolerance_pct` (0.01).
- Observed 2026-09-07 07:24 UTC: LINK $50.73 vs cap $50.00 (R-005 deny by
  73 cents), SOL $53.78, ETH would be ~$65; TAO $41.89 and NEAR ~$39 pass.
  AKT: preview passed, thesis drafted, binding R-012 deviation 0.0339 vs
  0.01 -> rejected (sizing priced at the daily close, ticket at the 1h close).
- Constraints any pin must respect: `mae` must not import `policy` (deep
  modules, DESIGN §4); R-012 purity means the ticket qty and the
  `SizingComputed` record must derive from the SAME inputs (price + equity +
  cap); money-path (`policy/`, `broker/`) changes need a review round.
- Candidate directions (CTO to choose in tk-spec): (a) pass
  `max_position_usd` into `size_position` from BOTH call sites (hud sizing
  seam and `thesis.submit`), computed as `max_position_pct_paper *
  paper_starting_equity_usd`; (b) size at the ticket's limit price (pass
  `price` in) so preview and submit agree; (c) ratify a wider R-012
  tolerance with a number derived from observed 1h/daily drift.

## Forks / parallel work in flight
- None mid-batch. The hourly task is the only thing running.
- Re-parked with Mike's "proceed" (2026-09-08): the 9 PARKED unknowns in
  SPEC-bridge-read / BRIDGE-UIA / HUD-ORDERBOOK / SPEC-wound-scale are
  untouched by this delta and stay parked (UIA is a ratified dead end).

## Next actions (ordered)
1. tk-spec for T1+T2+T3 as one feature (`docs/specs/SPEC-sizing-cap.md`),
   then tk-tasks -> tk-implement. Red tests must drive the REAL
   `thesis.submit` + `policy.evaluate` path (no fakes of either), mirroring
   `tests/unit/hud/test_build_state_preview_policy.py`'s harness.
2. After T1 lands: decide DEFAULT_SYMBOLS widening (B3) and commit.
3. Watch `docs/digest/` daily: entries, exits, the TAO exit reason, graded
   count. Commit digests at session end.
4. Data thread sprint (CLAUDE.md NEXT 2-5) when the record is flowing.
5. Prop decision from Mike.
