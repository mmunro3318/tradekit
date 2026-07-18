"""tradekit.memory._search — `tk search "<query>"` (DESIGN §11: "FTS5 over
events + wiki notes, recency-and-salience ranked"; SPRINT P3 batch E).

Unconditional `NotImplementedError` stub this batch; `tests/unit/memory/
test_search.py` pins the REAL target behavior.

PIN (sprint-doc addendum: "decide multi-word semantics — phrase vs AND —
and PIN it in ASSUMPTIONS, it was left open in P0"; ASSUMPTIONS round-21,
binding on the dev pass):

- A query with NO double-quotes: every whitespace-separated term is
  IMPLICIT-AND'd (a hit must contain every term, in ANY order/position) —
  e.g. `promotion halt` matches a document containing both words anywhere,
  not the literal substring `"promotion halt"`.
- A query wrapped in double-quotes (`'"exact phrase"'`) is a literal PHRASE
  match — the quoted words must appear ADJACENT, in that exact order (SQLite
  FTS5's own phrase-query syntax, `ledger.search`'s existing convention of
  quoting user text as an FTS5 phrase — see `ledger/__init__.py::Ledger.
  search`'s own docstring — extends naturally to this case; the dev pass
  may pass the quoted term straight through to `ledger.search` when the
  WHOLE query is one quoted phrase).
- Sources: `ledger.search(text)` (events) UNION wiki front-matter files
  under `wiki_dir` (`docs/wiki/*.md`, front-matter fields `status`/
  `salience`/`provenance` per DESIGN §11) whose body/front-matter matches
  the same AND/phrase semantics. Ranked recency-and-salience (ledger events
  rank by `ts_utc` desc; wiki notes carry their own `salience` front-matter
  field) — the dev pass documents the exact interleaving rule it picks
  here, since neither canonical doc pins a cross-source merge order.
- `k` caps the TOTAL result count across both sources (not k-per-source).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tradekit.ledger import Ledger


def search(ledger: Ledger, wiki_dir: str, query: str, k: int = 10) -> list[dict[str, Any]]:
    """`ledger.search()` (events) + wiki front-matter files under
    `wiki_dir`, implicit-AND / quoted-phrase semantics (module docstring),
    capped at `k` total results."""
    raise NotImplementedError("SPRINT P3 batch E — memory._search.search")


__all__ = ["search"]
