"""Shared bridge test fixtures (SPEC-bridge-read T4). `FakeUiaSession` is
the ONLY sanctioned fake for the `UiaSession`/`UiaNode` seam (design §7's
determinism boundary) — it implements the pinned Protocols over a
hand-authored nested-tree fixture and records every method invocation so
AC-8 (read-only guarantee) can be asserted directly against the call log.
Synthetic trees only; real probe trees swap in at T7 via golden-freeze.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tradekit.bridge._errors import AppNotFound
from tradekit.bridge._session import UiaNode


@dataclass
class FakeUiaNode:
    node_id: str
    role: str = "Custom"
    name: str = ""
    automation_id: str = ""
    value: str = ""
    _children: list[FakeUiaNode] = field(default_factory=list)
    _log: list[str] | None = None

    def children(self) -> list[UiaNode]:
        if self._log is not None:
            self._log.append(f"children:{self.node_id}")
        return list(self._children)


def node(
    node_id: str,
    *,
    role: str = "Custom",
    name: str = "",
    automation_id: str = "",
    value: str = "",
    children: list[FakeUiaNode] | None = None,
) -> FakeUiaNode:
    """Hand-authored fixture-tree builder."""
    return FakeUiaNode(
        node_id=node_id,
        role=role,
        name=name,
        automation_id=automation_id,
        value=value,
        _children=children or [],
    )


def _stamp_log(n: FakeUiaNode, log: list[str]) -> None:
    n._log = log
    for child in n._children:
        _stamp_log(child, log)


class FakeUiaSession:
    """`UiaSession` over a `FakeUiaNode` tree. `.calls` records every
    method invocation (`root`, `children:<node_id>`) — AC-8 asserts this
    list contains ONLY these two read-shaped entry kinds, never an
    invoke/click/set/keyboard verb. Those verbs don't exist on the fake
    at all (the Protocol has none); the assertion guards against a future
    accidental addition growing the seam past read-only.
    """

    def __init__(self, root_node: FakeUiaNode | None, *, app_present: bool = True) -> None:
        self._root = root_node
        self._app_present = app_present
        self.calls: list[str] = []
        if root_node is not None:
            _stamp_log(root_node, self.calls)

    def root(self) -> UiaNode:
        self.calls.append("root")
        if not self._app_present or self._root is None:
            raise AppNotFound("Kraken Desktop not running")
        return self._root

    WRITE_VERBS = frozenset({"invoke", "click", "set", "set_value", "send_keys", "type_keys"})
