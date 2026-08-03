"""tests for the S2 vocabulary additions' tag/family registration in
`tradekit.strategies.TAGS` (STRATEGY-PACK.md "Vocabulary additions" table:
`ema_above` -> tag `trend_up` -> family `momentum`; `rsi_band` -> tag
`pullback` -> family `momentum`). Both families are pinned VERBATIM by the
doc's own table (column 4, "family") — no ASSUMPTIONS-FLAG needed for the
family assignment itself (the dispatch prompt's "if the doc is silent,
ASSUMPTION-FLAG" branch does not trigger; the doc is not silent here).

RED stage: neither "trend_up" nor "pullback" exists in `strategies.TAGS`
yet — these are plain dict-membership assertions against real, already-
importable data (same "contracts are cheap, real data, no stub" precedent
as `tests/unit/test_strategies_registry.py`), so they fail as ordinary
`AssertionError`s, not collection errors.

Seam: none needed — `strategies.TAGS` is a stdlib-only module-level dict,
no monkeypatching required. Kept in its own file (not appended to the
existing `tests/unit/test_strategies_registry.py`) per surgical-change
discipline — that file's existing tests are frozen S1/T-MTF-3-era pins and
must not be touched by this S2 batch.
"""

from __future__ import annotations

from tradekit import strategies
from tradekit.mae import _scanner


def test_trend_up_tag_registers_with_momentum_family() -> None:
    assert strategies.TAGS.get("trend_up") == "momentum"


def test_pullback_tag_registers_with_momentum_family() -> None:
    assert strategies.TAGS.get("pullback") == "momentum"


def test_families_still_sorted_non_none_value_set_after_s2_additions() -> None:
    # BEHAVIOR: strategies.FAMILIES is computed FROM TAGS (module-load-time
    # derivation, strategies.py's own `tuple(sorted({... for ... in TAGS
    # .values() ...}))`) -- adding trend_up/pullback (both "momentum",
    # already a member) must not introduce a new family name or duplicate.
    assert strategies.FAMILIES == ("breakout", "mean_reversion", "momentum")


def test_scanner_tag_strategy_shares_the_new_tags_by_identity() -> None:
    # SEAM/CONTRACT: `_scanner._TAG_STRATEGY IS strategies.TAGS` (existing
    # pin, tests/unit/test_strategies_registry.py
    # test_scanner_tag_strategy_is_the_same_object_as_the_shared_registry) --
    # the new S2 tags must appear on the scanner's side too, for free, via
    # that same identity (no second edit site).
    assert _scanner._TAG_STRATEGY is strategies.TAGS
    assert _scanner._TAG_STRATEGY.get("trend_up") == "momentum"
    assert _scanner._TAG_STRATEGY.get("pullback") == "momentum"
