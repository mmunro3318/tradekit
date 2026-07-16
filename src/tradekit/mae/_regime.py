"""HMM regime classification core (SPRINT-P1C story 2 "get_regime", batch B;
DESIGN §9.1 / §3 `get_regime`; addendum "get_regime" bullet + Traps).

Status: P1C batch B IMPLEMENTED (dev pass). `tradekit.mae.get_regime` (the
public verb in `mae/__init__.py`) is wired to
`return _regime.compute_regime(symbol, lookback_days, n_states)`.

hmmlearn IS a project dependency as of this batch (`uv add hmmlearn`), but
`_fit_hmm` still imports it LAZILY inside the function body — the module
itself, and every other function here, stays importable in an environment
that lacks hmmlearn (dep-sync ordering safety, sprint doc "New
dependencies").

=== Design pins (CTO, SPRINT-P1C batch B dispatch; binding on the dev
agent implementing this module) ===

**Models-dir path seam** (batch A lesson, ASSUMPTIONS 45's sibling): any
module that writes files needs a path seam, and every test that triggers
fit/persist must monkeypatch it to `tmp_path` — a test that writes into the
real `data/models/` is a defect (CTO-caught pattern from `_runtime._cache_path`
in batch A). `_models_dir` below is that seam.

**Feature construction** (`_build_features`): per bar i (i >= 1, since a
log-return needs a prior close), `log_return_i = ln(close_i / close_{i-1})`.
`realized_vol_i` = population standard deviation (divide by N, NOT N-1) of
the TRAILING 20 log-returns ending at i (inclusive) — bars whose trailing
window is not yet full (fewer than 20 preceding log-returns available) are
EXCLUDED from the feature matrix entirely, never zero-filled. The feature
matrix is therefore `[[log_return_i, realized_vol_i], ...]` for i where both
values exist, in ascending bar order.

**HMM fit** (`_fit_hmm`, refit path ONLY — never called from the EWMA
override arithmetic path): lazily imports `hmmlearn.hmm.GaussianHMM` and
constructs it as `GaussianHMM(n_components=n_states, covariance_type="diag",
random_state=1337, n_iter=200)`, then `.fit(features)`. This is a seam
function specifically so tests can monkeypatch `_regime._fit_hmm` to force
a non-convergence path (e.g. raising the same exception hmmlearn raises
on non-convergence, or returning a model whose `.monitor_.converged` is
False) without needing hmmlearn installed at all.

**Persistence** (`_artifact_paths`, `_persist_artifact`, `_load_artifact`):
pickle at `{_models_dir}/hmm-{symbol_slug}-{lookback_days}.pkl`
(`symbol_slug` = `symbol` with every `"/"` replaced by `"-"`, via
`_symbol_slug`) plus a sidecar JSON at the same stem with suffix `.json`
holding `fit_date_utc` (ISO-8601 string), `window` (= lookback_days),
`n_states`, and `feature_means` (the fitted feature matrix's column means,
`[mean_log_return, mean_realized_vol]`). `_artifact_paths` path-validates:
it refuses (raises `ValueError`) to return any path that does not resolve
(`Path.resolve()`) inside `_models_dir.resolve()` — the sprint's pinned
pickle trap (Traps: "never load one from outside `data/models/`"). A
symbol crafted to escape via `..` segments (e.g. `"../evil"`) must trigger
this refusal BEFORE any file I/O is attempted, whether the artifact exists
or not. On Windows, a symbol carrying a literal backslash (e.g.
`"..\\..\\secrets"`) is NOT sanitized by `_symbol_slug` (which only
replaces `"/"`), and pathlib's `WindowsPath` treats `"\\"` as a real
separator: joining such a filename onto `_models_dir` silently expands
into MULTIPLE path components instead of the single filename component a
legitimate artifact name always is. `_artifact_paths` therefore validates
two independent things before returning any path: (1) the joined path
resolves strictly inside `_models_dir` (`Path.resolve()` containment), and
(2) the join added EXACTLY one path component (`len(candidate.parts) ==
len(_models_dir.parts) + 1`) — check (2) is what actually catches the
backslash trap, since a crafted name can decompose into components that,
after resolution, still land back inside `_models_dir` without ever
"escaping" it in the naive containment sense.

**Staleness** (`_is_stale`): the sidecar's `fit_date_utc`, compared against
`_runtime.clock()` (this module never calls a real clock itself — it takes
"now" from the caller, per TD-17), is stale when more than 7 days have
elapsed. A stale or missing/unreadable artifact triggers a refit via
`_fit_hmm` + `_persist_artifact`, and `compute_regime`'s output notes list
gets a `"refit"` entry.

**State labeling** (`_label_states`): given the fitted model's per-state
variance of the realized-vol feature (diag covariance, column index 1),
order state indices by that variance ascending. For `n_states=2`:
lowest-variance state -> `"low_vol_trend"`, highest-variance state ->
`"high_vol_chop"`. For `n_states=3`: lowest -> `"low_vol_trend"`, highest ->
`"breakdown"`, middle -> `"high_vol_chop"` (CTO-ratified 2026-07-16, see
`tests/ASSUMPTIONS.md` entry 51). Any `n_states` outside `{2, 3}` is out of
scope this batch (raises `ValueError`).

**EWMA override** (`_ewma_vol`, `_check_ewma_override` — G3, pure
arithmetic on a LOADED artifact, never refits): over the LAST 30 daily
log-returns (recomputed directly from closes, to avoid depending on
`_build_features`'s trailing-20-window exclusion), `alpha = 2 / (20 + 1)`;
`ewma_var` seeded as `r_0**2` (the OLDEST of the 30, i.e. index 0 of the
30-slice) then `ewma_var_t = (1 - alpha) * ewma_var_{t-1} + alpha *
r_t**2` walking forward to the newest; `ewma_vol = sqrt(final ewma_var)`.
`state_mean_vol` is `feature_means[1]` (the OVERALL fitted feature matrix's
realized-vol column mean, from the persisted sidecar or the live fit —
NOT specific to any one state) and `state_vol_std` is `sqrt` of the
LOW-VOL state's diag variance on the realized-vol feature (column index 1)
— the calmest fitted state, used as a stable baseline reference REGARDLESS
of which raw state the latest bar itself decoded into (an extreme
single-bar spike can decode into its own high-variance state, which would
otherwise inflate the threshold band past the very anomaly this override
exists to catch — "blows past any sane fitted low-vol state's mean+3*std
band" per the fixture-freeze commentary). Trigger:
`ewma_vol > state_mean_vol + 3 * state_vol_std` ->
`compute_regime` returns `method="ewma_override"`,
`current_state="high_vol_chop"`, `recommended_strategies=[]`. This check
runs on EVERY call (not just refits), after loading (or refitting, if
stale) the artifact — it can override a fresh-refit's own decoded state.

**Rules fallback** (`_rules_fallback`): used when fewer than 60 daily bars
are available, OR `_fit_hmm` signals non-convergence. Grid, evaluated in
this order (first match wins):
  1. `vol_pctile > 0.8` -> `"high_vol_chop"` (`vol_pctile` = the fraction of
     the window's non-None realized-vol values that are `<=` the latest
     realized-vol value — a `<=`-rank percentile, ties counted inclusive).
  2. else `ADX(14) >= 25` -> `"low_vol_trend"`.
  3. else -> `_RULES_NEUTRAL_STATE` (module constant, `"neutral"` — a
     FOURTH legitimate `current_state` value, CTO-ratified 2026-07-16,
     emitted only by `method="rules"`; see ASSUMPTIONS entry 53).
`method="rules"`, plus a warning naming WHY the rules path was taken:
`"insufficient_history"` (< 60 bars) or `"hmm_non_convergence"` (fit
attempted and failed to converge).

**Recommended/avoid strategy mapping** (`_strategy_tags`, a SESSION-CHOSEN
mapping — not itself CTO-ratified, kept intentionally simple): derived from
canonical §3's example (`low_vol_trend` recommends trend-following tags,
avoids mean-reversion) and extrapolated the obvious opposite for
`high_vol_chop`; `breakdown` and the `ewma_override` result recommend
nothing and avoid everything (a state extreme enough to force an override
or classify as structural breakdown warrants no strategy green-light);
`"neutral"` (rules-only) recommends and avoids nothing — a genuine
no-signal bucket, per ASSUMPTIONS 53's "no-recommendation" ratification.

    low_vol_trend  -> recommend [momentum, breakout];  avoid [mean_reversion]
    high_vol_chop  -> recommend [mean_reversion];       avoid [momentum, breakout]
    breakdown      -> recommend [];                     avoid [momentum, breakout, mean_reversion]
    neutral        -> recommend [];                     avoid []
    (ewma_override forces recommend [] / avoid [momentum, breakout, mean_reversion]
     regardless of the decoded label, per the G3 pin above.)

**Confidence**: for the HMM path, the posterior probability of the current
(decoded) state from `model.predict_proba` on the feature matrix, last row
— `P(current_state | observations)` per canonical §3. For the rules and
ewma_override paths, no real posterior exists; `confidence` is `None`
(documented degraded value — untested by name, so the conservative,
honest choice over a fabricated float).

**Determinism**: identical inputs + the pinned `random_state=1337` seed ->
identical decoded states across repeated fits; loading a persisted artifact
(no refit) must reproduce the exact same `current_state`/`method` as the
fit that produced it, given the same recent bars.

**Lookahead**: `compute_regime` must source ALL bars via
`_runtime.get_daily_bars(symbol, lookback_days)` — never call a provider or
`_runtime.provider_for` directly — since `get_daily_bars` is what strips
the still-open live daily bar (ASSUMPTIONS 45). `compute_regime` passes
`lookback_days` straight through to `get_daily_bars`.
"""

