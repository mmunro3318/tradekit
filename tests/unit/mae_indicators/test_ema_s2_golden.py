"""GOLDEN — EMA hand-derivation for STRATEGY-PACK S2 (`ema_above` filter,
docs/design/STRATEGY-PACK.md "Vocabulary additions" table: "EMA(n) of
closes (EMA seeded with SMA(n), standard recursive form)").

EMA REUSABILITY FINDING (dispatch mission item, reported to CTO): EMA is
NOT a new indicator this batch. `tradekit.mae._indicators.trend.ema` is a
complete, already-golden-tested (`tests/unit/mae_indicators/test_trend.py`
`test_ema_golden_vector` et al.) public surface matching the doc's exact
pinned seeding convention verbatim (SMA-seed of the first `period` values,
then `ema[i] = values[i]*k + ema[i-1]*(1-k)`, `k = 2/(period+1)` —
`trend.ema`'s own docstring states this identically). The doc's
conditional ("if EMA not in indicators yet, implement there") does NOT
trigger — no new production code is needed for the indicator itself, only
for wiring `ema_above` into `_scanner._precompute_indicators`/
`_evaluate_symbol_timeframe` (the scanner-vocabulary side, covered by
test_s2_pullback_strategy.py's ema_above tests, not this file).

This file still pins a FRESH, small (5-value), independently hand-derived
golden against the public indicator surface per the dispatch mission's
explicit instruction ("If EMA already exists somewhere reusable, still pin
the golden against the public indicator surface and note it") — it does
NOT reuse test_trend.py's existing EMA(20) golden vector (period=20, loaded
from a fixture file); this is a distinct, smaller, hand-worked check scoped
to S2's own dispatch requirement, kept in its own file (S2's tests should
not touch/modify the pre-existing P1B `test_trend.py`, per surgical-change
discipline).

GOLDEN derivation (by hand, EMA(3) over 5 closes — NOT computed via the
indicator under test):

    closes = [10.0, 20.0, 30.0, 40.0, 50.0], period = 3
    k = 2 / (period + 1) = 2 / 4 = 0.5

    ema[0] = None                     (index < period-1 = 2, no seed yet)
    ema[1] = None                     (index < period-1 = 2, no seed yet)
    ema[2] = SMA(closes[0:3])         seed: (10.0 + 20.0 + 30.0) / 3
           = 60.0 / 3 = 20.0
    ema[3] = closes[3]*k + ema[2]*(1-k)
           = 40.0*0.5 + 20.0*0.5
           = 20.0 + 10.0 = 30.0
    ema[4] = closes[4]*k + ema[3]*(1-k)
           = 50.0*0.5 + 30.0*0.5
           = 25.0 + 15.0 = 40.0

    expected = [None, None, 20.0, 30.0, 40.0]

RED stage: this golden is expected to PASS today (`trend.ema` already
exists and is already correct) — it is included per the dispatch mission's
explicit instruction to pin the golden regardless of reuse, not because it
is expected to fail. The S2 RED-ness for `ema_above` lives entirely in
test_s2_pullback_strategy.py (the scanner-vocabulary wiring, which does
not exist yet)."""

from __future__ import annotations

import pytest

from tradekit.mae._indicators.trend import ema


def test_ema_period_3_five_value_hand_derived_golden() -> None:
    closes = [10.0, 20.0, 30.0, 40.0, 50.0]
    out = ema(closes, period=3)
    expected: list[float | None] = [None, None, 20.0, 30.0, 40.0]
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(expected[2])
    assert out[3] == pytest.approx(expected[3])
    assert out[4] == pytest.approx(expected[4])
