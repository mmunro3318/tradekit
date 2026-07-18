"""scripts/smoke_alpaca_paper.py — SPRINT P4-PAPER batch A dress-rehearsal
smoke script (addendum 2).

NOT a test (no pytest here; hits the REAL Alpaca PAPER trading API and
writes a real $10 BTC/USD paper order into Mike's Alpaca paper account).
Mike (or any dev with `ALPACA_API_KEY_ID`/`ALPACA_API_SECRET` set) runs this
once by hand to re-run the CTO's own probe (docs/research/
alpaca-paper-shapes-2026-07-18.json, 2026-07-18 UTC — a real $10 BTC/USD
paper order's full lifecycle) and eyeball that `AlpacaBroker`'s normalized
output still matches the shape the respx fixtures in
tests/unit/broker/test_alpaca_broker.py were captured from:

    uv run python scripts/smoke_alpaca_paper.py

This SPRINT P4-PAPER batch A: `AlpacaBroker`'s methods are still
`NotImplementedError` stubs (`src/tradekit/broker/_alpaca.py`), so running
this script today prints the lifecycle stages up to the first stub call and
then reports the `NotImplementedError` plainly — that IS the expected
result until the batch-B dev pass lands the real bodies. This script is
written NOW (not deferred to batch B) so Mike can run it unchanged the
moment batch B ships, exactly mirroring `scripts/smoke_data.py`/
`scripts/smoke_scan.py`'s own "write it once, it just starts working" DoD
convention.

Money note: this places a REAL (paper-money, zero financial risk) order on
Mike's Alpaca PAPER account — never live. `broker.get("live:alpaca")` is
the separate, fail-closed live path (`LiveTradingDisabled` unless BOTH the
`live_trading_enabled` dial AND `ALPACA_LIVE_KEY_ID`/`ALPACA_LIVE_SECRET`
are set) and this script never touches it.

Token note: this script is a REHEARSAL of the adapter in isolation, not a
run through the full `broker.execute_order` two-phase pipeline (that needs
a real thesis/policy-evaluate round-trip, out of scope for a smoke script)
— it seeds its own `VerdictIssued(allow=true)` event directly on a throwaway
ledger (`TK_DATA_DIR` under a tempdir), the same "earn the allow" pattern
`tests/unit/broker/test_alpaca_broker.py`'s `_seed_allow_verdict` helper
uses, so `AlpacaBroker.submit`'s real token-verification path (SPRINT
P4-PAPER batch B) is exercised honestly rather than bypassed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal

from ulid import ULID

_VERDICT_ID = "smoke-alpaca-paper-verdict"
_THESIS_ID = "smoke-alpaca-paper-thesis"
_ACCOUNT_REF = "alpaca-paper:smoke"


def main() -> None:
    # Isolate this script's ledger writes into a throwaway tempdir — never
    # touch data/ledger.db (same TK_DATA_DIR isolation discipline the test
    # suite's autouse fixture enforces, applied by hand here since a smoke
    # script runs outside pytest).
    os.environ.setdefault("TK_DATA_DIR", tempfile.mkdtemp(prefix="tk-smoke-alpaca-"))

    from tradekit.broker._alpaca import (
        ALPACA_PAPER_BASE_URL,
        ALPACA_PAPER_KEY_ID_ENV,
        ALPACA_PAPER_SECRET_ENV,
        AlpacaBroker,
    )
    from tradekit.broker._port import BrokerTokenRequired, LiveTradingDisabled, NoQuoteAvailable
    from tradekit.contracts import (
        AssetRef,
        Event,
        OrderRequest,
        VerdictIssuedPayload,
        VerdictToken,
    )
    from tradekit.ledger import default_ledger

    if not os.environ.get(ALPACA_PAPER_KEY_ID_ENV) or not os.environ.get(ALPACA_PAPER_SECRET_ENV):
        print(
            f"missing {ALPACA_PAPER_KEY_ID_ENV}/{ALPACA_PAPER_SECRET_ENV} in the environment -- "
            "set your Alpaca PAPER key pair before running this rehearsal (never Alpaca LIVE "
            "keys; this script only ever touches the paper base URL)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"base_url: {ALPACA_PAPER_BASE_URL}")
    print(f"account_ref: {_ACCOUNT_REF}")

    ledger = default_ledger()
    now = datetime.now(tz=UTC)
    ledger.append(
        Event(
            event_id=str(ULID()),
            ts_utc=now,
            type="VerdictIssued",
            actor="system:smoke-alpaca-paper",
            run_id=None,
            schema_ver=1,
            payload=VerdictIssuedPayload(
                verdict_id=_VERDICT_ID,
                kind="submit_order",
                account_ref=_ACCOUNT_REF,
                thesis_id=_THESIS_ID,
                allow=True,
                policy_version_hash="0" * 64,
            ).model_dump(mode="json"),
        )
    )
    verdict = VerdictToken(verdict_id=_VERDICT_ID, policy_version_hash="0" * 64)

    adapter = AlpacaBroker(
        account_ref=_ACCOUNT_REF,
        base_url=ALPACA_PAPER_BASE_URL,
        key_id_env=ALPACA_PAPER_KEY_ID_ENV,
        secret_env=ALPACA_PAPER_SECRET_ENV,
        ledger=ledger,
    )

    # $10 notional BTC/USD market buy -- the SAME order shape the CTO's own
    # 2026-07-18 probe placed (docs/research/alpaca-paper-shapes-2026-07-18.json).
    order = OrderRequest(
        thesis_id=_THESIS_ID,
        account_ref=_ACCOUNT_REF,
        asset=AssetRef(
            symbol="BTC/USD", venue="alpaca", asset_class="crypto", tick_size=Decimal("0.01")
        ),
        side="buy",
        order_type="market",
        qty=Decimal("10") / Decimal("65000"),  # ~$10 notional at a round BTC estimate
    )

    print("\n--- stage: submit ---")
    try:
        ack = adapter.submit(order, verdict)
    except (BrokerTokenRequired, LiveTradingDisabled, NoQuoteAvailable, NotImplementedError) as exc:
        print(f"submit() raised {type(exc).__name__}: {exc}")
        print(
            "\n(expected result on SPRINT P4-PAPER batch A -- AlpacaBroker.submit is still a "
            "NotImplementedError stub; re-run this script once batch B lands the real body)"
        )
        return
    print(f"order_id={ack.order_id} status={ack.status} ts_utc={ack.ts_utc}")

    print("\n--- stage: order_status polling ---")
    for _ in range(10):
        status = adapter.order_status(ack.order_id)
        print(f"  status={status.status} filled_qty={status.filled_qty}")
        if status.status == "filled":
            break
        time.sleep(1)

    print("\n--- stage: fills ---")
    fills = adapter.fills(now)
    for fill in fills:
        print(
            f"  order_id={fill.order_id} price={fill.price} qty={fill.qty} "
            f"fees_usd={fill.fees_usd} ts_utc={fill.ts_utc}"
        )

    print("\n--- stage: account ---")
    account = adapter.account()
    print(
        f"  equity_usd={account.equity_usd} settled_cash_usd={account.settled_cash_usd} "
        f"buying_power_usd={account.buying_power_usd}"
    )


if __name__ == "__main__":
    main()