from __future__ import annotations

import json
import math
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from tradekit.contracts import Bar
from tradekit.mae import _runtime
from tradekit.mae._indicators import trend as _trend

# ---------------------------------------------------------------------------
# Seams (batch A pattern: module-level indirections, tests monkeypatch these
# names directly rather than patching the functions that use them).
# ---------------------------------------------------------------------------

_models_dir: Path = Path("data/models")
"""Path seam for all HMM artifact reads/writes. Tests MUST monkeypatch this
to a `tmp_path` before triggering any fit/persist/load — a test that writes
into the real `data/models/` is a defect (batch A `_cache_path` lesson)."""

_STALE_AFTER_DAYS = 7
_MIN_BARS_FOR_HMM = 60
_EWMA_SPAN = 20
_EWMA_ALPHA = 2.0 / (_EWMA_SPAN + 1)
_EWMA_WINDOW = 30
_REALIZED_VOL_WINDOW = 20
_ADX_PERIOD = 14
_VOL_PCTILE_HIGH_VOL_CHOP = 0.8
_ADX_TREND_THRESHOLD = 25.0
_TRADING_DAYS_PER_YEAR = 252

_RULES_NEUTRAL_STATE = "neutral"
"""The rules-fallback grid's third bucket (neither high-vol-chop nor
low-vol-trend). A FOURTH legitimate `current_state` value beyond canonical
§3's three enumerated strings, emitted only by `method="rules"`
(CTO-ratified 2026-07-16, tests/ASSUMPTIONS.md entry 53). Tests reference
this constant rather than hardcoding the string."""

