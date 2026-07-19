"""tradekit.strategies — the shared tag->family registry (ASSUMPTIONS 57f;
SPRINT P3 batch E, sprint-doc addendum: "one source of truth").

`strategies.TAGS`/`FAMILIES` are REAL data (see `strategies.py`'s own module
docstring). The dev pass this file originally described as pending (round-21
red phase, `tests/ASSUMPTIONS.md`) has LANDED: `mae._scanner._TAG_STRATEGY`
is re-derived FROM `strategies.TAGS` (same object, not a copy), so a registry
edit propagates to the scanner/regime gate without a second edit. Every test
below now pins that CURRENT, green, one-source-of-truth behavior — none of
them describe a pre-implementation gap any more (test-audit-2026-07-18.md
garbage-removal item 6: the names/docstrings were stale "RED"-era wording
that passed for the OPPOSITE of what they claimed). Golden-compatibility
(scanner/regime OUTPUT VALUES unchanged) stays covered by the pre-existing
frozen tests in `tests/unit/mae/`.
"""

from __future__ import annotations

from tradekit import strategies
from tradekit.mae import _regime, _scanner


def test_tags_seed_matches_scanners_existing_mapping_verbatim() -> None:
    """`strategies.TAGS` must equal `_scanner._TAG_STRATEGY`'s values
    (ASSUMPTIONS 57f's mapping) — now trivially true by IDENTITY (see
    `test_scanner_tag_strategy_is_the_same_object_as_the_shared_registry`,
    the dev pass re-derived `_scanner._TAG_STRATEGY` from `strategies.TAGS`
    directly), kept as its own value-level pin so a future refactor that
    breaks the identity link still gets caught by a value mismatch here."""
    assert strategies.TAGS == _scanner._TAG_STRATEGY


def test_families_is_the_sorted_non_none_value_set_of_tags() -> None:
    assert strategies.FAMILIES == ("breakout", "mean_reversion", "momentum")
    assert set(strategies.FAMILIES) == {v for v in strategies.TAGS.values() if v is not None}


def test_regime_strategy_tags_families_are_within_the_shared_vocabulary() -> None:
    """Golden-compatibility floor: every family name `_regime._STRATEGY_TAGS`
    ever emits (recommended OR avoid) must already be a member of
    `strategies.FAMILIES` — true today (both modules were hand-authored
    against the same three family names), so this passes now and stays true
    once `_regime` is rewired to reference `strategies.FAMILIES` directly
    instead of re-typing the three strings."""
    for recommended, avoid in _regime._STRATEGY_TAGS.values():
        assert set(recommended) <= set(strategies.FAMILIES)
        assert set(avoid) <= set(strategies.FAMILIES)


def test_scanner_tag_strategy_is_the_same_object_as_the_shared_registry() -> None:
    """Pins the "one source of truth" requirement itself: `_scanner.
    _TAG_STRATEGY` is re-derived FROM `strategies.TAGS` (identity, not a
    value-equal copy) — the dev pass landed this (test-audit-2026-07-18.md
    item 6 renamed this test from its stale RED-era "is_not_yet" name/
    docstring, which described the pre-implementation gap this test now
    proves is closed)."""
    assert _scanner._TAG_STRATEGY is strategies.TAGS, (
        "mae._scanner._TAG_STRATEGY must be re-derived FROM tradekit.strategies.TAGS "
        "(the same object, e.g. `_TAG_STRATEGY = strategies.TAGS`) so a registry edit "
        "propagates to the scanner without a second edit"
    )


def test_registry_edit_propagates_to_the_regime_gate(monkeypatch) -> None:
    """The concrete "does a registry change propagate" scenario the
    sprint doc asked for, now pinned green: flip `oversold`'s family from
    `mean_reversion` to `breakout` in the SHARED registry, and
    `_scanner._apply_regime_gate` (reading the SAME object per the test
    above, no private copy left to go stale) keeps `oversold` for a regime
    recommending only `breakout` (test-audit-2026-07-18.md item 6 renamed
    this from its stale RED-era docstring, which described this propagation
    as not-yet-working)."""
    monkeypatch.setitem(strategies.TAGS, "oversold", "breakout")
    kept = _scanner._apply_regime_gate(["oversold"], {"recommended_strategies": ["breakout"]})
    assert kept == ["oversold"], (
        "editing tradekit.strategies.TAGS must change what mae._scanner._apply_regime_gate "
        "keeps -- it currently does not, because _scanner reads its own private copy"
    )
