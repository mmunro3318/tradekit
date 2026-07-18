"""tradekit.report — thin templating over read models (DESIGN §12.3;
SPRINT P3 batch E). "Thin, no computation beyond formatting" per the
sprint-doc addendum — every field these verbs render is read verbatim off
`policy`/`ledger.models`/`ledger.query`, never recomputed here.

Deep interface: `daily_memo(thesis_id) -> str`, `readiness_report() -> str`,
`pnl_snapshot(account_ref) -> str`.

DESIGN PINS (CTO, binding on the dev pass):

- `daily_memo(thesis_id)`: renders the SME §3 "Daily Decision One-Pager"
  practitioner memo (`docs/research/perplexity-SME.md` §3) for ONE thesis —
  hypothesis (`rationale`), market context (the `MarketSnapshotTaken`
  payload nearest submission), strategy (`entry`), size (`size_usd`/
  `sizing_method`), risk (stop/invalidation/max-loss/correlated positions),
  numeric EV (`ev_block`, EXPLICIT arithmetic per SME §3's own callout —
  never a vague qualitative rationale), success/failure criteria, and gate
  status (the thesis's own `VerdictIssued`/`ReviewCompleted` history).
  Writes to `docs/reports/` (a NEW file-writer — path seam required, cross-
  cutting pin) AND returns the same markdown string.

- `readiness_report()`: the promotion one-pager (SCOPE §5) — thin
  formatting of `policy.promotion_status()`'s OWN dict, rendered
  VERBATIM including the full `t2_eligible.criteria` per-criterion
  breakdown (sprint-doc addendum: "the D7 stakes-without-deception
  surface" — a reader must see EXACTLY which of the four T1->T2 conjuncts
  passed/failed, never a collapsed "eligible: false"). Argless, same
  signature convention as `promotion_status()` itself (single default-
  account MVP).

- `pnl_snapshot(account_ref)`: the D4 verified-snapshot artifact — realized
  pnl (`ledger.models` / `pnl_daily` projection), trade count, current
  series stats, formatted for a non-Anthropic model's `review.verify_claim`
  to check against broker records (§12.2).

Status (TDD red phase): all three verbs are unconditional
`NotImplementedError` stubs; `tests/unit/report/` pins the REAL target
behavior (assertion on KEY CONTENT PRESENCE, not a full golden string —
sprint-doc: "assert key content presence not full golden strings").
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Any


def daily_memo(thesis_id: str, reports_dir: str | None = None) -> str:
    """SME §3 practitioner memo for `thesis_id` (module docstring).
    `reports_dir` is the path seam (cross-cutting pin, "all new file-writers
    get path seams") — defaulted, same convention as `memory._wiki.add_note`'s
    `wiki_dir` default, so the pinned single-arg call site (`report.
    daily_memo(thesis_id)`) still works."""
    from tradekit.ledger import default_ledger
    from tradekit.thesis import _machine

    ledger = default_ledger()
    drafted = _machine.latest_payload(ledger, thesis_id, "ThesisDrafted")
    if drafted is None:
        raise ValueError(f"no ThesisDrafted event found for thesis_id={thesis_id!r}")
    contract: dict[str, Any] = drafted["contract"]

    snapshot = _machine.latest_payload(ledger, thesis_id, "MarketSnapshotTaken")
    review = _machine.latest_payload(ledger, thesis_id, "ReviewCompleted")

    ev_block: dict[str, Any] = contract.get("ev_block", {})
    entry: dict[str, Any] = contract.get("entry", {})
    invalidation: dict[str, Any] = contract.get("invalidation", {})

    gate_status = "UNKNOWN — no ReviewCompleted on record"
    if review is not None:
        gate_status = "PASSED" if review.get("passed") else "FAILED"

    market_context = "(no MarketSnapshotTaken on record)"
    if snapshot is not None:
        market_context = (
            f"snapshot: {snapshot.get('symbol')} @ {snapshot.get('last_close')} "
            f"({snapshot.get('ts')}, source={snapshot.get('source')})"
        )

    lines = [
        f"# DAILY TRADE MEMO — {contract.get('thesis_id', thesis_id)} — "
        f"{contract.get('asset', {}).get('symbol', '')}",
        "",
        "## Hypothesis",
        str(contract.get("rationale", "")),
        "",
        "## Market Context",
        market_context,
        "",
        "## Strategy",
        f"entry: {entry.get('order_type')} @ {entry.get('limit_price')}",
        f"direction: {contract.get('direction')}",
        f"strategy_tag: {contract.get('strategy_tag')}",
        "",
        "## Size",
        f"size_usd: {contract.get('size_usd')}",
        f"sizing_method: {contract.get('sizing_method')}",
        "",
        "## Risk",
        f"stop_price: {contract.get('stop_price')}",
        f"invalidation ({invalidation.get('kind')}): "
        f"{invalidation.get('attestation') or invalidation.get('predicate')}",
        f"max_loss_usd: {ev_block.get('risk_usd')}",
        "(correlated positions: no cross-thesis correlation read model wired yet — P3 scope gap)",
        "",
        "## EV",
        f"p_win: {ev_block.get('p_win')}",
        f"reward_usd: {ev_block.get('reward_usd')}",
        f"risk_usd: {ev_block.get('risk_usd')}",
        f"ev_usd: {ev_block.get('ev_usd')}",
        "",
        "## Success / Failure Criteria",
        f"success_criteria: {contract.get('success_criteria')}",
        f"failure_criteria: {contract.get('failure_criteria')}",
        "",
        "## GATE STATUS",
        f"GATE: {gate_status}",
    ]
    memo = "\n".join(lines)

    # Default under TK_DATA_DIR (state-hygiene: generated artifacts live in
    # the data dir, and the suite-wide tmp isolation covers them for free —
    # a repo-path default littered real docs/reports/ during test runs,
    # CTO-caught at the batch-E gate).
    if reports_dir is not None:
        out_dir = Path(reports_dir)
    else:
        out_dir = Path(os.environ.get("TK_DATA_DIR", "data")) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{thesis_id}.md").write_text(memo, encoding="utf-8")
    return memo


def readiness_report() -> str:
    """The promotion one-pager — thin format of `policy.promotion_status()`
    (module docstring). Renders the FULL `t2_eligible.criteria` per-criterion
    breakdown verbatim (D7 stakes-without-deception surface)."""
    from tradekit import policy

    status = policy.promotion_status()

    lines = [
        "# Promotion Readiness",
        "",
        f"account_ref: {status.get('account_ref')}",
        f"tier: {status['tier']}",
        f"live_sequence_remaining: {status.get('live_sequence_remaining')}",
        "",
        "## Current Series",
        f"index: {status['current_series']['index']}",
        f"window: {status['current_series']['window']}",
        f"counts: {status['current_series']['counts']}",
        f"clean_so_far: {status['current_series']['clean_so_far']}",
        "",
        "## Last 4 Series",
    ]
    for series in status["last_4_series"]:
        lines.append(f"- {series}")
    lines += [
        "",
        f"## T2 Eligibility — eligible: {status['t2_eligible']['eligible']}",
    ]
    for name, passed in status["t2_eligible"]["criteria"].items():
        lines.append(f"- {name}: {passed}")
    return "\n".join(lines)


def pnl_snapshot(account_ref: str) -> str:
    """The D4 verified-snapshot artifact for `account_ref` (module
    docstring): realized pnl + trade count off `ledger.models.
    latest_grades()` (never re-derived), plus the account's current series
    stats (`policy._series`, the same read-only "policy._dials reuse" class
    of cross-module data dependency ASSUMPTIONS round-21 entry 136 ratifies)."""
    from tradekit.ledger import default_ledger
    from tradekit.policy import _context, _series
    from tradekit.policy._dials import PolicyDials

    ledger = default_ledger()
    dials = PolicyDials.load()

    grades = ledger.models.latest_grades(n=1_000_000)
    account_grades = [g for g in grades if g.account_ref == account_ref]
    realized_pnl = sum(
        (g.pnl_usd for g in account_grades if g.pnl_usd is not None), Decimal("0")
    )
    trade_count = len(account_grades)

    now = _context.clock()
    current_idx = _series.series_index(now, dials.series_epoch)
    stats = _series.series_stats(ledger, account_ref, current_idx, dials, now)

    lines = [
        f"# PnL Snapshot — {account_ref}",
        "",
        f"account_ref: {account_ref}",
        f"realized_pnl_usd: {realized_pnl}",
        f"trade_count: {trade_count}",
        "",
        "## Current Series",
        f"series_index: {stats.series_index}",
        f"window: [{stats.window_start.isoformat()}, {stats.window_end.isoformat()})",
        f"graded_count: {stats.graded_count}",
        f"void_count: {stats.void_count}",
        f"expectancy: {stats.expectancy}",
        f"mdd_pct: {stats.mdd_pct}",
        f"complete: {stats.complete}",
        f"clean: {stats.clean}",
    ]
    return "\n".join(lines)


__all__ = ["daily_memo", "pnl_snapshot", "readiness_report"]
