# SPRINT P3→P4 — Paper trading, review, reporting, memory, live proof

> Coarser than P1/P2 docs by design: by the time you're here, the patterns (ports, conformance suites, event-sourcing, adversarial replays) are established — copy them. Split into sessions along the story boundaries below. Executor: Sonnet; Opus for the fill model, the reconcile→halt path, and anything touching live keys. References: DESIGN §8, §11, §12, TD-6/7/8/19/21, G5/G6.

## P3 stories

### 3.1 BrokerPort + conformance suite
Port per DESIGN §8.1 (five methods; `submit` takes the VerdictToken). Write the conformance suite FIRST (`tests/contract/test_broker_port.py`) — every adapter passes the same suite; that's what makes venue swap safe (TD-18 ring 2).

### 3.2 PaperBroker (TD-7 — our own; Opus reviews the fill model)
- Named accounts = ledger projections (`paper:alpha`, …), seeded by a `tk account create-paper` verb + event.
- Market fills: latest cached quote mid ± half-spread from `tradekit.costs`, plus fee; quote snapshot stored ON the Fill (§8.3 — every fill auditable).
- Limit fills: bar must trade THROUGH the limit by ≥1 tick — exact touch is NOT a fill (G5). No partials. Deterministic: same cache ⇒ same fills (replay test).
- Known-optimism note (§8.3) stays true at ≤$25 notionals; do not gold-plate the microstructure.

### 3.3 `broker.execute_order` — the two-phase money pipeline (Opus)
Exactly §8.2: ActionProposed → policy.evaluate → VerdictIssued → (deny ⇒ exit 1 with Verdict) → adapter.submit(order, verdict_token) → OrderSubmitted/Ack → fill polling → FillRecorded → thesis activation. `tk order submit|status|cancel`. Adapters REFUSE without an allow-token. Reconcile (`tk account reconcile`): broker records vs ledger; ANY mismatch → ReconciliationRun(mismatch) + automatic HaltSet (§8.2 step 7). Test the halt path — it's the last line of §15.

### 3.4 Review module (TD-21)
`LLMReviewerPort` → subprocess adapters (Codex CLI default, Gemini alt — both exist on Mike's machine via gstack). Attack/defense as structured JSON exchanges; rubric scoring DETERMINISTIC in Python (`prompts/rubric-thesis-v1.md` — write it with Mike); unresolved attack ≥ threshold blocks approval. Auto-fail short-circuits BEFORE spending tokens: missing numeric EV, no falsifiable catalyst, size ≠ SizingComputed. Artifacts ledgered. Tests: fake reviewer adapter (canned JSON) — never a real LLM call in tests. VOID sign-off (`verify_claim`) rides the same port.

### 3.5 ManualBroker + advisory mode (D16)
`submit` raises `AdvisoryOnly`; `tk fill record` writes Fills with `actor=mike`; Kraken read-only key drives balance tracking (needs Mike's key). R-009/R-014 already enforced by policy — advisory accounts just flow through.

### 3.6 Memory + reporting (`tradekit.memory`, `tradekit.report`)
`tk brief` (≤ ~1.5k tokens: promotion state + attempt stats (D7), open positions, active theses, last 10 grades, halts, top-salience lessons); `tk search` (ledger FTS + wiki front-matter; decide multi-word semantics — phrase vs AND — and PIN it in ASSUMPTIONS, it was left open in P0); `tk wiki add`; daily memo + readiness report + pnl snapshot templates per DESIGN §12.3/SME §3. Research-loop lead/scout prompts (D14) into `prompts/` — Sonnet drafts, Mike approves tone/shape.

### 3.7 P3 done-gate
End-to-end replay: scan → thesis → review (fake adapter) → gates → order → paper fill → grade → memo, reproducible from the event log. Seed the $5k/$5k paper distribution with long-term theses (SCOPE Pass C).

## P4 stories (live proof — D4; every step pairs with Mike)

1. Alpaca PAPER dress rehearsal through the real API (order lifecycle parity vs PaperBroker conformance).
2. Mike: live keys + $50–100. Keys enter `.env` only; never echoed, never committed (TD-19).
3. Real promotion: readiness report → `tk promote confirm` → 3-trade budget.
4. 3-trade live sequence (long-only, liquid large-caps/BTC/ETH per R-004) → `reconcile` green after each → auto-revert to T1 (R-011).
5. `tk report snapshot` → `verify_claim` with a non-Anthropic model confirms trades/settlement/P&L vs broker records. **That's the MVP done-gate. Stop, celebrate, retro in the dev log.**

## Traps

- Paper determinism dies if fills read the LIVE quote at call time — fills read the CACHED quote referenced by the order event, so replays reproduce.
- Reviewer subprocesses: timeouts + max-token caps + treat stdout as untrusted data (parse JSON strictly; a chatty model must not crash the pipeline).
- `tk brief` token budget is a hard cap — truncate by salience, never silently overflow (it's every agent's first read).
- P4 live keys: if anything reconciles wrong, HALT stays set until Mike manually clears — no auto-resume on the live path, ever.
