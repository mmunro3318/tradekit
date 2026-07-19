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
from datetime import UTC, datetime
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
    args = _parse_args(argv)
    from tradekit.bridge._elementmap import grade_exposure, load_element_map
    from tradekit.bridge._session import real_session

    session = real_session()
    root = session.root()
    print("attached; dumping tree (Electron trees are large — patience)...")
    tree = dump_tree(root)

    grade = "ungraded"
    if args.element_map:
        element_map = load_element_map(args.element_map)
        grade = grade_exposure(root, element_map)

    out = args.out or (
        "docs/research/uia-probe-kraken-"
        + datetime.now(UTC).strftime("%Y-%m-%d")
        + ".json"
    )
    artifact = {
        "app_version": "unverified",
        "captured_utc": datetime.now(UTC).isoformat(),
        "exposure_grade": grade,
        "tree": tree,
    }
    Path(out).write_text(json.dumps(artifact, indent=1), encoding="utf-8")

    def _count(t: dict) -> int:
        return 1 + sum(_count(c) for c in t.get("children", []))

    print(f"nodes={_count(tree)} grade={grade} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
