"""tradekit.mae._data — market data providers, cache, and rate limiting
(SPRINT-P1A). Private: nothing outside tradekit.mae imports these modules
directly except tests, which have a documented, temporary exception (see
tests/ASSUMPTIONS.md) until a public verb wires this package in (P1C+).

No re-exports here on purpose — each submodule (port, cache, kraken,
ratelimit, errors) is imported directly by name; this sprint does not define
a public surface for _data yet.
"""

from __future__ import annotations
