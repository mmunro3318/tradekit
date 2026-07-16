"""tests for `tradekit.mae._regime`'s pure/structural internals (SPRINT-P1C
batch B, story 2 "get_regime" — HMM + EWMA 3-sigma override + rules
fallback).

TEST-PATH EXCEPTION (extends ASSUMPTIONS 23/29/39/44): this file imports
`tradekit.mae._regime` directly — no public verb wraps it yet this batch
(`tradekit.mae.get_regime` stays an unconditional `NotImplementedError`
stub; the dev pass wires it to `_regime.compute_regime`, same shape as
`_correlation`/`_runtime`'s existing exceptions). Full-orchestration tests
(persistence, staleness, EWMA override, rules-fallback grid, non-convergence,
lookahead) live in `test_get_regime_verb.py`, which calls `_regime.
compute_regime` directly with `_runtime.get_daily_bars` faked by dotted
STRING monkeypatch (batch A pattern) — that file's docstring explains why
that counts as the "verb-level" split even though the public verb itself
is untouched this batch.

Status: `_regime.py` is a P1C batch B STUB (every function raises
`NotImplementedError` unconditionally) — every test below currently fails
with `NotImplementedError`, the expected red state for this batch. hmmlearn
is NOT installed for this red pass (module lazily imports it only inside
`_fit_hmm`'s real body, which does not exist yet) — none of these tests
import or require hmmlearn.

FIXTURE-FREEZE: every hand-derived number below traces to
`derive_p1c_batchB.py` (session scratchpad, never committed), section
numbers cited inline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tradekit.contracts import AssetRef, Bar
from tradekit.mae import _regime

_ASSET = AssetRef(symbol="BTC/USD", venue="kraken", asset_class="crypto", tick_size=Decimal("0.01"))


def _bar(
    ts_open: datetime, close: float, *, high: float | None = None, low: float | None = None
) -> Bar:
    h = high if high is not None else close + 0.3
    lo = low if low is not None else close - 0.3
    return Bar(
        ts_open=ts_open,
        open=Decimal(str(close)),
        high=Decimal(str(h)),
        low=Decimal(str(lo)),
        close=Decimal(str(close)),
        volume=Decimal("1000"),
    )


def _bars_from_closes(closes: list[float]) -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [_bar(start + timedelta(days=i), c) for i, c in enumerate(closes)]


# ---------------------------------------------------------------------------
# _symbol_slug
# ---------------------------------------------------------------------------


def test_symbol_slug_replaces_slash_with_dash() -> None:
    assert _regime._symbol_slug("BTC/USD") == "BTC-USD"


def test_symbol_slug_equity_symbol_unchanged() -> None:
    assert _regime._symbol_slug("SPY") == "SPY"


# ---------------------------------------------------------------------------
# _artifact_paths — the sprint's pinned pickle trap (Traps: "never load one
# from outside data/models/"). _symbol_slug only sanitizes "/" -> "-"; a
# symbol carrying a WINDOWS path separator ("\") survives that replacement
# untouched, so `_artifact_paths` must independently validate the resolved
# path lands inside `_models_dir` rather than trusting the slug alone.
# ---------------------------------------------------------------------------


def test_artifact_paths_normal_symbol_resolves_inside_models_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    pkl_path, json_path = _regime._artifact_paths("BTC/USD", 90)
    assert pkl_path.resolve().parent == tmp_path.resolve()
    assert json_path.resolve().parent == tmp_path.resolve()
    assert pkl_path.name == "hmm-BTC-USD-90.pkl"
    assert json_path.name == "hmm-BTC-USD-90.json"


def test_artifact_paths_backslash_escape_symbol_raises_value_error(monkeypatch, tmp_path) -> None:
    """`_symbol_slug` only replaces `"/"`; a symbol containing `"\\.."`
    segments is NOT sanitized by that rule alone and, unvalidated, would
    resolve OUTSIDE `_models_dir` on Windows (backslash is a real path
    separator there) — `_artifact_paths` must catch this independently,
    per the addendum's path-validation pin, BEFORE any file I/O."""
    monkeypatch.setattr(_regime, "_models_dir", tmp_path)
    with pytest.raises(ValueError):
        _regime._artifact_paths("..\\..\\secrets", 90)


