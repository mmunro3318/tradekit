# TICKET-001 — Scan-attrition telemetry + the S1 "wait" bottleneck

> Opened 2026-07-23 (Opus session, with Mike). Diagnostic evidence gathered
> live against the real providers. This ticket both **names a confirmed root
> cause** and **specs the telemetry** that should have surfaced it on day one.
> Discipline: the config fix in §4.1 is a strategy-behavior change — it ships
> *with* the telemetry (§4.2) and a CTO sign-off, never as a silent flip
> (seed red-line: no strategy-dial change without numbers on the table).

## 1. Problem

Every `tk hud` scan since ops went live (~7/19) has graded all 11 pairs
`wait` — zero advisory tickets, zero `AdvisoryTicketAcked`, zero
`ThesisGraded`. The scan report says only *"no surviving setup signal tags
(absent or dropped by regime gate)"* per symbol. That message cannot tell
Mike **which filter killed the candidate**, so "the market is quiet" and
"the scanner is broken" are indistinguishable from the outside. Tonight
they turned out to be **both at once**.

## 2. Evidence gathered tonight (equity $5000 → prop now $4963.57)

Ran the setup scan by hand, decomposed per filter, on real 4h bars:

| pair | 4h bars | macd_hist | vol_ratio | macd>0 (bullish) | vol≥1.5 |
|---|---|---|---|---|---|
| ETH/USD | 179 | −6.9143 | 1.443 | ✗ | ✗ |
| SOL/USD | 179 | −0.2629 | 2.059 | ✗ | ✓ |
| LINK/USD | 179 | −0.0312 | 0.421 | ✗ | ✗ |
| XRP/USD | 179 | −0.0048 | 0.828 | ✗ | ✗ |
| AVAX/USD | 179 | −0.0251 | 3.709 | ✗ | ✓ |
| NEAR/USD | 179 | −0.0035 | 0.276 | ✗ | ✗ |
| RENDER/USD | 179 | −0.0053 | 0.767 | ✗ | ✗ |
| TAO/USD | 179 | −0.5487 | 0.951 | ✗ | ✗ |
| AKT/USD | 179 | −0.0017 | 0.788 | ✗ | ✗ |
| EIGEN/USD | 179 | −0.0008 | 2.112 | ✗ | ✓ |
| PAXG/USD | 179 | −7.4806 | 1.209 | ✗ | ✗ |

Two independent facts fall out:

### 2a. CONFIRMED BUG — the momentum filter is a guaranteed reject-all
`hud/_build.py` ships `_SETUP_FILTERS = {"macd_signal": "bullish", "volume_spike": 1.5}`.
But `mae/_scanner.py` (lines ~250–260) accepts **only** the canonical enum
`"bullish_cross"`/`"bearish_cross"` and sends everything else down an
unconditional `else: return None`:

```python
want = filters["macd_signal"]            # "bullish"  (from _SETUP_FILTERS)
if want == "bullish_cross":   ...        # not taken
elif want == "bearish_cross": ...        # not taken
else:
    return None                          # <-- EVERY candidate dies here, always
```

The scanner's own module docstring (line 46) **explicitly warns** against the
`"bullish"`/`"bearish"` spelling. So as currently wired, S1 rejects every
symbol at the MACD stage **on every scan, in every regime, at every price** —
it has been structurally incapable of firing a ticket since the constant was
written. Empirically: `scan(filters={"macd_signal":"bullish",...})` → 0
matches with **0 warnings** (the silent `else` path — no insufficient-bars
warning, nothing).

### 2b. GENUINE MARKET — even corrected, S1 correctly finds nothing *right now*
Swap in `"bullish_cross"` and re-scan: still 0 matches — because **all 11
pairs have a negative MACD histogram** (broad crypto weakness on the 4h). S1
is a momentum-long strategy; with no bullish momentum anywhere, 0 setups is
the *correct* answer. Three pairs (SOL, AVAX, EIGEN) have the volume spike,
but none have the momentum, so the AND-composition legitimately yields none.

**The lesson this ticket exists to institutionalize:** without per-filter
telemetry you cannot tell 2a (broken) from 2b (correctly quiet). Tonight it
was both. The fix for 2a is one word; the guard against ever being blind to
it again is the telemetry.

## 3. Root-cause hypotheses (ranked; 3a/3b now confirmed, rest still open)

1. **[CONFIRMED] macd enum mismatch** — `"bullish"` vs `"bullish_cross"`.
   Structural, market-independent, total. Fix in §4.1.
2. **[CONFIRMED contributing] bearish regime** — every scanned pair is in
   negative-momentum territory; post-fix S1 still (correctly) fires nothing
   until momentum turns. Not a bug; a market state to *observe*, not tune away.
3. **[OPEN] volume threshold calibration** — `volume_spike ≥ 1.5` cleared
   only 3/11 tonight. Is 1.5 right for these low-liquidity alts? Telemetry
   over several scan-days answers this; do NOT touch it before then.
4. **[OPEN] regime-gate tag-stripping** — even a genuine `bullish_cross` +
   volume match can have its strategy tag dropped by the regime gate
   (`_scanner.py` §"Regime gate"). We have never observed this path fire
   because 3a blocked everything upstream. Telemetry must instrument the
   gate as its own attrition stage.