_N_STATES_3_MIDDLE_LABEL = "high_vol_chop"
"""For n_states=3, the middle-variance state's label (CTO-ratified
2026-07-16, tests/ASSUMPTIONS.md entry 51)."""

_STRATEGY_TAGS: dict[str, tuple[list[str], list[str]]] = {
    "low_vol_trend": (["momentum", "breakout"], ["mean_reversion"]),
    "high_vol_chop": (["mean_reversion"], ["momentum", "breakout"]),
    "breakdown": ([], ["momentum", "breakout", "mean_reversion"]),
    _RULES_NEUTRAL_STATE: ([], []),
}
"""Session-chosen recommended/avoid strategy mapping — see module
docstring's "Recommended/avoid strategy mapping" section."""

_EWMA_OVERRIDE_AVOID_STRATEGIES = ["momentum", "breakout", "mean_reversion"]


def _symbol_slug(symbol: str) -> str:
    """`"/"` -> `"-"` (e.g. `"BTC/USD"` -> `"btc-usd"` is NOT implied — case
    is preserved; only the separator is swapped, per the addendum's
    `hmm-{symbol}-{lookback}.pkl` naming)."""
    return symbol.replace("/", "-")


def _artifact_paths(symbol: str, lookback_days: int) -> tuple[Path, Path]:
    """`(pkl_path, json_path)` for `symbol`/`lookback_days`, both validated
    to resolve strictly inside `_models_dir` (the sprint's pickle trap) —
    raises `ValueError` on any path that would escape it, BEFORE touching
    the filesystem."""
    slug = _symbol_slug(symbol)
    stem = f"hmm-{slug}-{lookback_days}"
    models_dir_resolved = _models_dir.resolve()
    expected_parts = len(_models_dir.parts) + 1

    paths: list[Path] = []
    for suffix in (".pkl", ".json"):
        candidate = _models_dir / f"{stem}{suffix}"
        if len(candidate.parts) != expected_parts:
            raise ValueError(
                f"symbol {symbol!r} produces an artifact filename containing a path "
                "separator (Windows backslash trap) — refusing to build a path"
            )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(models_dir_resolved)
        except ValueError as exc:
            raise ValueError(
                f"artifact path for symbol {symbol!r} would escape _models_dir "
                f"({models_dir_resolved})"
            ) from exc
        paths.append(candidate)

    return paths[0], paths[1]


