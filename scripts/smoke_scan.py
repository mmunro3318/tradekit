"""scripts/smoke_scan.py — SPRINT-P1C Definition-of-done smoke script.

NOT a test (no pytest here; hits the real, live Kraken API and writes real
rows into data/cache.db). Mike (or any dev) runs this once by hand to eyeball
that `scan_markets` returns real setups from live data:

    uv run python scripts/smoke_scan.py

What it does: one daily-timeframe scan over three of Mike's universe pairs
(ETH/SOL/LINK vs USD) with a deliberately loose filter (rsi_max=70) so at
least some symbols usually match, `regime_gate=False` to keep the run fast
and to avoid fitting/persisting an HMM artifact from a smoke script (regime
has its own deterministic test coverage; data/models/ stays untouched here).

Reading the output: a "match" is NOT a trade signal — it means the symbol's
last closed daily bar passed the numeric filter. `signal_tags` names which
filter(s) it passed. Symbols in `warnings` were skipped (usually not enough
history for an indicator), never silently dropped.
"""

from __future__ import annotations

import json

from tradekit.mae import scan_markets

SYMBOLS = ["ETH/USD", "SOL/USD", "LINK/USD"]


def main() -> None:
    result = scan_markets(
        asset_class="crypto",
        timeframes=["1d"],
        filters={"rsi_max": 70},
        symbols=SYMBOLS,
        regime_gate=False,
    )

    print(f"scan_ts: {result.get('scan_ts')}")
    print(f"symbols scanned: {', '.join(SYMBOLS)}  (filter: RSI(14) <= 70, daily)")
    print(f"matches: {len(result['matches'])}")
    for m in result["matches"]:
        print(
            f"  {m['symbol']:>9} {m['timeframe']}: close={m['price']} "
            f"RSI={m['rsi']:.2f} tags={m['signal_tags']}"
        )

    if result.get("warnings"):
        print("\nwarnings (skipped symbols):")
        for w in result["warnings"]:
            print(f"  {w}")

    print("\nfull payload (canonical §3 shape):")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
