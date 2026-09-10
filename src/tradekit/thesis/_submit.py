"""`thesis.submit` mechanics — snapshot, sizing, predicate requantization, and
EV validation (DESIGN §10.1, SPRINT P2 batch A story 1 + CTO addendum).

Deliberately private and pure-ish: `build_submit_payloads` does ALL the work
that can fail (market-data fetch, `mae.size_position`, EV tolerance check)
and returns the three typed payloads ready to append, in the pinned order —
`thesis.submit()` itself only calls this, then appends
(ASSUMPTIONS 65: "validates EVERYTHING first, then appends [...] in the EXACT
order MarketSnapshotTaken -> SizingComputed -> ThesisSubmitted"). Nothing in
this module touches the ledger.

Sanctioned cross-module seam (CTO addendum, story-1 pins): `thesis` may
import `mae._runtime` and call `get_closed_bars`/`clock` ONLY — imported as
`from tradekit.mae import _runtime as _mae_runtime`, module-attribute calls,
so tests monkeypatching `"tradekit.mae._runtime.get_closed_bars"` /
`"tradekit.mae._runtime._clock"` by dotted string path see the effect here
too. `mae.size_position` is called through the public `tradekit.mae` module
attribute (`from tradekit import mae`), never bypassed, so it stays the
single source of truth for R-012's sizing-purity comparison.

SPRINT P2 batch C: the `PAPER_STARTING_EQUITY_USD` hardcode (ASSUMPTIONS
61, "ratified-temporary, must not survive the sprint") is RETIRED this
batch — sizing now reads `PolicyDials.load().paper_starting_equity_usd` at
call time (no caching, same discipline as `TK_CONFIG_PATH`/`TK_DATA_DIR`).
`thesis` importing `tradekit.policy._dials` (dials only, nothing else from
`policy`) does not create a cycle: `policy` imports nothing from `thesis`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ulid import ULID

from tradekit import mae
from tradekit.contracts import (
    MarketSnapshotTakenPayload,
    SizingComputedPayload,
    ThesisSubmittedPayload,
    quantize,
)
from tradekit.mae import _runtime as _mae_runtime
from tradekit.policy._dials import PolicyDials

# SME F5: recompute must not differ from the stated EV by more than one cent.
_EV_TOLERANCE_USD = Decimal("0.01")

# MVP: enough lookback for `_mae_runtime.get_closed_bars` to return at least
# one closed daily bar; the exact figure is not load-bearing (only the LAST
# closed bar is used for the snapshot).
_SNAPSHOT_LOOKBACK_DAYS = 30


def build_submit_payloads(
    thesis_id: str, contract: dict[str, Any]
) -> tuple[MarketSnapshotTakenPayload, SizingComputedPayload, ThesisSubmittedPayload]:
    """Validate everything a submit needs and return the three payloads to
    append, in order. Raises `ValueError` on EV-tolerance failure (or on an
    empty bar series); propagates whatever `mae.size_position`/
    `_mae_runtime.get_closed_bars` raise for genuine market-data problems.
    Either way, the caller has appended nothing when this raises.

    ASSUMPTIONS 182 (SPEC-sizing-cap P4): sizes off `entry.limit_price` when
    the contract carries one (falling back to the snapshot's daily close
    otherwise) and clips to `PolicyDials.paper_max_position_usd` for
    `paper:` account refs — the same price/equity/cap basis `hud._build`'s
    scan-time preview now uses, so R-012 compares like with like.

    review round 24 F1 (ASSUMPTIONS 182.10, SPEC-sizing-cap P4'): also
    resolves the contract's own `strategy_tag` against `mae.STRATEGY_BY_KEY`
    and forwards its `size_scale` (1 for no match/no tag) into `mae.
    size_position` — the SAME def `hud._build`'s preview claimed, so a
    restricted-size strategy (e.g. S4) records the scaled notional here too,
    instead of the ticket's own post-hoc multiply drifting from what gets
    ledgered."""
    ev_recomputed, ev_stated = _validate_ev(contract["ev_block"], thesis_id)

    asset = contract["asset"]
    symbol = str(asset["symbol"])
    tick_size = Decimal(str(asset["tick_size"]))

    bars = _mae_runtime.get_closed_bars(symbol, "1d", _SNAPSHOT_LOOKBACK_DAYS)
    if not bars.bars:
        raise ValueError(f"no closed daily bars available for {symbol!r} to snapshot")
    last_close = quantize(bars.bars[-1].close, tick_size)
    snapshot_payload = MarketSnapshotTakenPayload(
        thesis_id=thesis_id,
        snapshot_id=str(ULID()),
        symbol=symbol,
        ts=_mae_runtime.clock(),
        last_close=last_close,
        source=bars.source,
    )

    entry = contract["entry"]
    reference_price = (
        Decimal(str(entry["limit_price"])) if entry.get("limit_price") is not None else last_close
    )
    account_ref = str(contract["account_ref"])
    dials = PolicyDials.load()
    paper_starting_equity_usd = dials.paper_starting_equity_usd
    cap = dials.paper_max_position_usd if account_ref.startswith("paper:") else None
    strategy_tag = str(contract.get("strategy_tag") or "")
    strategy_def = mae.STRATEGY_BY_KEY.get(strategy_tag) if strategy_tag else None
    size_scale = strategy_def.size_scale if strategy_def is not None else Decimal("1")
    sizing = mae.size_position(
        symbol,
        account_equity_usd=paper_starting_equity_usd,
        price=reference_price,
        max_position_usd=cap,
        size_scale=size_scale,
    )
    sizing_payload = SizingComputedPayload(
        thesis_id=thesis_id,
        symbol=symbol,
        account_equity_usd=paper_starting_equity_usd,
        sizing=sizing,
    )

    submitted_payload = ThesisSubmittedPayload(
        thesis_id=thesis_id,
        market_snapshot_id=snapshot_payload.snapshot_id,
        resolved_target_price=quantize(contract["target_price"], tick_size),
        resolved_stop_price=quantize(contract["stop_price"], tick_size),
        resolved_success_criteria=[
            _requantize_predicate(p, tick_size) for p in contract["success_criteria"]
        ],
        resolved_failure_criteria=[
            _requantize_predicate(p, tick_size) for p in contract["failure_criteria"]
        ],
        ev_stated_usd=ev_stated,
        ev_recomputed_usd=ev_recomputed,
    )
    return snapshot_payload, sizing_payload, submitted_payload


def _validate_ev(ev_block: dict[str, Any], thesis_id: str) -> tuple[Decimal, Decimal]:
    """Returns (recomputed, stated); raises ValueError if they diverge by
    more than `_EV_TOLERANCE_USD` (SME F5)."""
    p_win = Decimal(str(ev_block["p_win"]))
    reward_usd = Decimal(str(ev_block["reward_usd"]))
    risk_usd = Decimal(str(ev_block["risk_usd"]))
    ev_stated = Decimal(str(ev_block["ev_usd"]))
    ev_recomputed = p_win * reward_usd - (Decimal("1") - p_win) * risk_usd
    if abs(ev_stated - ev_recomputed) > _EV_TOLERANCE_USD:
        raise ValueError(
            f"EV validation failed for thesis_id={thesis_id!r}: stated={ev_stated} "
            f"recomputed={ev_recomputed} diverges by more than {_EV_TOLERANCE_USD} (SME F5)"
        )
    return ev_recomputed, ev_stated


def _requantize_predicate(predicate: dict[str, Any], tick_size: Decimal) -> dict[str, Any]:
    """Every price-carrying predicate's `value` re-quantized onto the asset's
    tick grid (CTO addendum); every other field passes through unchanged."""
    resolved = dict(predicate)
    if resolved.get("value") is not None:
        resolved["value"] = str(quantize(resolved["value"], tick_size))
    return resolved