def _build_features(bars: list[Bar]) -> list[tuple[float, float]]:
    """`[(log_return_i, realized_vol_i), ...]` — see module docstring's
    Feature construction pin. Bars lacking a full trailing-20 log-return
    window are excluded, never zero-filled."""
    closes = [float(b.close) for b in bars]
    n = len(closes)
    if n < 2:
        return []

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]

    window = _REALIZED_VOL_WINDOW
    features: list[tuple[float, float]] = []
    for j in range(window - 1, len(log_returns)):
        trailing = log_returns[j - window + 1 : j + 1]
        mean = sum(trailing) / window
        variance = sum((r - mean) ** 2 for r in trailing) / window
        realized_vol = math.sqrt(variance)
        features.append((log_returns[j], realized_vol))
    return features


def _fit_hmm(features: list[tuple[float, float]], n_states: int) -> Any:
    """Lazily imports `hmmlearn.hmm.GaussianHMM`, fits
    `GaussianHMM(n_components=n_states, covariance_type="diag",
    random_state=1337, n_iter=200)` on `features`, returns the fitted model.
    Tests monkeypatch THIS function (not hmmlearn itself) to simulate
    non-convergence without hmmlearn installed."""
    from hmmlearn.hmm import GaussianHMM

    x = np.asarray(features, dtype=np.float64)
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        random_state=1337,
        n_iter=200,
    )
    model.fit(x)
    return model


def _label_states(state_vol_variances: list[float], n_states: int) -> dict[int, str]:
    """`{state_index: label}` ordering states by `state_vol_variances`
    (ascending) per the State labeling pin. Raises `ValueError` for
    `n_states` outside `{2, 3}`."""
    if n_states not in (2, 3):
        raise ValueError(f"n_states must be 2 or 3, got {n_states}")

    order = sorted(range(len(state_vol_variances)), key=lambda i: state_vol_variances[i])
    labels: dict[int, str] = {}
    if n_states == 2:
        labels[order[0]] = "low_vol_trend"
        labels[order[1]] = "high_vol_chop"
    else:
        labels[order[0]] = "low_vol_trend"
        labels[order[1]] = _N_STATES_3_MIDDLE_LABEL
        labels[order[2]] = "breakdown"
    return labels