# ---------------------------------------------------------------------------
# _build_features — log-return + trailing-20 realized-vol feature pairs;
# insufficient-window bars EXCLUDED, never zero-filled.
# ---------------------------------------------------------------------------


def test_build_features_excludes_bars_with_insufficient_trailing_window() -> None:
    # 25 bars -> 24 log-returns (index 0 has no prior close). realized_vol
    # needs a full trailing-20-return window, so only returns at index
    # >= 19 (0-based within the 24-return series) qualify -> 24-19 = 5
    # feature rows.
    closes = [100.0 + i for i in range(25)]
    bars = _bars_from_closes(closes)

    features = _regime._build_features(bars)

    assert len(features) == 5, (
        f"expected 5 feature rows (24 returns, trailing-20 window fills at "
        f"return index 19), got {len(features)}"
    )


def test_build_features_log_return_arithmetic_two_bars() -> None:
    # Minimal 21-bar constant-step series lets us hand-check the FIRST
    # qualifying feature row's log_return exactly: closes = 100..120 (step
    # +1/day). log_return at index 20 = ln(120/119).
    import math

    closes = [100.0 + i for i in range(21)]
    bars = _bars_from_closes(closes)

    features = _regime._build_features(bars)

    assert len(features) == 1
    log_return, _realized_vol = features[0]
    assert log_return == pytest.approx(math.log(120.0 / 119.0), abs=1e-12)


# ---------------------------------------------------------------------------
# _label_states — order by fitted variance; n_states=2 unambiguous, n_states=3
# middle-label mapping is a FLAGGED (not CTO-ratified) session call — see
# module docstring and tests/ASSUMPTIONS.md.
# ---------------------------------------------------------------------------


def test_label_states_two_states_lowest_variance_is_low_vol_trend() -> None:
    # state 0 has the LOWER vol-feature variance -> low_vol_trend; state 1
    # (higher variance) -> high_vol_chop, regardless of index order in the
    # input list (the function must sort by variance, not by index).
    labels = _regime._label_states([0.0004, 0.04], n_states=2)
    assert labels == {0: "low_vol_trend", 1: "high_vol_chop"}


def test_label_states_two_states_order_independent_of_index() -> None:
    # Same two variances, swapped index order -> labels must still track
    # variance, not position.
    labels = _regime._label_states([0.04, 0.0004], n_states=2)
    assert labels == {0: "high_vol_chop", 1: "low_vol_trend"}


def test_label_states_three_states_middle_uses_flagged_constant() -> None:
    """n_states=3 ordering: lowest variance -> low_vol_trend, highest ->
    breakdown, middle -> `_regime._N_STATES_3_MIDDLE_LABEL` (currently
    "high_vol_chop") — asserted via the module constant, NOT a hardcoded
    string literal, because this mapping is flagged as CTO-unratified
    (canonical §3 never states which of its three current_state values is
    the vol-variance middle one)."""
    labels = _regime._label_states([0.02, 0.0001, 0.5], n_states=3)
    assert labels[1] == "low_vol_trend"  # variance 0.0001 is the lowest
    assert labels[2] == "breakdown"  # variance 0.5 is the highest
    assert labels[0] == _regime._N_STATES_3_MIDDLE_LABEL  # variance 0.02 is the middle


def test_label_states_rejects_unsupported_n_states() -> None:
    with pytest.raises(ValueError):
        _regime._label_states([0.1, 0.2, 0.3, 0.4], n_states=4)


# ---------------------------------------------------------------------------
# _ewma_vol — pinned 5-point worked example (derive_p1c_batchB.py Section 1a,
# alpha = 2/21). Full derivation shown, not just the endpoint, per the
# fixture-freeze "show the arithmetic" discipline.
# ---------------------------------------------------------------------------


