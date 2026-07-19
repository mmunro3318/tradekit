"""Read-only Kraken Spot private-API probe (no order endpoints imported or called).

Purpose: determine whether a Kraken Pro API key sees the Kraken Prop
sub-account (Report 1 open question #3). Calls Balance, BalanceEx,
TradeBalance, OpenOrders, OpenPositions, Ledgers and prints shapes +
values. A $5,000 Prop account that is invisible here answers the
question one way; a balance entry near $5,000 answers it the other.

Run: uv run python scripts/smoke_kraken_probe.py
Requires KRAKEN_LIVE_API_KEY / KRAKEN_LIVE_API_SECRET in .env.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import httpx

BASE_URL = "https://api.kraken.com"

# Read-only endpoints only. Nothing in this file places, amends, or
# cancels orders; keep it that way.
PROBES: list[tuple[str, dict[str, str]]] = [
    ("Balance", {}),
    ("BalanceEx", {}),
    ("TradeBalance", {"asset": "ZUSD"}),
    ("OpenOrders", {}),
    ("OpenPositions", {}),
    ("Ledgers", {"ofs": "0"}),
]


def _load_env() -> tuple[str, str]:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("KRAKEN_LIVE_API_KEY", "")
    secret = os.environ.get("KRAKEN_LIVE_API_SECRET", "")
    if not key or not secret:
        # no-creds-is-loud: never fabricate or silently skip
        sys.exit("FATAL: KRAKEN_LIVE_API_KEY / KRAKEN_LIVE_API_SECRET missing")
    return key, secret


def _sign(url_path: str, data: dict[str, str], secret: str) -> str:
    postdata = urllib.parse.urlencode(data)
    encoded = (data["nonce"] + postdata).encode()
    message = url_path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def private_post(
    client: httpx.Client, key: str, secret: str, endpoint: str, payload: dict[str, str]
) -> dict[str, object] | list[str]:
    data = dict(payload)
    data["nonce"] = str(int(time.time() * 1000))
    url_path = f"/0/private/{endpoint}"
    headers = {"API-Key": key, "API-Sign": _sign(url_path, data, secret)}
    r = client.post(f"{BASE_URL}{url_path}", headers=headers, data=data)
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        return body["error"]  # surface Kraken's error verbatim, don't raise
    result: dict[str, object] = body["result"]
    return result


def main() -> None:
    key, secret = _load_env()
    print(f"probe target: {BASE_URL} (Spot private API), key ...{key[-4:]}")
    with httpx.Client(timeout=30.0) as client:
        for endpoint, payload in PROBES:
            try:
                result = private_post(client, key, secret, endpoint, payload)
            except httpx.HTTPError as exc:
                print(f"\n== {endpoint}: TRANSPORT ERROR {exc!r}")
                continue
            print(f"\n== {endpoint} ==")
            if isinstance(result, list):
                print(f"KRAKEN ERROR: {result}")
            else:
                print(json.dumps(result, indent=2, default=str)[:3000])
            time.sleep(1.2)  # stay far under private-endpoint rate limits


if __name__ == "__main__":
    main()