def _persist_artifact(
    symbol: str,
    lookback_days: int,
    model: Any,
    n_states: int,
    feature_means: tuple[float, float],
    fit_date_utc: datetime,
) -> None:
    """Pickles `model` + writes the sidecar JSON (`fit_date_utc` ISO-8601,
    `window`, `n_states`, `feature_means`) via `_artifact_paths`."""
    pkl_path, json_path = _artifact_paths(symbol, lookback_days)
    _models_dir.mkdir(parents=True, exist_ok=True)

    pkl_path.write_bytes(pickle.dumps(model))
    sidecar = {
        "fit_date_utc": fit_date_utc.isoformat(),
        "window": lookback_days,
        "n_states": n_states,
        "feature_means": list(feature_means),
    }
    json_path.write_text(json.dumps(sidecar))


def _load_artifact(symbol: str, lookback_days: int) -> tuple[Any, dict[str, Any]] | None:
    """`(model, sidecar_dict)` if both pkl and sidecar exist and validate
    inside `_models_dir`; `None` if missing. Raises `ValueError` (never
    silently falls through) if `_artifact_paths` rejects the resolved path."""
    pkl_path, json_path = _artifact_paths(symbol, lookback_days)
    if not pkl_path.exists() or not json_path.exists():
        return None
    try:
        model = pickle.loads(pkl_path.read_bytes())
        sidecar: dict[str, Any] = json.loads(json_path.read_text())
    except (pickle.UnpicklingError, json.JSONDecodeError, OSError, EOFError):
        return None
    return model, sidecar


def _is_stale(fit_date_utc: datetime, now: datetime) -> bool:
    """`now - fit_date_utc > timedelta(days=_STALE_AFTER_DAYS)`."""
    return (now - fit_date_utc) > timedelta(days=_STALE_AFTER_DAYS)


def _ewma_vol(returns: list[float]) -> float:
    """EWMA volatility over `returns` (expects exactly the last 30 daily
    log-returns, oldest-first) per the EWMA override pin: seed
    `ewma_var = returns[0]**2`, then walk forward with `alpha = 2/21`,
    `ewma_vol = sqrt(final ewma_var)`."""
    ewma_var = returns[0] ** 2
    for r in returns[1:]:
        ewma_var = (1 - _EWMA_ALPHA) * ewma_var + _EWMA_ALPHA * r**2
    return math.sqrt(ewma_var)


def _check_ewma_override(
    ewma_vol: float, state_mean_vol: float, state_vol_std: float
) -> bool:
    """`ewma_vol > state_mean_vol + 3 * state_vol_std` — pure comparison,
    no I/O, no refit; isolated so tests can drive it directly with
    artifact-derived numbers instead of hardcoded floats."""
    return ewma_vol > state_mean_vol + 3 * state_vol_std


def _strategy_tags(state: str) -> tuple[list[str], list[str]]:
    """`(recommended_strategies, avoid_strategies)` for `state` — see
    module docstring's "Recommended/avoid strategy mapping" section."""
    recommended, avoid = _STRATEGY_TAGS.get(state, ([], []))
    return list(recommended), list(avoid)


def _average_run_length(decoded: Any, state_index: int) -> float:
    """Average length (in bars) of consecutive runs of `state_index` within
    the decoded state sequence `decoded` — used for `avg_state_duration_days`.
    `0.0` if `state_index` never appears (should not happen for the current
    state, since it is drawn from the sequence's own last element)."""
    run_lengths: list[int] = []
    current_val: int | None = None
    current_len = 0
    for raw in decoded:
        v = int(raw)
        if v == current_val:
            current_len += 1
        else:
            if current_val is not None:
                run_lengths.append(current_len if current_val == state_index else -1)
            current_val = v
            current_len = 1
    if current_val is not None:
        run_lengths.append(current_len if current_val == state_index else -1)

    matching = [length for length in run_lengths if length >= 0]
    return float(sum(matching) / len(matching)) if matching else 0.0


