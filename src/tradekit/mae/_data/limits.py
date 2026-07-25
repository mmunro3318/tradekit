"""Pinned scan-lookback ceilings per timeframe (T-MTF-1,
docs/design/MTF-SCAN.md lines 7-26).

Kraken OHLC retains only the most recent 720 candles per interval
(CTO-verified live 2026-07-19, ASSUMPTIONS 161) — `since` filters within
that window and pagination past it is impossible. Each entry below is a
pinned scan lookback with headroom under that 720-bar wall, derived as
`720 * hours_per_bar / 24` days:

    15m: 720 * 0.25 / 24 = 7.5 d retention -> pinned 6 d
    1h:  720 * 1    / 24 = 30  d retention -> pinned 25 d
    4h:  720 * 4    / 24 = 120 d retention -> pinned 90 d
    1d:  720 * 24   / 24 = 720 d retention -> pinned 365 d

Invariant: this is the ONLY place a scan lookback may be hardcoded —
the scanner and hud must consume this table, never restate the numbers.
"""

from __future__ import annotations

TIMEFRAME_MAX_LOOKBACK_DAYS: dict[str, int] = {
    "15m": 6,
    "1h": 25,
    "4h": 90,
    "1d": 365,
}
