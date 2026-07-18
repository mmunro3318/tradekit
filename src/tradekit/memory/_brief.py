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
from typing import TYPE_CHECKING, Any

from tradekit.contracts import EventFilter

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


def _section(title: str, lines: list[str]) -> str:
    body = "\n".join(lines) if lines else "(none)"
    return f"## {title}\n{body}"


def _lessons_section(entries: list[dict[str, Any]]) -> str:
    return _section(
        "Top-Salience Lessons",
        [f"- (salience {entry['salience']}) {entry['note']}" for entry in entries],
    )


def _assemble(sections: list[str], *, truncated: bool) -> str:
    text = "\n\n".join(sections)
    if truncated:
        text += "\n" + TRUNCATION_MARKER
    return text


def render(ledger: Ledger, dials: PolicyDials, now: datetime) -> str:
    """Assemble the fixed six sections (module docstring), then truncate
    lowest-salience-section-first until `estimate_tokens(result) <=
    dials.brief_max_tokens` — see module docstring for the full pin.

    Every section is a read model ONLY (module docstring): `policy.
    promotion_status()` (already a "read-verb-that-writes", idempotent —
    calling it from here appends nothing new beyond what a normal read
    would), `ledger.models.active_theses()`/`latest_grades()` (against
    freshly-rebuilt projections — `rebuild()` is a pure function of the
    event log, not "fresh computation" of business logic), `policy.status()`'s
    `halted`/`halt_reason`, and `LessonRecorded` events ranked by salience
    desc. `now` is accepted for signature symmetry with the module's other
    pure helpers; the promotion/halt reads use their own established clock
    seams (`policy._context.clock`), never this parameter, since neither verb
    accepts an injected `now`."""
    # Local import: `memory` reaching into `policy` for its own read models
    # is a read-only data dependency (same class of call ASSUMPTIONS round-21
    # entry 136 ratifies for `policy._dials.PolicyDials` reuse) — deferred to
    # call time only to keep this module's own import graph easy to reason
    # about at package-init time.
    from tradekit import policy

    ledger.rebuild()

    promotion = policy.promotion_status()
    pol_status = policy.status()
    active = ledger.models.active_theses()
    grades = ledger.models.latest_grades(n=10)

    lessons: list[dict[str, Any]] = sorted(
        (
            {
                "salience": int(event.payload.get("salience", 0)),
                "note": str(event.payload.get("note", "")),
            }
            for event in ledger.query(EventFilter(types=["LessonRecorded"]))
        ),
        key=lambda entry: -entry["salience"],
    )

    promotion_section = _section(
        "Promotion",
        [
            f"tier: {promotion.get('tier')}",
            f"eligible: {promotion.get('t2_eligible', {}).get('eligible')}",
            f"live_sequence_remaining: {promotion.get('live_sequence_remaining')}",
        ],
    )
    positions_section = _section(
        "Open Positions", ["(no open-position read model wired yet — P3 scope gap)"]
    )
    active_section = _section(
        "Active Theses",
        [f"- {t.thesis_id} ({t.account_ref}, {t.strategy_tag})" for t in active],
    )
    grades_section = _section(
        "Last 10 Grades",
        [f"- {g.thesis_id}: {g.outcome} pnl={g.pnl_usd}" for g in grades],
    )
    halts_section = _section(
        "Halts",
        [
            f"halted: {pol_status['halted']}",
            f"halt_reason: {pol_status['halt_reason']}",
        ],
    )

    fixed_sections = [
        promotion_section,
        positions_section,
        active_section,
        grades_section,
        halts_section,
    ]

    full = _assemble([*fixed_sections, _lessons_section(lessons)], truncated=False)
    if estimate_tokens(full) <= dials.brief_max_tokens:
        return full

    # Over cap: drop lessons LOWEST-SALIENCE-FIRST, one at a time (a "section"
    # for this ordering purpose — module docstring), never mid-word. `lessons`
    # is sorted highest-salience-first, so popping the tail removes the
    # currently-lowest-salience surviving entry each iteration.
    kept_lessons = list(lessons)
    while kept_lessons:
        kept_lessons.pop()
        candidate = _assemble([*fixed_sections, _lessons_section(kept_lessons)], truncated=True)
        if estimate_tokens(candidate) <= dials.brief_max_tokens:
            return candidate

    # Lessons section fully exhausted and still over cap: drop WHOLE sections
    # from the bottom of the fixed list upward (module docstring) — Halts,
    # then Grades, then Active Theses, then Open Positions. Promotion (index 0)
    # is never dropped — it is the one section every brief must still name.
    trimmed = list(fixed_sections)
    candidate = _assemble(trimmed, truncated=True)
    if estimate_tokens(candidate) <= dials.brief_max_tokens:
        return candidate
    while len(trimmed) > 1:
        trimmed.pop()
        candidate = _assemble(trimmed, truncated=True)
        if estimate_tokens(candidate) <= dials.brief_max_tokens:
            return candidate
    return candidate


__all__ = ["TRUNCATION_MARKER", "estimate_tokens", "render"]
