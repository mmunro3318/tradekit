"""Element-map data format + grade rule (SPEC-bridge-read Interface pins,
T2). ``load_element_map``/``grade_exposure`` are RED stubs — real bodies
land with T6 (probe script) and T4 (read verbs) respectively; the pinned
logical-selector constants and the ``ElementMap``/``Selector`` shapes are
real now (they are the data-format contract the loader must satisfy).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tradekit.bridge._errors import AmbiguousElement, ElementMapMiss
from tradekit.bridge._session import UiaNode

# Pinned logical selector names (SPEC-bridge-read: "Logical selector names
# are pinned constants in _elementmap.py").
ACCOUNT_NAME = "ACCOUNT_NAME"
BALANCE = "BALANCE"
MDL_REMAINING = "MDL_REMAINING"
MDD_REMAINING = "MDD_REMAINING"
TARGET_REMAINING = "TARGET_REMAINING"
INSTRUMENT = "INSTRUMENT"
POSITIONS_TABLE = "POSITIONS_TABLE"
TICKET_SIDE = "TICKET_SIDE"
TICKET_ORDER_TYPE = "TICKET_ORDER_TYPE"
TICKET_QTY = "TICKET_QTY"
TICKET_LIMIT_PRICE = "TICKET_LIMIT_PRICE"
TICKET_STOP_PRICE = "TICKET_STOP_PRICE"


@dataclass(frozen=True)
class Selector:
    by: Literal["automation_id", "name", "path"]
    value: str | list[str]


@dataclass(frozen=True)
class ElementMap:
    app_version: str
    captured_utc: str
    selectors: dict[str, Selector]


def load_element_map(path: str) -> ElementMap:
    """Load + parse an element-map JSON artifact (format pinned in
    SPEC-bridge-read)."""
    text = Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    selectors = {
        name: Selector(by=sel["by"], value=sel["value"])
        for name, sel in payload["selectors"].items()
    }
    return ElementMap(
        app_version=payload["app_version"],
        captured_utc=payload["captured_utc"],
        selectors=selectors,
    )


def _walk(n: UiaNode) -> list[UiaNode]:
    out = [n]
    for child in n.children():
        out.extend(_walk(child))
    return out


def resolve_selector(
    root: UiaNode, name: str, selector: Selector
) -> tuple[Literal["automation_id", "name", "path"], UiaNode]:
    """THE single element-resolution cascade (fix round F1/F2/F6): the
    only place a logical selector is turned into a live `UiaNode`. Both
    `grade_exposure` and `_read.py`'s read verbs consume this — no
    duplicated resolver logic.

    Cascade starts at the selector's own stored `by` tier (F6, CTO
    adjudication): a `by:"name"` selector never consults the
    automation_id tier; tiers below its own tier are fallback only.
    `by:"automation_id"` falls through to `name` on a miss (both match
    against the same string `value`); `by:"path"` is terminal (list
    value, ordered unique-name descent per ASSUMPTIONS 155b) with no
    fallback.

    AMBIGUITY TERMINATES THE CASCADE (F1/F2): >1 match at a tier is a
    failure of the whole resolution, not a fall-through to the next
    tier — raises `AmbiguousElement` immediately.

    Raises `ElementMapMiss` / `AmbiguousElement` on failure; never
    returns a partial/defaulted result.
    """
    if selector.by == "path":
        assert isinstance(selector.value, list)
        current = root
        for step in selector.value:
            # Whole-subtree descent (not just direct children) is a
            # conservative quirk kept as-is per fix-round F9; logged
            # for T7 re-freeze against the real tree.
            candidates = [n for n in _walk(current) if n.name == step]
            if len(candidates) == 0:
                raise ElementMapMiss(name, f"no node named {step!r} in subtree")
            if len(candidates) > 1:
                raise AmbiguousElement(name, len(candidates))
            current = candidates[0]
        return "path", current

    value = selector.value
    assert isinstance(value, str)
    all_nodes = _walk(root)

    if selector.by == "automation_id":
        by_aid = [n for n in all_nodes if n.automation_id == value]
        if len(by_aid) == 1:
            return "automation_id", by_aid[0]
        if len(by_aid) > 1:
            raise AmbiguousElement(name, len(by_aid))
        # 0 matches at automation_id: fall through to name tier.

    by_name = [n for n in all_nodes if n.name == value]
    if len(by_name) == 1:
        return "name", by_name[0]
    if len(by_name) > 1:
        raise AmbiguousElement(name, len(by_name))

    nearby_roles = sorted({n.role for n in all_nodes})
    hint = f"no node with automation_id/name {value!r}; nearby roles: {nearby_roles}"
    raise ElementMapMiss(name, hint)


def grade_exposure(
    tree: UiaNode, element_map: ElementMap
) -> Literal["A", "B", "C"]:
    """Apply the pinned grade rule to a resolved tree against an element
    map, re-resolving every logical selector LIVE via `resolve_selector`
    (ASSUMPTIONS 154a; fix round F1/F2/F6). A miss or an ambiguous match
    both count as unresolvable for grading purposes (grading counts
    resolvability, not ambiguity — ASSUMPTIONS 154a).

    Grade rule (pinned, SPEC-bridge-read):
    A = every selectors logical target resolvable by automation_id;
    B = all resolvable but >=1 only by name/path;
    C = >=1 target unresolvable (canvas/opaque).
    """
    tiers: list[Literal["automation_id", "name", "path"] | None] = []
    for name, selector in element_map.selectors.items():
        try:
            tier, _node = resolve_selector(tree, name, selector)
        except (ElementMapMiss, AmbiguousElement):
            tier = None
        tiers.append(tier)
    if any(tier is None for tier in tiers):
        return "C"
    if all(tier == "automation_id" for tier in tiers):
        return "A"
    return "B"


__all__ = [
    "ACCOUNT_NAME",
    "BALANCE",
    "INSTRUMENT",
    "MDD_REMAINING",
    "MDL_REMAINING",
    "POSITIONS_TABLE",
    "TARGET_REMAINING",
    "TICKET_LIMIT_PRICE",
    "TICKET_ORDER_TYPE",
    "TICKET_QTY",
    "TICKET_SIDE",
    "TICKET_STOP_PRICE",
    "ElementMap",
    "Selector",
    "grade_exposure",
    "load_element_map",
    "resolve_selector",
]
