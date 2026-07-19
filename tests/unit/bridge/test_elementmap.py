"""AC-11: element-map grade rule + artifact round-trip (SPEC-bridge-read,
T2). BEHAVIOR + GOLDEN per the test-plan sketch — one synthetic fixture
tree per grade (A/B/C), built directly from the pinned grade rule text:

    A = every selectors logical target resolvable by automation_id
    B = all resolvable but >=1 only by name/path
    C = >=1 target unresolvable (canvas/opaque)

ASSUMPTION (flag for tests/ASSUMPTIONS.md ratification — see report):
the pin does not specify grade_exposure's resolution algorithm (how a
selector's `by`/`value` is matched against a live tree — cascading
automation_id -> name -> path, or strict use of the map's stored `by`
field only). These fixtures assume cascading resolution against the
live tree (grade reflects what's ACTUALLY resolvable now, not merely
what the map recorded from a prior probe run) since grade_exposure's
signature takes both `tree` and `element_map`. Flagged as ASSUMPTIONS
candidate #1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tradekit.bridge._elementmap import (
    ElementMap,
    Selector,
    grade_exposure,
    load_element_map,
)


@dataclass
class FakeUiaNode:
    node_id: str
    role: str = "Custom"
    name: str = ""
    automation_id: str = ""
    value: str = ""
    _children: list[FakeUiaNode] = field(default_factory=list)

    def children(self) -> list[FakeUiaNode]:
        return self._children


def _tree(*nodes: FakeUiaNode) -> FakeUiaNode:
    return FakeUiaNode(node_id="root", role="Window", _children=list(nodes))


class TestGradeRuleA:
    def test_all_automation_id_resolvable_grades_a(self) -> None:
        """GOLDEN: two selectors, both matched by automation_id on the
        synthetic tree -> grade A per the pinned rule's first clause."""
        tree = _tree(
            FakeUiaNode(node_id="n1", automation_id="balanceValue"),
            FakeUiaNode(node_id="n2", automation_id="accountNameValue"),
        )
        element_map = ElementMap(
            app_version="1.0.0",
            captured_utc="2026-07-19T00:00:00Z",
            selectors={
                "BALANCE": Selector(by="automation_id", value="balanceValue"),
                "ACCOUNT_NAME": Selector(
                    by="automation_id", value="accountNameValue"
                ),
            },
        )
        assert grade_exposure(tree, element_map) == "A"


class TestGradeRuleB:
    def test_one_name_only_resolution_grades_b(self) -> None:
        """GOLDEN: BALANCE resolvable by automation_id, ACCOUNT_NAME only
        by name (no automation_id on that node) -> grade B (all resolvable,
        >=1 by name/path)."""
        tree = _tree(
            FakeUiaNode(node_id="n1", automation_id="balanceValue"),
            FakeUiaNode(node_id="n2", automation_id="", name="Account Name"),
        )
        element_map = ElementMap(
            app_version="1.0.0",
            captured_utc="2026-07-19T00:00:00Z",
            selectors={
                "BALANCE": Selector(by="automation_id", value="balanceValue"),
                "ACCOUNT_NAME": Selector(by="name", value="Account Name"),
            },
        )
        assert grade_exposure(tree, element_map) == "B"


class TestGradeRuleC:
    def test_unresolvable_target_grades_c(self) -> None:
        """GOLDEN: ACCOUNT_NAME's selector value matches nothing in the
        tree (canvas/opaque case) -> grade C, STOP per design U4."""
        tree = _tree(
            FakeUiaNode(node_id="n1", automation_id="balanceValue"),
        )
        element_map = ElementMap(
            app_version="1.0.0",
            captured_utc="2026-07-19T00:00:00Z",
            selectors={
                "BALANCE": Selector(by="automation_id", value="balanceValue"),
                "ACCOUNT_NAME": Selector(by="name", value="Nonexistent Label"),
            },
        )
        assert grade_exposure(tree, element_map) == "C"


class TestElementMapRoundTrip:
    """AC-11: the artifact JSON round-trips (load -> same tree)."""

    def test_load_element_map_round_trips_via_json(self, tmp_path: Path) -> None:
        payload = {
            "app_version": "1.0.0",
            "captured_utc": "2026-07-19T00:00:00Z",
            "selectors": {
                "BALANCE": {"by": "automation_id", "value": "balanceValue"},
                "POSITIONS_TABLE": {
                    "by": "path",
                    "value": ["Window", "Grid", "Table"],
                },
            },
        }
        artifact = tmp_path / "kraken-1.0.0.json"
        artifact.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_element_map(str(artifact))

        assert loaded.app_version == "1.0.0"
        assert loaded.selectors["BALANCE"].by == "automation_id"
        assert loaded.selectors["BALANCE"].value == "balanceValue"
        assert loaded.selectors["POSITIONS_TABLE"].value == [
            "Window",
            "Grid",
            "Table",
        ]

    def test_load_element_map_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(FileNotFoundError):
            load_element_map(str(missing))
