"""tradekit.strategies — the shared tag->family registry (ASSUMPTIONS 57f;
SPRINT P3 batch E, sprint-doc addendum: "one source of truth").

`strategies.TAGS`/`FAMILIES` are REAL data (see `strategies.py`'s own module
docstring) — the tests here are NOT wrapped in `pytest.raises(
NotImplementedError)`, and most of them are ordinary assertion failures
against already-real, golden-frozen modules (`mae._scanner`/`mae._regime`),
not `NotImplementedError`s: there is no stub function to call, only two
already-complete modules that haven't been rewired to import FROM the new
shared registry yet. This is the one file in this batch's red phase that
deliberately deviates from the "new red is NotImplementedError only"
default — flagged in `tests/ASSUMPTIONS.md` round-21, not silently ratified
here. Golden-compatibility (scanner/regime OUTPUT VALUES unchanged) is
covered by the pre-existing frozen tests in `tests/unit/mae/`, which must
stay green throughout the dev pass's rewire — this file only pins the
re-derivation/propagation requirement itself.
"""

from __future__ import annotations

from tradekit import strategies
from tradekit.mae import _regime, _scanner


def test_tags_seed_matches_scanners_existing_mapping_verbatim() -> None:
    """`strategies.TAGS` must be a byte-for-byte transcription of `_scanner
    ._TAG_STRATEGY`'s CURRENT values (ASSUMPTIONS 57f's mapping, not a new
    decision) — this passes today by construction (both were authored from
    the same source) and pins that the seed is honest, not silently
    diverged, before the dev pass ever rewires either module."""
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


def test_scanner_tag_strategy_is_not_yet_the_shared_registry_object() -> None:
    """RED (assertion failure, not NotImplementedError — see module
    docstring): the sprint-doc pin requires `_scanner._TAG_STRATEGY` to be
    the SAME object as `strategies.TAGS` (import, not a copy) once the dev
    pass re-derives it — "one source of truth" only holds if a change to
    the registry propagates without touching `_scanner.py` again. As of
    this commit `_scanner._TAG_STRATEGY` is still `_scanner.py`'s own
    independent module-level dict (equal in VALUE, per the test above, but
    a distinct object) — this test names the gap explicitly rather than
    leaving it to be discovered as a silent non-propagation bug."""
    assert _scanner._TAG_STRATEGY is strategies.TAGS, (
        "mae._scanner._TAG_STRATEGY must be re-derived FROM tradekit.strategies.TAGS "
        "(the same object, e.g. `_TAG_STRATEGY = strategies.TAGS`) so a registry edit "
        "propagates to the scanner without a second edit — currently still independent"
    )


def test_registry_edit_propagates_to_the_regime_gate(monkeypatch) -> None:
    """RED (assertion failure): the concrete "does a registry change
    propagate" scenario the sprint doc asks for. Flip `oversold`'s family
    from `mean_reversion` to `breakout` in the SHARED registry; today
    `_scanner._apply_regime_gate` still reads its own private
    `_TAG_STRATEGY` copy, so a regime recommending only `breakout` still
    drops the `oversold` tag (the module never saw the edit) — once
    `_TAG_STRATEGY` is re-derived (previous test), this same monkeypatch
    must flip the gate's outcome instead."""
    monkeypatch.setitem(strategies.TAGS, "oversold", "breakout")
    kept = _scanner._apply_regime_gate(["oversold"], {"recommended_strategies": ["breakout"]})
    assert kept == ["oversold"], (
        "editing tradekit.strategies.TAGS must change what mae._scanner._apply_regime_gate "
        "keeps -- it currently does not, because _scanner reads its own private copy"
    )
