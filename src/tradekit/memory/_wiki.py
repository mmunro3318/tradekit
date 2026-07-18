"""tradekit.memory._wiki — `tk wiki add` (DESIGN §11: "distilled knowledge
in docs/wiki/ with front-matter (status: candidate|simulating|rejected|
adopted, salience, provenance)"; SPRINT P3 batch E).

REAL this batch — declarative front-matter file writing, same "cheap"
status as `broker.create_paper_account`/`policy._rules_md.write_rules_md`
(no domain logic beyond formatting + a filesystem write; the substantial
memory-module deliverable is `_brief.render`/`_search.search`, both
stubbed). Path seam: `wiki_dir` is always an explicit argument (cross-
cutting pin, "All new file-writers get path seams") — callers resolve it
from `PolicyDials.load().wiki_dir`, never a module-level constant.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATUSES = ("candidate", "simulating", "rejected", "adopted")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class InvalidWikiStatus(ValueError):
    """`status` is not one of the four DESIGN §11 values."""


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug or "note"


def add_note(
    wiki_dir: str,
    title: str,
    body: str,
    *,
    status: str = "candidate",
    salience: int = 1,
    provenance: str = "",
) -> Path:
    """Write `{wiki_dir}/{slug(title)}.md` with YAML-ish front-matter
    (`status`/`salience`/`provenance`) + `title` + `body`; returns the
    written path. Overwrites a same-slug file (idempotent re-add, same
    convention as `ledger._projections`'s `INSERT OR REPLACE` rows) —
    front-matter is deliberately hand-rolled (no PyYAML dependency this
    sprint) since `memory._search`'s own front-matter READER is the ONLY
    consumer and both sides are house code."""
    if status not in _STATUSES:
        raise InvalidWikiStatus(
            f"status={status!r} must be one of {_STATUSES!r} (DESIGN §11)"
        )
    if not (1 <= salience <= 5):
        raise ValueError(f"salience={salience!r} must be in 1..5")

    directory = Path(wiki_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slugify(title)}.md"

    front_matter = (
        "---\n"
        f"status: {status}\n"
        f"salience: {salience}\n"
        f"provenance: {provenance}\n"
        "---\n"
    )
    path.write_text(f"{front_matter}# {title}\n\n{body}\n", encoding="utf-8")
    return path


__all__ = ["InvalidWikiStatus", "add_note"]