def test_ewma_vol_five_point_hand_derived() -> None:
    # returns = [0.01, -0.02, 0.015, 0.03, -0.01]; alpha = 2/21 =
    # 0.09523809523809523.
    #   i=0: ewma_var = 0.01**2            = 0.0001
    #   i=1: ewma_var = 0.9047619...*0.0001 + 0.0952381...*0.0004
    #                 = 0.00012857142857142858
    #   i=2: ewma_var = 0.00013775510204081632
    #   i=3: ewma_var = 0.00021034985422740523
    #   i=4 (final): ewma_var = 0.00019984034430098568
    #     -> ewma_vol = sqrt(0.00019984034430098568) = 0.014136489815402751
    returns = [0.01, -0.02, 0.015, 0.03, -0.01]

    ewma_vol = _regime._ewma_vol(returns)

    assert ewma_vol == pytest.approx(0.014136489815402751, abs=1e-15)


def test_ewma_vol_single_return_is_its_own_absolute_value() -> None:
    # seed-only case: ewma_var = r_0**2 -> ewma_vol = |r_0|.
    assert _regime._ewma_vol([0.02]) == pytest.approx(0.02, abs=1e-15)


# ---------------------------------------------------------------------------
# _check_ewma_override — pure comparison, no I/O.
# ---------------------------------------------------------------------------


def test_check_ewma_override_triggers_when_strictly_above_threshold() -> None:
    # threshold = mean + 3*std = 0.01 + 3*0.002 = 0.016; ewma_vol=0.02 > 0.016.
    triggered = _regime._check_ewma_override(
        ewma_vol=0.02, state_mean_vol=0.01, state_vol_std=0.002
    )
    assert triggered is True


def test_check_ewma_override_does_not_trigger_below_threshold() -> None:
    triggered = _regime._check_ewma_override(
        ewma_vol=0.015, state_mean_vol=0.01, state_vol_std=0.002
    )
    assert triggered is False


def test_check_ewma_override_boundary_is_exclusive() -> None:
    # ewma_vol exactly AT mean+3*std must NOT trigger (spec: "ewma_vol >
    # state_mean_vol + 3*state_vol_std", strict inequality).
    threshold = 0.01 + 3 * 0.002
    triggered = _regime._check_ewma_override(
        ewma_vol=threshold, state_mean_vol=0.01, state_vol_std=0.002
    )
    assert triggered is False


# ---------------------------------------------------------------------------
# _is_stale — 7-day boundary, compared against a caller-supplied "now"
# (never a real clock inside this module, TD-17).
# ---------------------------------------------------------------------------


def test_is_stale_exactly_seven_days_is_not_stale() -> None:
    fit_date = datetime(2026, 7, 1, tzinfo=UTC)
    now = fit_date + timedelta(days=7)
    assert _regime._is_stale(fit_date, now) is False


def test_is_stale_eight_days_is_stale() -> None:
    fit_date = datetime(2026, 7, 1, tzinfo=UTC)
    now = fit_date + timedelta(days=8)
    assert _regime._is_stale(fit_date, now) is True


def test_is_stale_fresh_artifact_is_not_stale() -> None:
    fit_date = datetime(2026, 7, 1, tzinfo=UTC)
    now = fit_date + timedelta(hours=1)
    assert _regime._is_stale(fit_date, now) is False


# ---------------------------------------------------------------------------
# _rules_fallback — reason plumbing (grid-outcome tests, which need concrete
# ADX/vol-pctile-shaped bar fixtures, live in test_get_regime_verb.py via
# compute_regime, per the sprint's "assert the resulting STATE" instruction).
# ---------------------------------------------------------------------------


def test_rules_fallback_surfaces_reason_in_warnings() -> None:
    closes = [100.0 + i for i in range(45)]
    bars = _bars_from_closes(closes)

    result = _regime._rules_fallback(bars, reason="insufficient_history")

    assert result["method"] == "rules"
    assert "insufficient_history" in result["warnings"]


def test_rules_fallback_non_convergence_reason_surfaced() -> None:
    closes = [100.0 + i for i in range(45)]
    bars = _bars_from_closes(closes)

    result = _regime._rules_fallback(bars, reason="hmm_non_convergence")

    assert "hmm_non_convergence" in result["warnings"]
