# cc-dev-log

Chronological dev log. Newest entry first. One entry per working session; keep entries terse — decisions and deltas, not narration.

## 2026-07-12 (later) — Adversarial review incorporated; DESIGN.md → v0.2

- Mike approved all v0.1 decisions incl. the three §18 asks (TD-10 promotion tightening, $25 live cap, advisory cooling-off). Confirmed rolling our own paper engine; futures *signals* deprioritized below stocks/crypto (we never trade futures — it's positioning data for spot theses); options = "maybe, later" → P5+ deferred list.
- Gemini adversarial review (Codex usage-capped) archived verbatim with dispositions at `docs/research/gemini-adversarial-review.md` (G1–G6).
- Accepted: G1 DSR gates only at n≥30/strategy, provisional penalized-Sharpe regime below (TD-14); G2 tick-size `quantize` at MAE boundary (new TD-23); G3 EWMA 3σ vol override on stale HMM (TD-13); G5 limit fills need trade-through ≥1 tick; G6 derivatives chain = Kraken Futures → Coinalyze → Binance, implementation → P3.
- **Partially rejected G4** (in-process write queue): wrong topology — tradekit is many short-lived CLI processes, not one threaded process. Kept: bounded retry-with-jitter on `append`; scouts write wiki files, not events. Escalation stays the Phase-2 daemon (TD-16).
- All three former Perplexity questions (Q1–Q3) resolved by the review; none open.
- Answered Gemini's closing question by specifying correlation methodology in DESIGN §9.1 (30d Pearson, daily log-returns, UTC inner-join, ≥20 overlap else `insufficient_overlap` → unmeasured ≠ pass).
- Next: ROADMAP.md, then P0 implementation. Repo still needs `git init` + GitHub remote (Mike's call to make now).

## 2026-07-12 — Pass B: DESIGN.md produced (Claude Code, Fable)

- Read all Pass-A inputs: SCOPE.md (D1–D17), Perplexity SME pass (F1–F7), canonical MAE doc.
- Wrote **docs/DESIGN.md** — full architecture doc: TD-1…TD-22 decision register, tech stack, 7 deep modules + 2 shared leaves + 2 thin shells, contracts (thesis contract + predicate DSL), event-sourced hash-chained ledger DDL, policy rules catalog R-001…R-016 with WHYs, promotion state machine (series hardened per SME F2/F3), two-phase order pipeline owned by `broker.execute_order`, own PaperBroker (TD-7), MAE port with derivatives-provider fallback chain, threat model, three-ring test strategy, build phasing P0–P5.
- Notable overrides of SCOPE (all flagged inline): promotion series locked to fixed 30-day blocks/≥10 trades/≥30 total (F2/F3); paper daily trade cap 20/day (anti-gaming); CoinMarketCap dropped.
- Key risk surfaced: **Binance fapi is US-geo-blocked (HTTP 451)** — canonical MAE's primary derivatives source; made derivatives a pluggable port, fallback question queued for Perplexity (DESIGN §18 Q1).
- Ran a cold-read consistency review via subagent: 20 defects found (2 HIGH), all fixed same-session.
- Next: Mike reviews DESIGN.md (§18 has 3 decisions for him + paste-ready Perplexity script) → adversarial review via Codex/gstack → ROADMAP.md → P0 implementation.

Blockers for Mike (from SCOPE §8, still open): CoinGecko demo key, Kraken read-only key, GitHub repo `tradekit` + `git init` (folder is not a git repo yet).
