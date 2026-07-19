"""Read-only Kraken Desktop UIA tree probe (SPEC-bridge-read T6/T7).

Connects to Kraken Desktop via the real pywinauto-backed session, dumps the
full accessibility tree (role/name/automation_id/value per node,
recursive), grades its exposure (A/B/C, design U4) against an element map,
and writes a JSON artifact `{app_version, captured_utc, exposure_grade,
tree}` to `docs/research/uia-probe-kraken-<date>.json` (or `--out`).

Nothing here clicks, types, or submits — read-only throughout.

Run: uv run python scripts/probe_uia_kraken.py --element-map PATH [--out PATH]
Requires the optional `bridge` dependency group (`uv sync --group bridge`)
and Kraken Desktop running (Windows only).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tradekit.bridge._elementmap import ElementMap, grade_exposure
from tradekit.bridge._session import UiaNode


def dump_tree(node: UiaNode) -> dict[str, Any]:
    """Serialize a `UiaNode` (and its subtree) into the artifact's `tree`
    shape — role/name/automation_id/value per node, recursive."""
    return {
        "node_id": node.node_id,
        "role": node.role,
        "name": node.name,
        "automation_id": node.automation_id,
        "value": node.value,
        "children": [dump_tree(child) for child in node.children()],
    }


def build_artifact(
    tree: UiaNode,
    element_map: ElementMap,
    *,
    app_version: str,
    captured_utc: str,
) -> dict[str, Any]:
    """Assemble the probe artifact: `{app_version, captured_utc,
    exposure_grade, tree}` — `exposure_grade` via the pinned grade rule
    (`_elementmap.grade_exposure`, re-resolved live against `tree`)."""
    return {
        "app_version": app_version,
        "captured_utc": captured_utc,
        "exposure_grade": grade_exposure(tree, element_map),
        "tree": dump_tree(tree),
    }


def load_artifact(path: str) -> dict[str, Any]:
    """Load a previously written artifact JSON (AC-11 round-trip)."""
    text = Path(path).read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(text)
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--element-map", required=False, help="Element map JSON to grade against."
    )
    parser.add_argument("--out", default=None, help="Output artifact JSON path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Real attach (session.root() -> dump -> grade -> write)
    lands with T7 against a live Kraken Desktop; this batch pins the pure
    helpers above (importable without a live app) and the argument surface
    (`--help` must work standalone on any machine, per T6's done criterion)."""
    _parse_args(argv)
    raise NotImplementedError("probe_uia_kraken.main: real attach lands with T7")


if __name__ == "__main__":
    raise SystemExit(main())
