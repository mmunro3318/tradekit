"""PAXG/gold daily-basis probe (2026-07-19). Findings + caveats:
docs/research/paxg-basis-probe-2026-07-19.md — READ IT before trusting
any number this prints; the naive backtest is artifact-dominated by
construction (timestamp skew, thin closes, futures roll).

Rerun: uv run python experiments/paxg-basis/probe_daily_basis.py
Network: Kraken public OHLC (keyless) + Yahoo chart API (keyless, GC=F).
"""

from __future__ import annotations

import json
import math
import statistics as st
import time
import urllib.request


def fetch_paxg_daily() -> dict[str, float]:
    url = "https://api.kraken.com/0/public/OHLC?pair=PAXGUSD&interval=1440"
    d = json.load(urllib.request.urlopen(url))
    key = next(k for k in d["result"] if k != "last")
    return {
        time.strftime("%Y-%m-%d", time.gmtime(r[0])): float(r[4])
        for r in d["result"][key]
    }


def fetch_gold_daily() -> dict[str, float]:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=2y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    d = json.load(urllib.request.urlopen(req))
    r = d["chart"]["result"][0]
    return {
        time.strftime("%Y-%m-%d", time.gmtime(t)): c
        for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"], strict=False)
        if c
    }


def main() -> None:
    paxg, gold = fetch_paxg_daily(), fetch_gold_daily()
    days = sorted(set(paxg) & set(gold))
    bs = [paxg[d] / gold[d] - 1.0 for d in days]
    print(f"overlap {len(days)} days  {days[0]} -> {days[-1]}")
    print(
        f"basis: mean {st.mean(bs)*100:.3f}%  sd {st.pstdev(bs)*100:.3f}%  "
        f"min {min(bs)*100:.3f}%  max {max(bs)*100:.3f}%"
    )

    window = 30
    zs: list[float] = []
    dev: list[float] = []
    for i in range(window, len(bs)):
        win = bs[i - window : i]
        sd = st.pstdev(win)
        if sd > 0:
            zs.append((bs[i] - st.mean(win)) / sd)
            dev.append(bs[i] - st.mean(win))

    x, y = dev[:-1], dev[1:]
    mx, my = st.mean(x), st.mean(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    beta = cov / sum((a - mx) ** 2 for a in x)
    half_life = math.log(0.5) / math.log(abs(beta)) if 0 < abs(beta) < 1 else float("inf")
    over2 = sum(1 for z in zs if abs(z) > 2)
    print(
        f"|z|>2 days: {over2} ({100*over2/len(zs):.1f}%)  "
        f"AR(1) beta {beta:.3f}  half-life {half_life:.1f}d"
    )

    # Next-day-entry fade (the honest variant; still artifact-contaminated).
    cost = 0.0020
    pnl: list[float] = []
    i = 0
    while i < len(zs) - 1:
        z = zs[i]
        if abs(z) >= 2:
            entry = dev[i + 1]
            side = -1 if z > 0 else 1
            j, exit_dev = i + 2, None
            while j < len(zs) and j <= i + 11:
                if (zs[j] <= 0 < z) or (zs[j] >= 0 > z):
                    exit_dev = dev[j]
                    break
                j += 1
            if exit_dev is None:
                exit_dev = dev[min(i + 11, len(dev) - 1)]
            pnl.append(side * (exit_dev - entry) - cost)
            i = j
        i += 1
    wins = sum(1 for p in pnl if p > 0)
    print(
        f"next-day fade: {len(pnl)} trades  mean {100*st.mean(pnl):.3f}%  "
        f"total {100*sum(pnl):.2f}%  win {100*wins/len(pnl):.0f}%"
    )


if __name__ == "__main__":
    main()
