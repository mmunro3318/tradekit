"""Series accounting — internal to `policy` (DESIGN §7.3; CTO addendum,
story-4 pins, SPRINT P2 batch D). `tests/unit/policy/test_series.py` is this
module's own test suite.

Status (batch D TDD-red pass, same "Failing tests + minimal stubs" discipline
as every other P2 red-phase module — thesis's grade()/void() stayed
unconditional `NotImplementedError` stubs through their own red passes even
though the arithmetic they wrap (`_grading.evaluate_criteria`) was already
real and frozen; `_series.py` gets the identical treatment here): EVERY
function below is an unconditional `NotImplementedError` stub. This differs
from `_dials.py`/`_rules.py` (which the CTO explicitly called REAL in the
batch-C red/green split) — no equivalent call has been made for `_series.py`
this batch, so it defaults to stub, per the batch-D dispatch's own literal
instruction ("Failing tests + minimal stubs"). The dev pass implements the
arithmetic pinned in every docstring below.

DESIGN PINS (CTO addendum, story-4 pins — binding on the dev pass):

- `series_index(grade_ts, epoch) = floor((grade_ts - epoch) / 30 days)` —
  PURE UTC calendar arithmetic, no timezone-local drift (sprint doc
  "Traps"). A thesis belongs to the series containing its GRADE timestamp
  (not activation, not submission). Boundary pin: `grade_ts == epoch` -> 0;
  `grade_ts == epoch + 30d` exactly -> 1 (NOT 0 — the window is
  right-open, `[epoch + 30d*k, epoch + 30d*(k+1))`); `grade_ts == epoch -
  1s` -> -1.

- Series stats are DERIVED AT READ TIME from `ThesisGraded`/
  `GateViolationDetected` events for the given `account_ref` + series
  index — there is NO `SeriesClosed` event in P2 (the taxonomy reserves
  the type per §6.3, but no P2 producer ever appends it; ASSUMPTIONS
  flags this as a P3-deferred row). The `series` projection table
  (`_projections.py`) materializes per-series rows from the SAME
  derivation on `ledger.rebuild()`, for CLI/report reads — the derivation
  here and the projection's population must agree byte-for-byte.

- `graded_count` = count of `ThesisGraded` events in-window with
  `outcome in {"PASS", "FAIL"}` (non-void). `void_count` = count with
  `outcome == "VOID"`.

- `expectancy` = mean of `pnl_usd` over graded NON-VOID theses whose
  `pnl_usd` is NOT None (ASSUMPTIONS 71's forward-pin: None-pnl theses are
  EXCLUDED from the expectancy aggregation but still counted in
  `graded_count`/`void_count`). If ZERO non-void theses in-window have a
  non-None `pnl_usd`, `expectancy` is `None` — this is NOT "vacuously
  clean" (unmeasurable != clean, anti-permissive): a series with no
  measured pnl can never be `clean`, regardless of everything else.

- `mdd_pct` (intra-series max drawdown, as a positive fraction): walk the
  in-window graded theses in `graded_ts` order, cumulative pnl (None
  treated as 0 for the WALK only — a None-pnl thesis contributes no cash
  flow to the equity curve, distinct from being excluded from expectancy),
  starting equity = `paper_starting_equity_usd` + realized pnl from ALL
  graded theses (any account) strictly BEFORE this window's start (equity
  entering the window) — track peak-to-trough over
  `equity_entering + cumulative_pnl`, `mdd_pct = max(peak - trough) /
  peak_at_that_point`.

- `gate_violations` = count of `GateViolationDetected` events for this
  `account_ref` with `ts_utc` inside `[window_start, window_end)`.

- `complete` = `now > window_end` (window closed) AND
  `graded_count >= 10`. `clean` = `complete` AND `gate_violations == 0`
  AND `expectancy is not None` AND `expectancy > 0` AND `mdd_pct < 0.15`.
  A window not yet closed is ALWAYS incomplete, regardless of count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tradekit.ledger import Ledger
from tradekit.policy._dials import PolicyDials


@dataclass(frozen=True)
class SeriesStats:
    """Return shape for `series_stats()` (documented here so the dev pass
    doesn't have to invent field names — the tests below construct their
    EXPECTED values against exactly this shape). Not a `contracts` model:
    never ledgered, never cross-boundary — an internal `policy` read-time
    value, same status as `PolicyContext`."""

    account_ref: str
    series_index: int
    window_start: datetime
    window_end: datetime
    graded_count: int
    void_count: int
    expectancy: Decimal | None
    mdd_pct: float | None
    gate_violations: int
    complete: bool
    clean: bool


def series_index(grade_ts: datetime, epoch: datetime) -> int:
    """`floor((grade_ts - epoch) / 30 days)` — pure, no I/O. See module
    docstring's boundary pin (`epoch + 30d` exactly lands in series 1, not
    0; `epoch - 1s` lands in series -1)."""
    raise NotImplementedError(
        "P2 batch D dev pass — docs/handoff/SPRINT-P2-thesis-policy.md story 4, "
        "CTO addendum 'series_index(grade_ts, epoch) = floor((grade_ts - epoch) / 30d)'"
    )


def window_for(series_idx: int, epoch: datetime) -> tuple[datetime, datetime]:
    """`(window_start, window_end)` for `series_idx` — the inverse of
    `series_index`: `window_start = epoch + 30d * series_idx`,
    `window_end = window_start + 30d` (right-open, matching `series_index`'s
    own boundary convention)."""
    raise NotImplementedError(
        "P2 batch D dev pass — docs/handoff/SPRINT-P2-thesis-policy.md story 4"
    )


def series_stats(
    ledger: Ledger,
    account_ref: str,
    series_idx: int,
    dials: PolicyDials,
    now: datetime,
) -> SeriesStats:
    """Derive `SeriesStats` for `(account_ref, series_idx)` at read time from
    `ThesisGraded`/`GateViolationDetected` events — see module docstring for
    the full arithmetic pin (graded_count/void_count/expectancy/mdd_pct/
    gate_violations/complete/clean)."""
    raise NotImplementedError(
        "P2 batch D dev pass — docs/handoff/SPRINT-P2-thesis-policy.md story 4"
    )


__all__ = ["SeriesStats", "series_index", "series_stats", "window_for"]
