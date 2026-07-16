"""Pearson correlation math core (SPRINT-P1C story 3; DESIGN §9.1 / §3
`get_correlation_matrix`; addendum "Correlation pins").

Pure, offline, numpy-free in its shipped arithmetic (a small in-house sum-
of-products formula — `numpy.corrcoef`/`pandas.DataFrame.corr` are allowed
only as DERIVATION-time cross-checks for the test goldens, per the
fixture-freeze rule, never inside this module). `mae.get_correlation_matrix`
(`mae/__init__.py`) is the only intended caller — it resolves symbols to
daily closes via `_runtime.get_daily_bars` (crypto/equity) or
`_data.macro.get_macro_bars` (macro tickers — exact wiring TBD, non-gating
per the addendum), converts each symbol's closes to its OWN log-return
series (`ln(c_t / c_{t-1})` over that symbol's consecutive closed daily
bars — note this means a crypto symbol's Monday return spans the weekend
gap since crypto trades every day, while an equity symbol's Monday return
spans Friday-to-Monday; that asymmetry is intentional, not a bug, standard
cross-asset-correlation practice), and hands the per-symbol return series
here.

This module's exact internal signature is a private, SESSION-CHOSEN shape
(nothing in the canonical doc or addendum pins it beyond "a small in-house
function") — documented here rather than pinned externally:

    compute_correlation(
        series_by_symbol: dict[str, list[tuple[date, float]]],
        *,
        min_overlap: int = 20,
        high_corr_threshold: float = 0.75,
    ) -> CorrelationResult

`series_by_symbol` maps symbol -> list of `(UTC calendar date, daily
log-return)` pairs, already converted from closes by the caller — this
module does no bar parsing or Decimal handling, only the pairwise
UTC-date inner join + Pearson + threshold-flagging math (P1B-style
`_indicators` purity: numbers in, numbers out).

Join semantics: the inner join is evaluated PER PAIR, not once across the
whole symbol set — two symbols keep every date a THIRD symbol lacks
entirely out of their own pairwise statistic (so a 7-day crypto series
correlated against BOTH a 5-day equity series AND a 6-day macro series uses
5 dates for the first pair and 6 for the second, independently).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class CorrelationResult:
    """`matrix[a][b]` is `None` when the pair's joined-date overlap is below
    `min_overlap` (never a silently-computed number on too little data,
    R-013); self-pairs (`a == b`) are always exactly `1.0`, never computed.
    `insufficient_overlap_warnings` and `high_correlation_warnings` each
    name the pair once (unordered — `(a, b)` and `(b, a)` are the same
    pair and appear only once, `a < b` lexicographically)."""

    matrix: dict[str, dict[str, float | None]]
    insufficient_overlap_warnings: list[tuple[str, str, int]]
    high_correlation_warnings: list[tuple[str, str, float]]


def compute_correlation(
    series_by_symbol: dict[str, list[tuple[date, float]]],
    *,
    min_overlap: int = 20,
    high_corr_threshold: float = 0.75,
) -> CorrelationResult:
    """Pairwise Pearson r over UTC-date inner-joined log-returns.

    For each unordered pair `(a, b)` with `a != b`: inner-join
    `series_by_symbol[a]` and `series_by_symbol[b]` on date, then compute
    Pearson r over the joined value pairs via the standard sum-of-products
    formula (`r = sum((x-mean_x)*(y-mean_y)) /
    sqrt(sum((x-mean_x)**2) * sum((y-mean_y)**2))`). If the joined overlap
    has fewer than `min_overlap` points, `matrix[a][b]` (and `matrix[b][a]`)
    is `None` and `(a, b, overlap_count)` (a < b) is appended to
    `insufficient_overlap_warnings`. Otherwise the computed r populates both
    `matrix[a][b]` and `matrix[b][a]` (correlation is symmetric), and if
    `abs(r) > high_corr_threshold`, `(a, b, r)` (a < b) is appended to
    `high_correlation_warnings`. Every `matrix[s][s]` is exactly `1.0`.
    """
    symbols = sorted(series_by_symbol)
    matrix: dict[str, dict[str, float | None]] = {s: {s: 1.0} for s in symbols}
    insufficient: list[tuple[str, str, int]] = []
    high_corr: list[tuple[str, str, float]] = []

    for i, a in enumerate(symbols):
        for b in symbols[i + 1 :]:
            by_date_a = dict(series_by_symbol[a])
            by_date_b = dict(series_by_symbol[b])
            shared_dates = sorted(set(by_date_a) & set(by_date_b))
            overlap = len(shared_dates)

            if overlap < min_overlap:
                matrix[a][b] = None
                matrix[b][a] = None
                insufficient.append((a, b, overlap))
                continue

            xs = [by_date_a[d] for d in shared_dates]
            ys = [by_date_b[d] for d in shared_dates]
            mean_x = sum(xs) / overlap
            mean_y = sum(ys) / overlap
            dx = [x - mean_x for x in xs]
            dy = [y - mean_y for y in ys]
            numerator = sum(px * py for px, py in zip(dx, dy, strict=True))
            denom = (sum(px * px for px in dx) * sum(py * py for py in dy)) ** 0.5
            r = numerator / denom if denom != 0 else 0.0

            matrix[a][b] = r
            matrix[b][a] = r
            if abs(r) > high_corr_threshold:
                high_corr.append((a, b, r))

    return CorrelationResult(
        matrix=matrix,
        insufficient_overlap_warnings=insufficient,
        high_correlation_warnings=high_corr,
    )


__all__ = ["CorrelationResult", "compute_correlation"]