def _state_metrics_from_decoded(
    features: list[tuple[float, float]], decoded: Any, state_index: int
) -> dict[str, float]:
    """`state_metrics` dict (`annualized_vol`, `mean_return_daily`,
    `avg_state_duration_days`) for the decoded HMM path, restricted to rows
    assigned to `state_index`."""
    matching_idx = [i for i in range(len(features)) if int(decoded[i]) == state_index]
    returns_for_state = [features[i][0] for i in matching_idx]
    vols_for_state = [features[i][1] for i in matching_idx]

    mean_return_daily = (
        sum(returns_for_state) / len(returns_for_state) if returns_for_state else 0.0
    )
    mean_vol = sum(vols_for_state) / len(vols_for_state) if vols_for_state else 0.0
    annualized_vol = mean_vol * math.sqrt(_TRADING_DAYS_PER_YEAR)

    return {
        "annualized_vol": annualized_vol,
        "mean_return_daily": mean_return_daily,
        "avg_state_duration_days": _average_run_length(decoded, state_index),
    }


def _rules_fallback(bars: list[Bar], reason: str) -> dict[str, Any]:
    """Realized-vol-percentile x ADX(14) grid per the Rules fallback pin.
    `reason` is `"insufficient_history"` or `"hmm_non_convergence"` and is
    surfaced verbatim in the output's warnings. Returns a dict with at
    least `current_state`, `method="rules"`, `warnings`, plus the rest of
    the canonical §3 output shape (schema keys present, values honestly
    degraded — no HMM state index/confidence exists on this path)."""
    closes = [float(b.close) for b in bars]
    highs = [float(b.high) for b in bars]
    lows = [float(b.low) for b in bars]

    features = _build_features(bars)
    vol_series = [v for _, v in features]

    if vol_series:
        latest_vol = vol_series[-1]
        vol_pctile = sum(1 for v in vol_series if v <= latest_vol) / len(vol_series)
    else:
        latest_vol = 0.0
        vol_pctile = 0.0

    adx_result = _trend.adx(highs, lows, closes, period=_ADX_PERIOD)
    adx_last = next((v for v in reversed(adx_result.adx) if v is not None), 0.0)

    if vol_pctile > _VOL_PCTILE_HIGH_VOL_CHOP:
        current_state = "high_vol_chop"
    elif adx_last >= _ADX_TREND_THRESHOLD:
        current_state = "low_vol_trend"
    else:
        current_state = _RULES_NEUTRAL_STATE

    mean_return_daily = (
        sum(r for r, _ in features) / len(features) if features else 0.0
    )
    annualized_vol = latest_vol * math.sqrt(_TRADING_DAYS_PER_YEAR)

    recommended, avoid = _strategy_tags(current_state)

    return {
        "current_state": current_state,
        "state_index": None,
        "confidence": None,
        "state_metrics": {
            "annualized_vol": annualized_vol,
            "mean_return_daily": mean_return_daily,
            "avg_state_duration_days": None,
        },
        "recommended_strategies": recommended,
        "avoid_strategies": avoid,
        "method": "rules",
        "warnings": [reason],
    }


def compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, Any]:
    """Full orchestration: load-or-refit the HMM artifact (staleness- and
    missing-artifact-triggered refit only), apply the EWMA override check,
    fall back to rules on insufficient history or non-convergence, and
    return the canonical §3 `get_regime` output shape (see
    `tradekit.mae.get_regime`'s docstring for the exact key list) plus the
    addendum-required `method` and `warnings`/notes keys.

    Sources ALL bars via `_runtime.get_daily_bars(symbol, lookback_days)` —
    the ONLY bar-fetch call this function makes; never calls
    `_runtime.provider_for` or a provider directly (Lookahead pin)."""
    if n_states not in (2, 3):
        raise ValueError(f"n_states must be 2 or 3, got {n_states}")

    # Path-escape validation FIRST, before any bar fetch or filesystem I/O
    # (the sprint's pinned pickle trap — see module docstring).
    _artifact_paths(symbol, lookback_days)

    bar_series = _runtime.get_daily_bars(symbol, lookback_days)
    bars = bar_series.bars

    if len(bars) < _MIN_BARS_FOR_HMM:
        result = _rules_fallback(bars, reason="insufficient_history")
        result["symbol"] = symbol
        return result

    now = _runtime.clock()
    warnings: list[str] = []

    loaded = _load_artifact(symbol, lookback_days)
    model: Any = None
    feature_means: tuple[float, float] | None = None
    need_refit = True

    if loaded is not None:
        candidate_model, sidecar = loaded
        fit_date = datetime.fromisoformat(sidecar["fit_date_utc"])
        if sidecar.get("n_states") == n_states and not _is_stale(fit_date, now):
            model = candidate_model
            feature_means = (
                float(sidecar["feature_means"][0]),
                float(sidecar["feature_means"][1]),
            )
            need_refit = False

    features = _build_features(bars)

    if need_refit:
        try:
            fitted = _fit_hmm(features, n_states)
            converged = bool(getattr(getattr(fitted, "monitor_", None), "converged", True))
        except Exception:
            fitted = None
            converged = False

        if fitted is None or not converged:
            result = _rules_fallback(bars, reason="hmm_non_convergence")
            result["symbol"] = symbol
            return result

        model = fitted
        mean_log_return = sum(f[0] for f in features) / len(features)
        mean_realized_vol = sum(f[1] for f in features) / len(features)
        feature_means = (mean_log_return, mean_realized_vol)
        _persist_artifact(symbol, lookback_days, model, n_states, feature_means, now)
        warnings.append("refit")

    assert model is not None
    assert feature_means is not None

    feature_matrix = np.asarray(features, dtype=np.float64)
    decoded = model.predict(feature_matrix)
    current_raw_state = int(decoded[-1])

    state_vol_variances = [float(model.covars_[s][1][1]) for s in range(n_states)]
    labels = _label_states(state_vol_variances, n_states)

    # EWMA 3-sigma override (G3) — pure arithmetic on the loaded/fitted
    # artifact, runs on EVERY call, never triggers a refit.
    closes = [float(b.close) for b in bars]
    log_returns_all = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    last_30 = log_returns_all[-_EWMA_WINDOW:]

    if last_30:
        ewma_vol = _ewma_vol(last_30)
        # Reference the LOW-VOL state's std, not necessarily the raw current
        # decoded state's — a single extreme observation (e.g. the planted
        # spike this override exists to catch) can itself get decoded into
        # its own high-variance state, which would inflate the threshold
        # band past the very anomaly it should flag. The low-vol state is
        # the model's calm baseline and stays a stable reference regardless
        # of which state the latest bar decoded into (see module docstring's
        # EWMA override pin: "blows past any sane fitted LOW-VOL state's
        # mean+3*std band").
        low_vol_state_index = min(range(n_states), key=lambda s: state_vol_variances[s])
        state_vol_std = math.sqrt(state_vol_variances[low_vol_state_index])
        if _check_ewma_override(ewma_vol, feature_means[1], state_vol_std):
            return {
                "symbol": symbol,
                "current_state": "high_vol_chop",
                "state_index": current_raw_state,
                "confidence": None,
                "state_metrics": _state_metrics_from_decoded(features, decoded, current_raw_state),
                "recommended_strategies": [],
                "avoid_strategies": list(_EWMA_OVERRIDE_AVOID_STRATEGIES),
                "method": "ewma_override",
                "warnings": warnings,
            }

    current_state = labels[current_raw_state]
    recommended, avoid = _strategy_tags(current_state)
    proba = model.predict_proba(feature_matrix)
    confidence = float(proba[-1][current_raw_state])

    return {
        "symbol": symbol,
        "current_state": current_state,
        "state_index": current_raw_state,
        "confidence": confidence,
        "state_metrics": _state_metrics_from_decoded(features, decoded, current_raw_state),
        "recommended_strategies": recommended,
        "avoid_strategies": avoid,
        "method": "hmm",
        "warnings": warnings,
    }