## 4. Scaffolded solution

### 4.1 Fix the enum (small, but treat as a strategy-behavior change)
- Change `_SETUP_FILTERS["macd_signal"]` → `"bullish_cross"` in
  `src/tradekit/hud/_build.py`.
- **Harden the contract so this class of bug fails loud, not silent:** the
  scanner's `else: return None` swallows an invalid filter enum. Replace it
  with a raised error (e.g. `ValueError(f"unknown macd_signal value {want!r}; "
  f"expected bullish_cross|bearish_cross")`) so a bad filter value is a loud
  crash at scan time, never a silent reject-all. This is the real defect — the
  string was fixable, the *silence* is what let it hide for days.
- TDD: red test proving `scan(filters={"macd_signal":"bullish"})` now raises
  (not returns `[]`); red test proving a synthetic bullish-cross+volume bar
  fixture produces a match with `signal_tags=["macd_bullish","volume_spike"]`.
- **⚠ A CURRENT TEST CODIFIES THE BUG.** The test audit (docs/reviews/
  test-audit-2026-07-23.md) found `tests/.../test_scan_markets_verb.py:490`
  feeds an unknown filter value (`"sideways"`) and asserts `matches == []` —
  i.e. it locks in the silent-drop as *correct*. Production's `"bullish"` is
  exactly that "unknown value," so the suite was green **because** S1 was
  broken; making the enum raise loud will turn this test RED. This is an
  R-rule-adjacent test change (a test asserting behavior we now consider a
  defect) — invert it deliberately, with a numbered `tests/ASSUMPTIONS.md`
  entry ratifying "unknown filter value MUST raise, not silently drop." Do NOT
  edit it to pass without that ratification (red-line: never edit a test to
  make impl pass).
- **Ships with §4.2 and CTO sign-off in the same batch** — a live momentum
  filter with no attrition visibility is how we got here.

### 4.2 Scan-attrition telemetry (the log Mike asked for)
Thread a per-pair, per-stage attrition record out of `_scanner.scan` (it
already computes each filter's pass/fail and the insufficient-bars reason —
today it just discards the "why"). Surface it two ways:

- **A run log** written per scan to `data/scans/<UTC-date>/scan-<HHMMSS>.log`
  (append-only, human-readable, the format below).
- **A ledger note** (`ScanAttritionRecorded` or a lightweight note event) so
  the audit trail can answer "which filter killed candidates on 7/24?"
  without re-running. Read-side only — no policy surface, no money path.

**Stages to instrument, in evaluation order** (each pair walks them until it
dies or emits a ticket):
`data_integrity` (≥20 bars) → `macd_signal` → `volume_spike` →
`regime_gate` (tag survival) → `sizing` (qty>0) → `policy_verdict`.

**Log format** (Mike's sketch, wired to real stage/field names):

```
====== New Scan ======
11:53:42  07/23/2026  prop $4963.57  equity $5000  universe=11 pairs  tf=4h
------------------------------------------------------------------------
NEAR/USD
  data_integrity   PASS   179 bars (≥20)
  macd_signal      FAIL   hist=-0.0035  needs bullish_cross (hist>0)
  → dropped at macd_signal
SOL/USD
  data_integrity   PASS   179 bars
  macd_signal      FAIL   hist=-0.2629  needs bullish_cross (hist>0)
  → dropped at macd_signal   (note: volume PASSED, 2.059≥1.5 — momentum is the blocker)
...
------------------------------------------------------------------------
SUMMARY  scanned=11  tickets=0
  attrition:  data_integrity 0 | macd_signal 11 | volume_spike 0 | regime_gate 0 | sizing 0 | policy 0
  killer filter: macd_signal (11/11)  → market: all pairs negative-momentum
======================================================================
```

The `SUMMARY` line is the payoff: after two scan-days it names the killer
filter *with counts*, which is exactly the tune-vs-replace decision input the
seed asked for — and it would have flagged 2a on the very first run.

## 5. Acceptance criteria

- [ ] Invalid `macd_signal` value raises loudly at scan time (regression test).
- [ ] Corrected filter produces a match against a bullish-cross fixture (test).
- [ ] Every scan writes an attrition log in the §4.2 format + a ledger note.
- [ ] After 2 real scan-days, the `killer filter` line names the blocker with
      numbers — no human re-derivation needed.
- [ ] `gate: uv run pytest -q && ruff && mypy` green; no money-path surface touched.

## 6. Out of scope (tracked elsewhere)
- HUD Confirm/Failed buttons fire silently + non-idempotently (each click
  books another `/ack`; two `failed` events landed tonight from repeated
  clicking). Separate UX/idempotency ticket — see handoff.
- Advisory (`advisory:kraken`) has no balance feed, so the loop settles
  against the `paper:alpha` $500 dial, not real prop equity (ASSUMPTIONS
  round-20). Separate ticket.
- Kraken Prop: no working bracket-order flow; mobile-only for entry;
  manual exits. OPERATIONS.md step 3 is wrong — see FRICTION.md + handoff.
