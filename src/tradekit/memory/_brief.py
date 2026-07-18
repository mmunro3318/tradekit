"""tradekit.memory._brief — `tk brief`'s token-budgeted markdown renderer
(DESIGN §11; sprint-doc addendum: "tk brief token budget is a hard cap —
truncate by salience, never silently overflow"; SPRINT P3 batch E).

`estimate_tokens` is REAL this batch (pure arithmetic, the addendum's own
PINNED heuristic — same "cheap, pure" status as `policy._series.
series_index`, ASSUMPTIONS round-21). `render` — section assembly plus the
truncation algorithm — is an unconditional `NotImplementedError` stub;
`tests/unit/memory/test_brief.py` pins the REAL target behavior.

DESIGN PINS (CTO, binding on the dev pass):

- Sections, in this fixed order: promotion state + attempt stats (D7),
  open positions, active theses, last 10 grades, halts, top-salience
  lessons. Every section is rendered from a read model ONLY
  (`policy.promotion_status`, `ledger.models.active_theses`/
  `latest_grades`, `policy.status`'s `halted`/`halt_reason`,
  `LessonRecorded` events ranked by salience desc) — never fresh
  computation.

- HARD CAP: `estimate_tokens(rendered_text) <= dials.brief_max_tokens`
  ALWAYS holds on return — never overflow, even by one section. When the
  full render exceeds the cap, drop or shrink WHOLE SECTIONS,
  LOWEST-SALIENCE-FIRST (a section's own "salience" for this ordering:
  lessons carry an explicit int; every other section's salience is fixed
  by DESIGN §11's own ordering — "top-salience lessons" is listed LAST,
  so it is the FIRST thing trimmed, then (if still over cap) sections
  trim from the bottom of the fixed list upward) — NEVER mid-sentence
  garble (a trimmed section is either fully present or fully replaced by
  the `TRUNCATION_MARKER` line, never cut mid-word). A truncated brief
  ends with `TRUNCATION_MARKER` as its own final line, once, naming
  nothing was silently dropped.

- `token≈len(text)/4` — PINNED heuristic (sprint-doc addendum), no
  tokenizer dependency. `estimate_tokens` below ceiling-divides so a
  non-empty string never estimates to zero tokens (a truncation decision
  must never treat real content as free).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradekit.ledger import Ledger
    from tradekit.policy._dials import PolicyDials

TRUNCATION_MARKER = "…[truncated]"


def estimate_tokens(text: str) -> int:
    """`token ≈ len(text) / 4`, ceiling division (a non-empty string never
    estimates to zero tokens) — pure, no I/O."""
    if not text:
        return 0
    return (len(text) + 3) // 4


def render(ledger: Ledger, dials: PolicyDials, now: datetime) -> str:
    """Assemble the fixed six sections (module docstring), then truncate
    lowest-salience-section-first until `estimate_tokens(result) <=
    dials.brief_max_tokens` — see module docstring for the full pin."""
    raise NotImplementedError("SPRINT P3 batch E — memory._brief.render")


__all__ = ["TRUNCATION_MARKER", "estimate_tokens", "render"]
