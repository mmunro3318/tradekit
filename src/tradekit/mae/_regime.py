"""HMM regime classification core (SPRINT-P1C story 2 "get_regime", batch B;
DESIGN §9.1 / §3 `get_regime`; addendum "get_regime" bullet + Traps).

Status: P1C batch B STUB — every function below raises `NotImplementedError`
unconditionally. This module is TDD red scaffolding; the dev pass (P1C
batch B implementation) fills each body per the design pins documented
inline. `tradekit.mae.get_regime` (the public verb in `mae/__init__.py`)
stays its own P1 stub this batch and is wired to call `compute_regime`
below in the dev pass — see that function's docstring for the exact
orchestration contract.

hmmlearn is NOT a project dependency yet (`uv add hmmlearn` is the dev
agent's job, sprint doc "New dependencies"). Every function that would need
it (`_fit_hmm`, `_load_artifact` when unpickling a real fitted model)
imports it LAZILY, inside the function body, so this module — and the red
test suite that imports it — loads fine with hmmlearn absent.

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
or not.

**Staleness** (`_is_stale`): the sidecar's `fit_date_utc`, compared against
`_runtime.clock()` (this module never calls a real clock itself — it takes
"now" from the caller, per TD-17), is stale when more than 7 days have
elapsed. A stale or missing/unreadable artifact triggers a refit via
`_fit_hmm` + `_persist_artifact`, and `compute_regime`'s output notes list
gets a `"refit"` entry (exact key TBD by the dev pass reading canonical §3
— canonical does not itself show a notes/warnings field for `get_regime`;
see the ambiguity flagged in `tests/ASSUMPTIONS.md`).

**State labeling** (`_label_states`): given the fitted model's per-state
variance of the realized-vol feature (diag covariance, column index 1),
order state indices by that variance ascending. For `n_states=2`:
lowest-variance state -> `"low_vol_trend"`, highest-variance state ->
`"high_vol_chop"`. For `n_states=3`: lowest -> `"low_vol_trend"`, highest ->
`"breakdown"`, middle -> `"high_vol_chop"` — THIS THREE-WAY MAPPING IS A
SESSION CALL, NOT DERIVED FROM CANONICAL §3, which lists exactly the three
strings `"low_vol_trend" | "high_vol_chop" | "breakdown"` as
`current_state`'s possible values but never states which is the "middle"
vol-variance state; see `tests/ASSUMPTIONS.md`'s new entry for this batch —
CTO ratification needed before this ordering is treated as load-bearing.
Any `n_states` outside `{2, 3}` is out of scope this batch (raise
`ValueError` — not silently generalized).

**EWMA override** (`_ewma_vol`, `_check_ewma_override` — G3, pure
arithmetic on a LOADED artifact, never refits): over the LAST 30 daily
log-returns (from `_build_features`'s log-return column, or recomputed
directly from closes — the dev pass picks whichever avoids double work),
`alpha = 2 / (20 + 1)`; `ewma_var` seeded as `r_0**2` (the OLDEST of the 30,
i.e. index 0 of the 30-slice) then `ewma_var_t = (1 - alpha) * ewma_var_{t-1}
+ alpha * r_t**2` walking forward to the newest; `ewma_vol = sqrt(final
ewma_var)`. The fitted current state's emission params give
`state_mean_vol` (the mean of the realized-vol feature, i.e.
`feature_means[1]` from the persisted sidecar, or the live fit) and
`state_vol_std` (`sqrt` of that state's diag variance on the realized-vol
feature, column index 1). Trigger: `ewma_vol > state_mean_vol +
3 * state_vol_std` -> `compute_regime` returns `method="ewma_override"`,
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
  3. else -> `_RULES_NEUTRAL_STATE` (module constant, currently `"neutral"`
     — NOT one of canonical §3's three enumerated `current_state` strings;
     flagged, not resolved, this batch — see ASSUMPTIONS).
`method="rules"`, plus a warning naming WHY the rules path was taken:
`"insufficient_history"` (< 60 bars) or `"hmm_non_convergence"` (fit
attempted and failed to converge).

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

from datetime import datetime
from pathlib import Path
from typing import Any

from tradekit.contracts import Bar

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

_RULES_NEUTRAL_STATE = "neutral"
"""The rules-fallback grid's third bucket (neither high-vol-chop nor
low-vol-trend). NOT one of canonical §3's three enumerated `current_state`
strings (`low_vol_trend` | `high_vol_chop` | `breakdown`) — a flagged
ambiguity, not a resolved one; see tests/ASSUMPTIONS.md. Tests reference
this constant rather than hardcoding the string so a later CTO ratification
that changes it needs no test-body edits."""

_N_STATES_3_MIDDLE_LABEL = "high_vol_chop"
"""For n_states=3, the middle-variance state's label — a session call
pending CTO ratification (see module docstring's State labeling section
and tests/ASSUMPTIONS.md)."""


def _symbol_slug(symbol: str) -> str:
    """`"/"` -> `"-"` (e.g. `"BTC/USD"` -> `"btc-usd"` is NOT implied — case
    is preserved; only the separator is swapped, per the addendum's
    `hmm-{symbol}-{lookback}.pkl` naming)."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _artifact_paths(symbol: str, lookback_days: int) -> tuple[Path, Path]:
    """`(pkl_path, json_path)` for `symbol`/`lookback_days`, both validated
    to resolve strictly inside `_models_dir` (the sprint's pickle trap) —
    raises `ValueError` on any path that would escape it, BEFORE touching
    the filesystem."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _build_features(bars: list[Bar]) -> list[tuple[float, float]]:
    """`[(log_return_i, realized_vol_i), ...]` — see module docstring's
    Feature construction pin. Bars lacking a full trailing-20 log-return
    window are excluded, never zero-filled."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _fit_hmm(features: list[tuple[float, float]], n_states: int) -> Any:
    """Lazily imports `hmmlearn.hmm.GaussianHMM`, fits
    `GaussianHMM(n_components=n_states, covariance_type="diag",
    random_state=1337, n_iter=200)` on `features`, returns the fitted model.
    Tests monkeypatch THIS function (not hmmlearn itself) to simulate
    non-convergence without hmmlearn installed."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _label_states(state_vol_variances: list[float], n_states: int) -> dict[int, str]:
    """`{state_index: label}` ordering states by `state_vol_variances`
    (ascending) per the State labeling pin. Raises `ValueError` for
    `n_states` outside `{2, 3}`."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


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
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _load_artifact(symbol: str, lookback_days: int) -> tuple[Any, dict[str, Any]] | None:
    """`(model, sidecar_dict)` if both pkl and sidecar exist and validate
    inside `_models_dir`; `None` if missing. Raises `ValueError` (never
    silently falls through) if `_artifact_paths` rejects the resolved path."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _is_stale(fit_date_utc: datetime, now: datetime) -> bool:
    """`now - fit_date_utc > timedelta(days=_STALE_AFTER_DAYS)`."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _ewma_vol(returns: list[float]) -> float:
    """EWMA volatility over `returns` (expects exactly the last 30 daily
    log-returns, oldest-first) per the EWMA override pin: seed
    `ewma_var = returns[0]**2`, then walk forward with `alpha = 2/21`,
    `ewma_vol = sqrt(final ewma_var)`."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _check_ewma_override(
    ewma_vol: float, state_mean_vol: float, state_vol_std: float
) -> bool:
    """`ewma_vol > state_mean_vol + 3 * state_vol_std` — pure comparison,
    no I/O, no refit; isolated so tests can drive it directly with
    artifact-derived numbers instead of hardcoded floats."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def _rules_fallback(bars: list[Bar], reason: str) -> dict[str, Any]:
    """Realized-vol-percentile x ADX(14) grid per the Rules fallback pin.
    `reason` is `"insufficient_history"` or `"hmm_non_convergence"` and is
    surfaced verbatim in the output's warnings. Returns a dict with at
    least `current_state`, `method="rules"`, `warnings`."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")


def compute_regime(symbol: str, lookback_days: int, n_states: int) -> dict[str, Any]:
    """Full orchestration: load-or-refit the HMM artifact (staleness- and
    missing-artifact-triggered refit only), apply the EWMA override check,
    fall back to rules on insufficient history or non-convergence, and
    return the canonical §3 `get_regime` output shape (see
    `tradekit.mae.get_regime`'s docstring for the exact key list) plus the
    addendum-required `method` and `warnings`/notes keys (flagged ambiguity
    vs. canonical §3 — tests/ASSUMPTIONS.md).

    Sources ALL bars via `_runtime.get_daily_bars(symbol, lookback_days)` —
    the ONLY bar-fetch call this function makes; never calls
    `_runtime.provider_for` or a provider directly (Lookahead pin)."""
    raise NotImplementedError("P1C batch B — docs/handoff/SPRINT-P1C-regime-scanner-sizing.md")
