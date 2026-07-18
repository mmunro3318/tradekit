"""tradekit.ledger.models — typed read-model accessors (DESIGN §4.2's
`tradekit.ledger` public-interface row: "models (typed read-model
accessors)"; SPRINT P3 batch E).

`Ledger.models` (see `ledger/__init__.py`) constructs one `LedgerModels`
instance per `Ledger` — cheap declarative wiring, same "cheap construction"
status as `broker.get()`'s account-prefix routing / `PaperBroker.__init__`
(SPRINT P3 batch B, ASSUMPTIONS round-20's own precedent list) — so THAT
constructor call is real. Every METHOD below is an unconditional
`NotImplementedError` stub this batch; `tests/unit/ledger/test_models.py`
pins the real target behavior (never wrapped in
`pytest.raises(NotImplementedError)`, same discipline as every other
red-phase module this sprint).

DESIGN PINS (CTO, sprint-doc batch-E line item — binding on the dev pass):

- `active_theses()`: every row of the `theses` projection table
  (`ledger/_projections.py`) whose `state == "active"`, as `ActiveThesis`
  values (`thesis_id`, `account_ref`, `strategy_tag`). Reads the PROJECTION
  (post-`rebuild()`), not raw events — same "projections are the read
  surface" convention `_series.py`'s docstring already establishes for
  `series`/`promotion_state`. `tk grade sweep` (SPRINT P3 batch E, CLI)
  calls this when invoked with no `--thesis` args (additive: explicit ids
  still work) — the auto-discovery gap `tests/ASSUMPTIONS.md`'s batch-C
  entry flagged as a coverage hole closes here.

- `account_refs()`: every distinct `account_ref` the ledger has ever seen —
  the UNION of the `accounts` projection table's own `account_ref` column
  (TD-24 `AccountCreated`-driven rows) and every `theses.account_ref` value
  (a P2-era account, e.g. the default `paper:alpha`, may trade without ever
  getting an explicit `AccountCreated` — TD-24's own "P2's default account
  gets an IMPLICIT AccountConfig" pin), sorted for determinism. `None`
  account_refs (malformed/legacy rows, if any) are excluded — every entry
  in the returned list is a real, non-empty string.

- `latest_grades(n=10)`: the `n` most recently graded theses (by
  `graded_ts` descending — ties broken by `thesis_id` ascending for
  determinism), as `GradeRecord` values (`thesis_id`, `account_ref`,
  `outcome`, `pnl_usd`, `graded_ts`). `pnl_usd` reads the owning
  `ThesisGraded` event's own payload field (not the `theses` projection,
  which does not carry pnl) — `outcome`/`graded_ts` may be read off either
  the projection or the event; the dev pass picks whichever avoids a
  double-derivation, per `_series.py`'s existing "derivation and
  projection must agree byte-for-byte" discipline. `tk brief`'s "last 10
  grades" section (DESIGN §11) is this accessor's first real consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from tradekit.contracts import EventFilter

if TYPE_CHECKING:
    from tradekit.ledger import Ledger


@dataclass(frozen=True)
class ActiveThesis:
    """`active_theses()`'s per-row return shape — an internal `ledger` read
    value, same status as `policy._series.SeriesStats` (never ledgered,
    never cross-boundary; the dev pass may freely add fields, never remove
    the three pinned here)."""

    thesis_id: str
    account_ref: str | None
    strategy_tag: str | None


@dataclass(frozen=True)
class GradeRecord:
    """`latest_grades()`'s per-row return shape."""

    thesis_id: str
    account_ref: str | None
    outcome: str
    pnl_usd: Decimal | None
    graded_ts: datetime


class LedgerModels:
    """`ledger.models` accessor bundle (DESIGN §4.2). Bound to one `Ledger`
    instance's own connection at construction — every method below reads
    THAT ledger only, never `default_ledger()` freshly."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def active_theses(self) -> list[ActiveThesis]:
        # `theses` is the projection table (`_projections.py`) — post-`rebuild()`
        # read surface, never raw events (module docstring's own pin).
        con = self._ledger._con
        rows = con.execute(
            "SELECT thesis_id, account_ref, strategy_tag FROM theses WHERE state = 'active'"
        ).fetchall()
        return [
            ActiveThesis(thesis_id=row[0], account_ref=row[1], strategy_tag=row[2])
            for row in rows
        ]

    def account_refs(self) -> list[str]:
        con = self._ledger._con
        from_accounts = {
            row[0] for row in con.execute("SELECT account_ref FROM accounts").fetchall()
        }
        from_theses = {
            row[0]
            for row in con.execute(
                "SELECT DISTINCT account_ref FROM theses WHERE account_ref IS NOT NULL"
            ).fetchall()
        }
        refs = {ref for ref in (from_accounts | from_theses) if ref}
        return sorted(refs)

    def latest_grades(self, n: int = 10) -> list[GradeRecord]:
        con = self._ledger._con
        rows = con.execute(
            "SELECT thesis_id, account_ref, graded_outcome, graded_ts FROM theses"
            " WHERE graded_ts IS NOT NULL"
            " ORDER BY graded_ts DESC, thesis_id ASC LIMIT ?",
            (n,),
        ).fetchall()

        # `pnl_usd` isn't carried by the `theses` projection (module docstring) —
        # read it off the owning `ThesisGraded` event. The FIRST ThesisGraded
        # event for a given thesis_id is the one the (guarded) projection
        # actually applied (a well-formed log has exactly one anyway), so
        # `setdefault` — never overwritten by a later duplicate — keeps the
        # derivation and the projection in agreement.
        pnl_by_thesis: dict[str, Decimal | None] = {}
        for event in self._ledger.query(EventFilter(types=["ThesisGraded"])):
            thesis_id = event.payload.get("thesis_id")
            if thesis_id is None or thesis_id in pnl_by_thesis:
                continue
            pnl = event.payload.get("pnl_usd")
            pnl_by_thesis[thesis_id] = Decimal(str(pnl)) if pnl is not None else None

        return [
            GradeRecord(
                thesis_id=row[0],
                account_ref=row[1],
                outcome=row[2],
                pnl_usd=pnl_by_thesis.get(row[0]),
                graded_ts=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]


__all__ = ["ActiveThesis", "GradeRecord", "LedgerModels"]
