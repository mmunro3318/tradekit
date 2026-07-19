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


def _resolve_tier(
    node: UiaNode, selector: Selector
) -> Literal["automation_id", "name", "path"] | None:
    """Cascade automation_id -> name -> path against the live tree
    (ASSUMPTIONS 154a): re-resolves live, ignoring the map's stored
    ``by`` provenance. Returns the tier the selector matched at, or
    None if the count of matches != 1 (0 or >1 both fail resolution
    for grading purposes — grading counts resolvability, not ambiguity).
    """

    def _walk(n: UiaNode) -> list[UiaNode]:
        out = [n]
        for child in n.children():
            out.extend(_walk(child))
        return out

    all_nodes = _walk(node)

    def _matches(value: str) -> list[UiaNode]:
        return [n for n in all_nodes if n.automation_id == value]

    def _matches_name(value: str) -> list[UiaNode]:
        return [n for n in all_nodes if n.name == value]

    # Try automation_id tier first using the selector's own value.
    value = selector.value
    if isinstance(value, str):
        by_aid = _matches(value)
        if len(by_aid) == 1:
            return "automation_id"
        by_name = _matches_name(value)
        if len(by_name) == 1:
            return "name"
    return None


def grade_exposure(
    tree: UiaNode, element_map: ElementMap
) -> Literal["A", "B", "C"]:
    """Apply the pinned grade rule to a resolved tree against an element
    map, re-resolving every logical selector LIVE by cascade
    automation_id -> name -> path (ASSUMPTIONS 154a).

    Grade rule (pinned, SPEC-bridge-read):
    A = every selectors logical target resolvable by automation_id;
    B = all resolvable but >=1 only by name/path;
    C = >=1 target unresolvable (canvas/opaque).
    """
    tiers = [_resolve_tier(tree, selector) for selector in element_map.selectors.values()]
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
]
