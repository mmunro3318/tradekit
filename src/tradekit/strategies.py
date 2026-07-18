"""tradekit.strategies — canonical strategy-tag registry (ASSUMPTIONS 57f;
SPRINT P3 batch E, sprint-doc addendum: "one source of truth").

Shared leaf, stdlib-only (same class of module as `tradekit.contracts`/
`tradekit.costs` per DESIGN §4.2 — importable from anywhere, imports nothing
from `tradekit`). `TAGS` is the SEED of `mae._scanner._TAG_STRATEGY` — the
values transcribed here are IDENTICAL to that module's own session-chosen
mapping (ASSUMPTIONS 57f), not a new decision; this module only promotes an
existing mapping to a single shared source so `mae._regime._STRATEGY_TAGS`
can validate its own family vocabulary against it instead of re-typing the
three family name strings independently.

Status (SPRINT P3 batch E, TDD red phase): `TAGS`/`FAMILIES` are REAL,
declarative data (same "contracts/dials are cheap" precedent as
`policy._dials.PolicyDials`/`policy._rules.RULES` — no stub needed for a
frozen mapping). What's RED this batch is the RE-DERIVATION itself:
`mae._scanner._TAG_STRATEGY` and `mae._regime._STRATEGY_TAGS` still carry
their own independent module-level dicts as of this commit — they do not
yet import/reference this module at all. `tests/unit/test_strategies_
registry.py` pins the propagation requirement (scanner's `_TAG_STRATEGY`
must BE this module's `TAGS`, by identity, once the dev pass re-derives it)
as ordinary assertion failures against already-real, frozen-golden modules
— NOT `NotImplementedError` (there is no stub to call; `_scanner`/`_regime`
are complete, golden-pinned modules per SPRINT P1C, and rewiring their
module-level constants is exactly the dev pass's job, flagged in the
ASSUMPTIONS round-21 entry for this batch rather than improvised here).
"""

from __future__ import annotations

# Signal-tag -> strategy-family map — verbatim transcription of
# `mae._scanner._TAG_STRATEGY`'s existing (ASSUMPTIONS 57f, session-chosen,
# not itself CTO-ratified) mapping. `None` means the tag carries no strategy
# affiliation and always survives `mae._scanner._apply_regime_gate`.
TAGS: dict[str, str | None] = {
    "oversold": "mean_reversion",
    "overbought": "mean_reversion",
    "macd_bullish": "momentum",
    "macd_bearish": "momentum",
    "at_support": "mean_reversion",
    "at_resistance": "mean_reversion",
    "bb_inside": None,
    "volume_spike": "breakout",
    "high_volatility": "breakout",
}

# The canonical strategy-family vocabulary, derived from TAGS's own non-None
# values (sorted for a deterministic, diff-friendly tuple) — this is what
# `mae._regime._STRATEGY_TAGS`'s recommended/avoid lists are validated
# against (every family name either module ever emits must appear here).
FAMILIES: tuple[str, ...] = tuple(
    sorted({family for family in TAGS.values() if family is not None})
)

__all__ = ["FAMILIES", "TAGS"]
