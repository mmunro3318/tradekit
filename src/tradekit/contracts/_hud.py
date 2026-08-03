"""HUD advisory payload models (SPEC-hud-orderbook T1, DESIGN §Contracts).

Pure data — no behavior. `AdvisoryTicket` mirrors the Kraken OSO bracket
ticket transcription (docs/handoff/HANDOFF-2026-07-20-hud-commit.md
§elements 1-16); `GateResult`/`ScanReportEntry` carry the scan-report
transparency layer; `HudState` is the shared secret between
`hud.build_state` and `hud.render`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import AwareDatetime

from tradekit.contracts._base import FrozenModel


class GateResult(FrozenModel):
    name: str
    passed: bool
    observed: str  # rendered value, e.g. "DSR=0.61"
    threshold: str  # e.g. ">= 0.5"
    rationale: str


class ScanReportEntry(FrozenModel):
    symbol: str
    timeframe: str
    indicators: tuple[tuple[str, str], ...]  # (name, rendered value)
    gates: tuple[GateResult, ...]
    grade: Literal["buy", "sell", "hold", "wait"]
    grade_rationale: str


class AdvisoryTicket(FrozenModel):
    pair: str  # "LINK/USD"
    side: Literal["buy", "sell"]
    mode: Literal["spot"]
    order_type: Literal["limit"]
    limit_price: Decimal
    quantity: Decimal
    est_total_usd: Decimal
    oso: Literal["bracket"]
    tp_price: Decimal
    tp_distance_pct: Decimal
    sl_price: Decimal
    sl_distance_pct: Decimal
    est_pnl_tp_usd: Decimal
    est_pnl_sl_usd: Decimal
    est_fee_usd: Decimal
    trigger_signal: Literal["last"]
    post_only: bool
    tif: Literal["gtc"]
    warnings: tuple[str, ...]
    thesis_id: str
    verdict_id: str
    created_at: AwareDatetime
    # SPEC-cadence T1-AC-2: additive, defaults to the "unclaimed/manual"
    # sentinel so pre-batch fixtures (no strategy_key kwarg) still validate.
    strategy_key: str = ""


class HudState(FrozenModel):
    generated_at: AwareDatetime
    tickets: tuple[AdvisoryTicket, ...]
    report: tuple[ScanReportEntry, ...]
    # SPRINT-TICKET-001 P4: plain dicts, verbatim the scanner's `"attrition"`
    # entry shape (`_scanner.scan`'s P3 output) plus hud's own two extra
    # stage names ("sizing", "policy_verdict") — CTO-adjudicated, no
    # dedicated pydantic model this batch (ASSUMPTIONS-FLAG in
    # tests/unit/hud/test_hud_attrition.py). Defaults to `()` so pre-existing
    # `HudState(...)` construction sites stay valid (additive field).
    attrition: tuple[dict[str, Any], ...] = ()


__all__ = [
    "AdvisoryTicket",
    "GateResult",
    "HudState",
    "ScanReportEntry",
]
