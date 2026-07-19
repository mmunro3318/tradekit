# HANDOFF — ops-ready (2026-07-20 seam; written by Fable for ALL successor models)

Audience: GPT "Sol" 5.6, Claude Haiku/Sonnet/Opus session models, and
Codex. You are inheriting a WORKING loop, not a construction site. Read
docs/OPERATIONS.md first — it is the playbook; this file is the seam.

## State (all on main, pushed, gate green 1000+ tests)

- **The loop is complete and rehearsed**: `tk hud --equity N --serve` →
  scan report + advisory OSO tickets → Mike transcribes into Kraken Prop
  → Confirm button = binding chain (real thesis draft→submit→review→
  approve + fresh policy verdict + AdvisoryTicketAcked event) → 409 if
  policy refuses at click time (STOP signal) → fills via `tk fill`.
  Rehearsal proof: `uv run python scripts/rehearse_hud_ack.py` (temp
  ledger, "REHEARSAL PASSED"). Run it after ANY change near the loop.
- All 11 greenlist pairs scan clean (Kraken pair map completed; XRP uses
  legacy XXRPZUSD result key). Setup scan runs on 4h candles (720-bar
  provider cap; T-PAGE-1 pagination backlogged in ROADMAP).
- Live strategy: S1 momentum+volume (STRATEGY-BACKLOG.md). If it's
  structurally silent for days, S2 pullback-continuation is the designed
  fallback — spec it via tk-spec, don't improvise filters.
- Collector: auto-starts at logon, 11 pairs → data/ticks/. Check it's
  writing each session; never start a second instance.
- UI aesthetic: parked ("80's vibe" verdict from Mike) — functionality
  first; Claude Design will restyle later. Do not burn session time on CSS.

## Sanctioned seams (tests may patch ONLY these)

`mae._runtime.get_closed_bars/clock`; `hud._build.evaluate_policy/
open_position_symbols/sizing_info/scan_setup`; `hud._serve.
evaluate_policy_binding/_make_server`. ASSUMPTIONS 143-160 are binding;
append-only, CTO ratifies.

## Queue (in order — do not reorder without Mike)

1. **Operate the daily loop** (OPERATIONS.md): scan cadence ≤2×/day after
   4h closes; watch the 7-day inactivity clock (day-5 rule → CTO minimal
   trade through the FULL funnel).
2. **First real trade** when a ticket fires (or day-5 rule). Fill goes in
   via `tk fill` verbatim from Kraken's record.
3. **T-PAGE-1** provider pagination (ROADMAP backlog; cursor semantics
   documented — Kraken `since` is a timestamp cursor, Alpaca is an opaque
   token; do NOT page-index).
4. **S2 pullback-continuation** (STRATEGY-BACKLOG.md) — needs the small
   scanner extension for cross-timeframe tag joins.
5. **M5.2 backtest engine** — carries the DSR-dispersion fix
   (ASSUMPTIONS 156a), per-trial SR registry, Report-2 cost params.
6. **MS-PAXG-1** research per STRATEGY-BACKLOG.md (grunt-tier data work
   first; flag the XAU-reference-feed decision to Mike/CTO).
7. Owed to Mike (explainer debts, no code): parquet-data explainer;
   the "50-100 trades" sample-size answer verified against
   mae._metrics/STRATEGY-PROCEDURE (which gates actually carry
   trade-count minimums and whose trades they count — HIS trades vs
   candles). Both queued, neither urgent.

## Red lines (unchanged, every model, every tier)

Never edit tests to pass; never weaken R-rules; policy//broker/ changes
need a review round; golden vectors need the freeze gate; data/ is
gitignored (never commit ticks/ledger); Confirm-time 409 = STOP is a
safety feature — never soften it; no strategy below coin-flip to
manufacture activity.

## Working style expected (from Mike's rules + what worked)

tk pipeline stages for any dev ask; bespoke context-rich subagent
prompts; (red) commit convention; ASSUMPTIONS protocol on ambiguity;
gate before claiming green; dev-log + ROADMAP + handoff on every seam.
When in doubt: smaller, honest, loud failures over silent fabrication —
this codebase's whole character is "no fabricated numbers on a surface
Mike trades from."
