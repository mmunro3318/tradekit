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


def daily_memo(thesis_id: str) -> str:
    """SME §3 practitioner memo for `thesis_id` (module docstring)."""
    raise NotImplementedError("SPRINT P3 batch E — report.daily_memo")


def readiness_report() -> str:
    """The promotion one-pager — thin format of `policy.promotion_status()`
    (module docstring)."""
    raise NotImplementedError("SPRINT P3 batch E — report.readiness_report")


def pnl_snapshot(account_ref: str) -> str:
    """The D4 verified-snapshot artifact for `account_ref` (module
    docstring)."""
    raise NotImplementedError("SPRINT P3 batch E — report.pnl_snapshot")


__all__ = ["daily_memo", "pnl_snapshot", "readiness_report"]
