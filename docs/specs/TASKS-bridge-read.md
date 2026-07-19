# TASKS-bridge-read (from SPEC-bridge-read.md)

### T1: bridge contracts payloads
satisfies: AC-1, AC-6, AC-7
files: src/tradekit/contracts/_bridge.py, src/tradekit/contracts/__init__.py, tests/unit/bridge/test_bridge_contracts.py
done: contract tests green via tk-gate (shapes/Decimal/frozen)

### T2: bridge skeleton — errors, session protocol, element map, grade rule, import guard
satisfies: AC-10, AC-11
files: src/tradekit/bridge/__init__.py, src/tradekit/bridge/_errors.py, src/tradekit/bridge/_session.py, src/tradekit/bridge/_elementmap.py, tests/unit/bridge/test_elementmap.py, tests/unit/bridge/test_import_guard.py
done: AC-10/AC-11 tests green via tk-gate

### T3: panel text parser
satisfies: AC-5
files: src/tradekit/bridge/_parse.py, tests/unit/bridge/test_parse.py
done: AC-5 golden table green via tk-gate (hand-derived)

### T4: read verbs over FakeUiaSession
satisfies: AC-1, AC-2, AC-3, AC-4, AC-6, AC-7, AC-8, AC-12
files: src/tradekit/bridge/_read.py, tests/unit/bridge/test_read_verbs.py, tests/unit/bridge/conftest.py
done: AC-1..8+12 tests green via tk-gate (synthetic fixture trees; AC-1 golden CTO-re-derived)

### T5: tk bridge snapshot CLI
satisfies: AC-9, AC-12
files: src/tradekit/cli/main.py, tests/unit/cli/test_cli_bridge.py
done: AC-9 exit-code/stdout-purity tests green via tk-gate

### T6: real pywinauto session + probe script + dependency group
satisfies: AC-10, AC-11
files: src/tradekit/bridge/_pywinauto.py, scripts/probe_uia_kraken.py, pyproject.toml
done: artifact round-trip + guard tests green via tk-gate; probe runs to --help on this machine (real attach needs T7)

### T7: run probe against live Kraken Desktop, commit artifact, re-freeze fixtures
satisfies: AC-1, AC-11 (real-data leg); resolves S1/S3, design U4
files: docs/research/uia-probe-kraken-2026-07.json, src/tradekit/bridge/elementmaps/, tests/unit/bridge/conftest.py
done: artifact committed with grade; fixtures swapped to real tree through the golden-freeze gate; MIKE-GATED (Kraken Desktop must be open; CTO observes read-only); includes real drift detection replacing _check_bridge_map_drift stub (AC-12)
