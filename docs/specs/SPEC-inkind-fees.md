# SPEC — In-kind crypto fee representation (Alpaca)

> Branch: `feature/inkind-fees`. Money-path adjacent (`broker/`) → review
> round required before commit of green.
> Ground truth: 2026-07-26 Mike-run live $5 ETH round trip (dev-log 07-26b).

## Scope

Represent Alpaca's real crypto fee physics — the fee is withheld **in-kind
from the received asset** (buys: fee in the crypto asset; sells: fee in the
USD proceeds) — across the fill payload, PaperBroker fill physics,
AlpacaBroker fill recording, paper position derivation, and `compute_pnl`,
so paper trades grade under the same physics live trades settle under.
Today `CostModel`/ledger assume USD-side fees on both legs (ASSUMPTIONS
142/146), which diverges filled qty from held qty and mis-states edge.

**Measured ground truth (live receipts):**
- Buy: `filled_qty=0.002602483` ETH @ 1883.57 → position held
  `0.002595976`. Withheld `0.000006507` ETH
  = `0.0025 × 0.002602483 = 0.0000065062075` rounded **up** at 9 dp
  (ROUND_HALF_EVEN would give `...506`; observed `...507`).
- Sell: `0.002595976` @ 1882.03, gross proceeds `4.88570471128` (exact
  Decimal product; an earlier draft of this section said `4.88570533…` —
  transcription slip, the golden's in-file derivation governs); account
  went $50.00 → $49.97, consistent with a further
  `0.0025 × proceeds ≈ $0.0122` withheld from the USD received.
- Round-trip P&L closes: `4.8857053 − 0.0122143 − 4.9021583 ≈ −$0.0287`
  ≈ dashboard −$0.03 (cent display).

## Out of scope

- Exit-order verb (does not exist yet). **Carried-forward pin for the batch
  that builds it (cadence batch): sells MUST be sized from the NET position
  (`positions()`), never from entry `filled_qty`** — the live smoke run
  proved a full-qty sell would be rejected/leave dust.
- `compute_pnl` short branch (crypto spot is long-only; existing behavior
  and tests stand untouched).
- Multi-fill / partial exits (already out of scope per `compute_pnl`
  docstring; entry=first fill, exit=last fill convention stands).
- Wiring `side` into P&L attribution (P2 harness fixtures lack `side`;
  ordering convention stands — pre-existing deferral).
- Kraken-venue crypto fee physics (unmeasured; keeps the USD-fee model).
- Cent-quantization of `fees_usd` (ASSUMPTIONS 146c tension with existing
  sub-cent fixture values — pre-existing, not touched here).
- Backfilling fee estimates on historical fills; reconcile match-key
  changes.

## Interface pins

```python
# contracts/_event_payloads.py — FillRecordedPayload gains ONE field:
fee_asset_qty: Decimal = Decimal("0")
# Asset units withheld in-kind from the RECEIVED asset on this fill.
# Buys (alpaca crypto): > 0, denominated in the crypto asset.
# Sells, equities, all historical events/fixtures: 0 (default preserves
# every existing serialized event and P2 fixture unchanged).
```

```python
# costs.py — one new accessor; _TABLE stays the single rate source:
def fee_rate(venue: str, asset_class: str) -> Decimal:
    """Fee rate for one side. Unknown venue dies loudly (same taxonomy as
    price_friction — a venue without a cost table must never price as
    free)."""
```

```python
# In-kind withhold arithmetic (PaperBroker AND AlpacaBroker, buys where
# venue == "alpaca" and asset_class == "crypto"):
fee_asset_qty = (fee_rate("alpaca", "crypto") * qty).quantize(
    Decimal("1e-9"), rounding=ROUND_CEILING
)  # PROVISIONAL rounding: single live observation; see Unknowns U1
fees_usd = fee_asset_qty * fill_price  # USD valuation, for reporting/P&L
# Paper buy cash delta: -(qty * fill_price) EXACTLY — fee is no longer a
# separate cash deduction; it is embodied in the withheld qty.
```

```python
# PaperBroker.positions() qty derivation (per symbol):
qty = sum(buy.qty - buy.fee_asset_qty) - sum(sell.qty)
```

```python
# thesis/_grade_wiring.compute_pnl — long, two-fill round trip:
#   entry = earliest fill, exit = latest (convention unchanged)
pnl = (exit.qty * exit.price - exit.fees_usd) \
      - (entry.qty * entry.price) \
      - (entry.fees_usd if entry.fee_asset_qty == 0 else Decimal("0"))
# Rationale: an in-kind entry fee is ALREADY realized as the reduced exit
# qty — subtracting its USD valuation too would double-count. A USD-fee
# entry (equities, all legacy fixtures) still subtracts, preserving every
# existing pinned value.
# Single-fill thesis: pnl = -fill.fees_usd (unchanged legacy pin).
```

Error taxonomy: no new error types. `fee_rate` raises exactly what
`price_friction` raises on unknown `(venue, asset_class)`.

## Acceptance criteria

```
AC-1: GIVEN a serialized FillRecorded event from before this change
       (no fee_asset_qty key)
      WHEN it is validated through FillRecordedPayload
      THEN it parses successfully and fee_asset_qty == Decimal("0")

AC-2: GIVEN PaperBroker buy, venue alpaca, asset_class crypto,
       qty Q, fill price P — BOTH fill paths (market
       _evaluate_and_record_market_fill AND _record_limit_fill)
      WHEN the fill is recorded
      THEN fee_asset_qty == (Decimal("0.0025") * Q).quantize(1e-9, CEILING),
           fees_usd == fee_asset_qty * P, and the account cash delta is
           exactly -(Q * P)

AC-3: GIVEN PaperBroker market sell, venue alpaca, asset_class crypto
      WHEN the fill is recorded
      THEN fee_asset_qty == 0 and cash delta == +(Q * P) - fees_usd
           with fees_usd from price_friction (unchanged sell physics)

AC-4: GIVEN PaperBroker buy, venue alpaca, asset_class equity
      WHEN the fill is recorded
      THEN fee_asset_qty == 0 and behavior is byte-identical to today
           (fee rate 0)

AC-5: GIVEN an in-kind crypto buy of qty Q with withhold W
      WHEN PaperBroker.positions() is read
      THEN the position qty == Q - W; and after selling exactly Q - W the
           account is flat (same flat representation as today)

AC-6: GIVEN AlpacaBroker._record_fill_from_order for a crypto buy order
       (respx fixture; Alpaca response carries NO fee field — measured
       fact, ASSUMPTIONS 142)
      WHEN the fill is recorded
      THEN fee_asset_qty == ceil9(0.0025 * filled_qty) and
           fees_usd == fee_asset_qty * filled_avg_price

AC-7 (GOLDEN): GIVEN the two live-receipt fills verbatim
       (buy 0.002602483 @ 1883.57 with fee_asset_qty 0.000006507;
        sell 0.002595976 @ 1882.03 with fees_usd 0.0025×proceeds)
      WHEN compute_pnl runs (direction long)
      THEN pnl == Decimal("4.88570533…") - exit_fees - Decimal("4.90215833…")
           (exact Decimals derived in-test from the pinned inputs),
           ≈ -0.0287, agreeing with the venue's $50.00→$49.97 to the cent.
      Derivation source (independent): Alpaca live order receipts +
      account balance delta, 2026-07-26 (dev-log 07-26b).

AC-8: GIVEN a single-fill thesis (any fee representation)
      WHEN compute_pnl runs
      THEN pnl == -fill.fees_usd (legacy pin preserved)

AC-9: GIVEN the existing legacy USD-fee round-trip fixture
       (test_grade_verb values, fee_asset_qty absent→0)
      WHEN compute_pnl runs
      THEN the result equals today's pinned value unchanged (regression)

AC-10: GIVEN fee_rate("nosuch", "crypto")
       WHEN called
       THEN it raises the same loud error price_friction raises (never 0)

AC-11: GLOSSARY.md gains "in-kind fee" / fee_asset_qty entries;
       tests/ASSUMPTIONS.md gains a numbered append documenting the
       in-kind convention and the PROVISIONAL ceiling rounding
       (supersedes-notes 142's USD-only framing; append-only).
```

Refusal/error paths: AC-1 (backward compat is the refusal-to-break path),
AC-10 (unknown venue). No new user-facing refusals.

**Note on existing tests:** AC-2's cash-delta change and fees_usd values
contradict pins in `test_paper_fills.py` / `test_paper_account_state.py`.
Those pins change **because the specified behavior changes** — each edited
assertion must cite the AC it now implements (reviewer verifies per red
line: this is spec-driven re-pinning, not editing-tests-to-pass).

## Test plan sketch

| AC | Kind | Home |
|---|---|---|
| AC-1 | CONTRACT | tests/unit/contracts |
| AC-2..5 | BEHAVIOR | tests/unit/broker (test_paper_fills / _account_state) |
| AC-6 | BEHAVIOR | tests/unit/broker/test_alpaca_broker (respx) |
| AC-7 | GOLDEN | tests/golden — derivation: live receipts + balance delta |
| AC-8, AC-9 | BEHAVIOR (regression) | tests/unit/thesis/test_grade_verb |
| AC-10 | BEHAVIOR | tests/unit/test_costs |
| AC-11 | doc inventory check (review round) | — |

## Unknowns register

- **U1 — rounding mode of the venue withhold.** ROUND_CEILING at 1e-9
  matches the single live observation (HALF_EVEN does not). PROVISIONAL;
  re-measure on the 3 probationary live trades and amend the ASSUMPTIONS
  entry if contradicted. Not blocking.
- **U2 — does any Alpaca feed expose the fee explicitly?** The paper
  activities feed doesn't (captured fixture). Live activities feed
  unprobed; if it does, measured-fee reconciliation becomes possible
  later. Not blocking.
- **U3 — Kraken venue fee physics** — unmeasured, out of scope, USD model
  stands there.
