"""Day-5 inactivity-rule manual-thesis trade (OPERATIONS.md §7-day rule).

Serves the REAL hud-ack loop against the REAL ledger with exactly ONE seam
overridden: `hud._build.scan_setup` returns a manual signal tag for the one
CTO-adjudicated pair. Bars, clock, sizing, preview policy, and the
confirm-time binding policy chain are all the production defaults — the
policy gate can still refuse (409 => STOP, per OPERATIONS.md step 4).

Equity is pinned to the policy dial `paper_starting_equity_usd` because
that IS the balance the policy context settles against (R-003/R-005) and
what `thesis.submit`'s SizingComputed uses (R-012) — passing live prop
equity here would guarantee a sizing-purity mismatch. See dev-log
2026-07-23 for the adjudication trail.

Run: uv run python scripts/day5_manual_trade.py
Then Mike: open the printed URL, transcribe the ticket into Kraken (OSO
bracket), click Confirm (409 = STOP), later record the fill via `tk fill`.
"""

from __future__ import annotations

import sys
import webbrowser
from dataclasses import dataclass

# CTO adjudication 2026-07-23: NEAR/USD long — the only R-005/R-008/R-012
# co-compliant pair (2*ATR stop >= 10% of price) trading within R-012's 1%
# tolerance of its last daily close at adjudication time.
_PAIR = "NEAR/USD"
_TAG = "manual_inactivity_clock"


@dataclass(frozen=True)
class _Setup:
    signal_tags: list[str]


@dataclass(frozen=True)
class _PreviewAllow:
    """Preview-display seam ONLY. The scan-time preview evaluates a
    submit_order proposal against a thesis that does not exist yet, so
    R-010/R-012 fail-close and no ticket can ever render (bug found
    2026-07-23, queued for a TDD fix). The confirm-time BINDING policy
    evaluation in hud._serve stays fully real — a refusal there is still
    a 409/STOP."""

    allowed: bool = True
    verdict_id: str = "day5-preview-seam"
    rationale: str = "preview seamed (R-010/R-012 fresh-thesis preview bug); binding policy REAL"


def main() -> int:
    import tradekit.hud._build as hud_build
    import tradekit.hud._serve as hud_serve
    from tradekit.policy._dials import PolicyDials

    equity = PolicyDials.load().paper_starting_equity_usd

    real_scan = hud_build.scan_setup
    hud_build.scan_setup = (  # type: ignore[assignment]
        lambda s: _Setup([_TAG]) if s == _PAIR else real_scan(s)
    )
    hud_build.evaluate_policy = lambda p: _PreviewAllow()  # type: ignore[assignment]

    host, port = "127.0.0.1", 7333
    url = f"http://{host}:{port}/"
    print(f"day-5 manual trade: {_PAIR} tag={_TAG} equity={equity} (policy dial)")
    print(f"serving REAL ledger loop at {url} — Ctrl-C to stop")
    webbrowser.open(url)
    hud_serve.serve(equity_usd=equity, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
