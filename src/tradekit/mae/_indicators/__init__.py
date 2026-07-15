"""tradekit.mae._indicators — pure indicator functions over bar-derived
numeric series (SPRINT P1B; docs/handoff/SPRINT-P1B-indicators.md).

No I/O, no state, no MAE-verb changes this sprint. Private: nothing outside
tradekit.mae imports these submodules directly except tests, which have a
documented, temporary exception (see tests/ASSUMPTIONS.md) until a public
verb wires this package into scan_markets (P1C+).

No re-exports here on purpose — each submodule (volatility, momentum,
trend; volume and structure land in a later batch) is imported directly by
name; this sprint does not define a public surface for _indicators yet.
"""

from __future__ import annotations
