"""`rules/RULES.md` generation (DESIGN §7.1: "generated from this registry
... so the human-readable catalog can never drift from the code"). STUB
this batch (CTO's batch-C red/green split call: "RULES.md generation ...
stay stubs -> red") — `_rules.py`'s registry is real and already carries
every rule's `id`/`why`, so the eventual implementation is a pure
string-render over `_rules.RULES`; it is not implemented THIS batch only
because `tk policy status --rules` (its CLI trigger) is itself gated behind
`policy.status()`, which is a stub.
"""

from __future__ import annotations

from pathlib import Path

# repo root, mirroring `_dials._REPO_ROOT_CONFIG`'s parents-count convention.
RULES_MD_PATH = Path(__file__).resolve().parents[3] / "rules" / "RULES.md"


def render_rules_md() -> str:
    """Render `_rules.RULES` into the Markdown catalog (ID / gate / dial /
    WHY, one row per rule, IDs in registry order). Pure — no filesystem
    access; `write_rules_md` is the I/O-performing caller."""
    raise NotImplementedError(
        "P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3; renders "
        "_rules.RULES into the rules/RULES.md table, generated-never-hand-edited"
    )


def write_rules_md() -> Path:
    """Write `render_rules_md()`'s output to `rules/RULES.md` (committed,
    generated, never hand-edited — DESIGN §7.1). Returns the path written."""
    raise NotImplementedError(
        "P2 batch D — docs/handoff/SPRINT-P2-thesis-policy.md story 3; writes "
        "render_rules_md()'s output to rules/RULES.md"
    )


__all__ = ["RULES_MD_PATH", "render_rules_md", "write_rules_md"]
