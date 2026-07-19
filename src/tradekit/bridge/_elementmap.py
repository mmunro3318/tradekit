"""Element-map data format + grade rule (SPEC-bridge-read Interface pins,
T2). ``load_element_map``/``grade_exposure`` are RED stubs — real bodies
land with T6 (probe script) and T4 (read verbs) respectively; the pinned
logical-selector constants and the ``ElementMap``/``Selector`` shapes are
real now (they are the data-format contract the loader must satisfy).
"""

from __future__ import annotations

from dataclasses import dataclass
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
    SPEC-bridge-read). RED stub — real body lands in T6."""
    raise NotImplementedError


def grade_exposure(
    tree: UiaNode, element_map: ElementMap
) -> Literal["A", "B", "C"]:
    """Apply the pinned grade rule to a resolved tree against an element
    map. RED stub — real body lands in T4/T6.

    Grade rule (pinned, SPEC-bridge-read):
    A = every selectors logical target resolvable by automation_id;
    B = all resolvable but >=1 only by name/path;
    C = >=1 target unresolvable (canvas/opaque).
    """
    raise NotImplementedError


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
