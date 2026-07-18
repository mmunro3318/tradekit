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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tradekit.contracts import Event, EventFilter
from tradekit.ledger import Ledger
from tradekit.policy._dials import PolicyDials

_WINDOW = timedelta(days=30)


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
    0; `epoch - 1s` lands in series -1).

    `timedelta // timedelta` is Python's own true floor division (floors
    toward negative infinity, not toward zero) — exactly the boundary
    semantics pinned above, including the negative-index case."""
    return (grade_ts - epoch) // _WINDOW


def window_for(series_idx: int, epoch: datetime) -> tuple[datetime, datetime]:
    """`(window_start, window_end)` for `series_idx` — the inverse of
    `series_index`: `window_start = epoch + 30d * series_idx`,
    `window_end = window_start + 30d` (right-open, matching `series_index`'s
    own boundary convention)."""
    start = epoch + _WINDOW * series_idx
    end = start + _WINDOW
    return start, end


def _account_thesis_ids(ledger: Ledger, account_ref: str) -> set[str]:
    """Every `thesis_id` whose `ThesisDrafted.contract.account_ref` matches
    (mirrors `policy._context`'s own account-scoping helpers)."""
    return {
        str(event.payload.get("thesis_id"))
        for event in ledger.query(EventFilter(types=["ThesisDrafted"]))
        if event.payload.get("contract", {}).get("account_ref") == account_ref
    }


def _graded_ts(event: Event) -> datetime:
    raw = event.payload.get("graded_ts")
    if raw is not None:
        ts = datetime.fromisoformat(raw)
    else:
        ts = event.ts_utc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


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
    epoch = dials.series_epoch
    window_start, window_end = window_for(series_idx, epoch)

    thesis_ids = _account_thesis_ids(ledger, account_ref)
    all_graded = [
        event
        for event in ledger.query(EventFilter(types=["ThesisGraded"]))
        if event.payload.get("thesis_id") in thesis_ids
    ]

    in_window = sorted(
        (event for event in all_graded if window_start <= _graded_ts(event) < window_end),
        key=_graded_ts,
    )

    graded_count = sum(1 for e in in_window if e.payload.get("outcome") in ("PASS", "FAIL"))
    void_count = sum(1 for e in in_window if e.payload.get("outcome") == "VOID")

    non_void_pnls = [
        Decimal(str(e.payload.get("pnl_usd")))
        for e in in_window
        if e.payload.get("outcome") in ("PASS", "FAIL") and e.payload.get("pnl_usd") is not None
    ]
    expectancy = (
        sum(non_void_pnls, Decimal("0")) / len(non_void_pnls) if non_void_pnls else None
    )

    # Equity entering the window: paper_starting_equity_usd + realized pnl
    # from THIS account's own graded theses strictly BEFORE window_start
    # (module docstring — the MDD walk itself is per-account, so its base
    # must be too; review round-14 HIGH: pooling every account's pnl here
    # let a winning sibling account's pre-window pnl inflate this account's
    # base and launder a genuinely dirty MDD into a falsely clean one).
    # None-pnl contributes no cash flow. Scoped via the same
    # `_account_thesis_ids` set used for `all_graded`/`in_window` above.
    equity_entering = dials.paper_starting_equity_usd
    for event in all_graded:
        if _graded_ts(event) < window_start:
            pnl = event.payload.get("pnl_usd")
            if pnl is not None:
                equity_entering += Decimal(str(pnl))

    equity = equity_entering
    peak = equity
    mdd_pct_value = 0.0
    for event in in_window:
        pnl = event.payload.get("pnl_usd")
        equity += Decimal(str(pnl)) if pnl is not None else Decimal("0")
        peak = max(peak, equity)
        if peak > 0:
            mdd_pct_value = max(mdd_pct_value, float((peak - equity) / peak))
    mdd_pct: float | None = mdd_pct_value

    gate_violations = sum(
        1
        for event in ledger.query(EventFilter(types=["GateViolationDetected"]))
        if event.payload.get("account_ref") == account_ref
        and window_start <= event.ts_utc.astimezone(UTC) < window_end
    )

    complete = now > window_end and graded_count >= 10
    clean = (
        complete
        and gate_violations == 0
        and expectancy is not None
        and expectancy > 0
        and mdd_pct is not None
        and mdd_pct < 0.15
    )

    return SeriesStats(
        account_ref=account_ref,
        series_index=series_idx,
        window_start=window_start,
        window_end=window_end,
        graded_count=graded_count,
        void_count=void_count,
        expectancy=expectancy,
        mdd_pct=mdd_pct,
        gate_violations=gate_violations,
        complete=complete,
        clean=clean,
    )


def maybe_close_series(
    ledger: Ledger, account_ref: str, series_idx: int, dials: PolicyDials, now: datetime
) -> str | None:
    """SPRINT P3 batch E (sprint-doc addendum): `SeriesClosed` EMISSION +
    idempotence. Unconditional `NotImplementedError` stub this batch — NOT
    called from `policy.promotion_status()` yet (that real, already-green
    verb is deliberately left untouched by this batch's red phase, so the
    pre-existing promotion/series test suites stay green; wiring this
    helper INTO `promotion_status()`'s call graph is the dev pass's job,
    together with whatever `promotion_status()` test updates that wiring
    requires — flagged in tests/ASSUMPTIONS.md round-21, not silently
    assumed here).

    DESIGN PIN (CTO addendum, binding on the dev pass): if
    `series_stats(ledger, account_ref, series_idx, dials, now).complete` is
    True AND no `SeriesClosed` event already exists for THIS exact
    `(account_ref, series_index)` pair, append exactly one `SeriesClosed`
    (`contracts.SeriesClosedPayload`, fields mirroring the `SeriesStats`
    the check itself just computed) and return the new event_id. A window
    that is not yet complete, OR one that already has a `SeriesClosed`
    event, is a no-op that returns `None` (idempotence: a second call for
    the same closed window never appends a duplicate)."""
    raise NotImplementedError(
        "SPRINT P3 batch E — policy._series.maybe_close_series (SeriesClosed emission)"
    )


__all__ = ["SeriesStats", "maybe_close_series", "series_index", "series_stats", "window_for"]
