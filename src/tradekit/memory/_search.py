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

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tradekit.contracts import Event
    from tradekit.ledger import Ledger

_FRONT_MATTER_DELIM = "---\n"


def _parse_query(query: str) -> tuple[list[str], bool]:
    """`(terms, is_phrase)` — a whole query wrapped in double-quotes is one
    literal adjacent phrase (`terms == [phrase]`); otherwise every
    whitespace-separated term is implicit-AND'd (module docstring PIN)."""
    stripped = query.strip()
    if len(stripped) >= 2 and stripped.startswith('"') and stripped.endswith('"'):
        return [stripped[1:-1]], True
    return stripped.split(), False


def _matching_events(ledger: Ledger, terms: list[str], is_phrase: bool) -> list[Event]:
    """`ledger.search()` already does exactly what a SINGLE phrase needs (it
    quotes its whole argument as one FTS5 phrase — `Ledger.search`'s own
    docstring). Implicit-AND over MULTIPLE terms is built here by searching
    each term independently (each single-word search is trivially its own
    one-word "phrase") and intersecting the resulting event_id sets — this
    reuses the existing verb rather than reaching into `Ledger`'s private
    FTS5 connection for a bespoke unquoted MATCH query."""
    if not terms:
        return []
    if is_phrase:
        return ledger.search(terms[0], k=10_000)

    per_term = [
        {event.event_id: event for event in ledger.search(term, k=10_000)} for term in terms
    ]
    common_ids = set(per_term[0])
    for matches in per_term[1:]:
        common_ids &= set(matches)
    return [per_term[0][event_id] for event_id in common_ids]


def _parse_front_matter(text: str) -> dict[str, Any]:
    """Reads exactly what `memory._wiki.add_note` writes — `status`/
    `salience`/`provenance` colon-delimited lines between the leading `---`
    fence pair (no PyYAML, same "hand-rolled, only house-code consumer" pin
    as the writer's own docstring)."""
    front: dict[str, Any] = {}
    if not text.startswith(_FRONT_MATTER_DELIM):
        return front
    _, _, rest = text.partition(_FRONT_MATTER_DELIM)
    fm_text, _, _ = rest.partition(_FRONT_MATTER_DELIM)
    for line in fm_text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        front[key.strip()] = value.strip()
    if "salience" in front:
        try:
            front["salience"] = int(front["salience"])
        except ValueError:
            pass
    return front


def _matches(haystack: str, terms: list[str], is_phrase: bool) -> bool:
    lowered = haystack.lower()
    if is_phrase:
        return terms[0].lower() in lowered
    return all(term.lower() in lowered for term in terms)


def _wiki_results(wiki_dir: str, terms: list[str], is_phrase: bool) -> list[dict[str, Any]]:
    directory = Path(wiki_dir)
    if not directory.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not _matches(text, terms, is_phrase):
            continue
        front = _parse_front_matter(text)
        results.append({"source": "wiki", "path": str(path), "text": text, **front})
    results.sort(key=lambda row: row.get("salience", 0), reverse=True)
    return results


def search(ledger: Ledger, wiki_dir: str, query: str, k: int = 10) -> list[dict[str, Any]]:
    """`ledger.search()` (events) + wiki front-matter files under
    `wiki_dir`, implicit-AND / quoted-phrase semantics (module docstring),
    capped at `k` total results.

    Cross-source merge order (dev-pass choice, module docstring flags this as
    undocumented by either canonical doc): ledger events first, ranked
    `ts_utc` desc (recency), then wiki notes, ranked by their own `salience`
    front-matter field desc — events are the higher-velocity, "what just
    happened" source; wiki notes are the slower-moving distilled-knowledge
    layer, so a fresher event outranks an older note by default."""
    terms, is_phrase = _parse_query(query)

    events = sorted(
        _matching_events(ledger, terms, is_phrase), key=lambda event: event.ts_utc, reverse=True
    )
    event_results = [
        {
            "source": "ledger",
            "event_id": event.event_id,
            "type": event.type,
            "ts_utc": event.ts_utc.isoformat(),
            **event.payload,
        }
        for event in events
    ]

    wiki_results = _wiki_results(wiki_dir, terms, is_phrase)

    combined = event_results + wiki_results
    return combined[:k]


__all__ = ["search"]
