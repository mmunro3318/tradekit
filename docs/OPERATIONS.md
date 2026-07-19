# OPERATIONS — the daily Kraken Prop loop

Audience: Mike, and any model (Haiku/Sonnet/Opus/GPT) running a session.
This is the OPERATIONAL playbook — it assumes the code works and tells you
what to run, when, and what each result means. Development rules live in
CLAUDE.md; architecture in docs/DESIGN.md. When this doc and the code
disagree, the code + tests/ASSUMPTIONS.md win — then fix this doc.

## The loop in one line

> Scan → (maybe) ticket → human transcribes into Kraken → Confirm →
> fill reported → ledger accounts for everything. Repeat.

Nothing in tradekit ever places an order. The human is the executor;
the ledger is the memory; the policy gate is the conscience.

## Daily routine (Mike, ~5 minutes)

1. `uv run tk hud --equity <CURRENT equity USD> --serve`
   - Equity = the account's live value right now (e.g. 4980), never the
     nominal size. Read it off Kraken before running.
   - `--serve` opens the HUD in the browser and keeps it live; plain
     `tk hud --equity N --open` writes a static snapshot instead.
2. Read the scan report. Every symbol shows its gates:
   - `wait` — no confirmed setup, or a gate refused. Do nothing.
   - `hold` — you already have a position; no exit signal. Do nothing.
   - `buy`/`sell` — a ticket tab exists. Go to step 3.
3. For each ticket tab: open Kraken Desktop → Prop account → OSO
   Bracketed Limit Order. Copy the fields top-to-bottom (the tab mirrors
   the form). Review & submit on Kraken.
4. Click **Confirm** on that tab (= "I submitted it"). This is the
   binding moment: tradekit drafts the real thesis, re-runs the policy
   gate fresh, and books the ack. A **409 error means STOP** — the policy
   gate refused between scan and click (state changed); do NOT submit the
   order on Kraken (if already submitted, cancel it).
   Click **Failed** instead if you couldn't submit (venue down, form
   rejected) — it books the technical failure and nothing else.
5. When the order fills on Kraken, record it:
   `uv run tk fill --help` for the exact syntax — price, qty, timestamp
   from Kraken's fill record, verbatim.
6. Done. Tomorrow, same thing.

## Cadence (how often to run the scan)

The setup gate reads **4h closed candles** (UTC closes at 00/04/08/12/16/20)
and daily bars for sizing. Signals can only change when a 4h candle
closes, so:
- **Twice a day is the honest maximum useful cadence** (e.g. after the
  candle close nearest your morning and evening). Running it hourly
  changes nothing except the limit price sampling.
- Running it once a day is acceptable; you just might catch a setup a few
  hours late.
- Do NOT loosen gates to make tickets appear. Silence is a result.

## The 7-day inactivity rule

The prop account closes after 7 days without a trade. If no ticket has
fired by day ~5, the session model must flag it to Mike and the CTO
adjudicates a minimal manual-thesis trade — full funnel (thesis → policy
→ ticket → confirm → fill), smallest compliant size. Never bypass; the
funnel IS the product being rehearsed.

## Rehearsal (run after any change to the loop)

`uv run python scripts/rehearse_hud_ack.py` — spins a temp ledger, forces
one fake ticket, exercises GET + Confirm, and verifies the resulting
event chain + hash chain. Exit 0 and "REHEARSAL PASSED" or it's broken.
Run it before trusting the loop after ANY edit to hud/, thesis flow, or
policy surfaces. It never touches the real ledger.

## What the pieces are (for a model new to the repo)

| Command | What it does |
|---|---|
| `tk hud --equity N [--serve\|--open]` | scan funnel → tickets + gated report |
| `tk fill …` | record a manual fill against a thesis/order |
| `tk ledger verify` | hash-chain integrity check |
| `tk ledger query --type X` | inspect events |
| `tk thesis show <id>` | one thesis's full lifecycle |
| `tk policy status` / `tk promote …` | gate state / promotion ladder |
| `scripts/collect_ticks.py` | tick/book recorder (auto-starts at logon — never start a second one) |
| `scripts/rehearse_hud_ack.py` | end-to-end loop rehearsal, temp ledger |

## Session-model duties (any model driving a dev/ops session)

1. Read the newest docs/handoff/ file first; run the gate
   (`uv run pytest -q && uv run ruff check . && uv run mypy`) before
   building on anything.
2. Check the collector is writing (`data/ticks/<pair>/<today>/`) and the
   inactivity-day count; surface both to Mike unprompted.
3. Money-path red lines (CLAUDE.md) apply to every model at every tier:
   never edit tests to pass, never weaken R-rules, policy/broker changes
   need a review round, golden vectors need the freeze gate.
4. When you finish anything: dev-log entry, ROADMAP checkbox (green gate
   only), handoff note if the session is ending. Docs are part of done.
