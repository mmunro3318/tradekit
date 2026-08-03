"""tests for `ThesisContract.horizon_hours` (STRATEGY-PACK S4 dispatch,
PINNED block: "thesis contract gains `horizon_hours: int = 168` (default =
today's 7d behavior, so every existing thesis is unchanged); S4 theses carry
`horizon_end = captured_at + 48h` -> `horizon_hours = 48`").

RED stage: `ThesisContract` (src/tradekit/contracts/_thesis.py) has no
`horizon_hours` field yet. `FrozenModel`'s `model_config` does not set
`extra="forbid"` (src/tradekit/contracts/_base.py), so passing
`horizon_hours=48` today is silently ignored rather than raising -- every
test below fails on the `.horizon_hours` attribute access itself
(`AttributeError: 'ThesisContract' object has no attribute
'horizon_hours'`), a real failure for the right reason, not a construction
error.

Mirrors the `fee_asset_qty` AC-1 backward-compat pattern verbatim
(tests/unit/contracts/test_event_payloads.py, SPEC-inkind-fees): a new
field on an existing frozen contract must (a) default without being passed
at all -- the "every producer call site written before this field existed"
case -- and (b) accept an explicit non-default value, round-tripping
unchanged.

=== ASSUMPTION-FLAG S4-2 (deferred, see also
tests/unit/mae/test_s4_reversion_strategy.py's module docstring) ===
No test here builds a thesis "FROM" `StrategyDef.s4_reversion` (e.g. a
scan match arming a draft with `horizon_hours=48` automatically) -- that
wiring does not exist in production code today. The only draft-building
function found (`hud/_serve.py:_build_minimal_contract`) hardcodes
`horizon_end = now + timedelta(days=7)` and `strategy_tag="hud-ack-manual"`
with no reference to any `StrategyDef`/`STRATEGY_BY_KEY`, and does not set
`horizon_hours` at all -- it will fall through to this batch's `168`
default once the field lands, which is the correct backward-compat outcome
for unmodified code, but is NOT itself proof of S4 wiring. Whether/how
`_build_minimal_contract` (or a future draft-builder) should consume a
`StrategyDef.horizon_hours`-equivalent is out of scope for this batch per
the mission's explicit "do NOT invent wiring tests against nonexistent
code paths" instruction -- flagged for T-MTF-4/cadence scope, not
improvised here.
"""

from __future__ import annotations

from tradekit.contracts import ThesisContract


def test_thesis_contract_horizon_hours_defaults_to_168_on_direct_construction(
    make_thesis,
) -> None:
    """CONTRACT: constructing `ThesisContract` with no `horizon_hours`
    kwarg (every pre-this-batch producer call site, e.g. `make_thesis()`'s
    own fixture kwargs, which carries no such key) must succeed and yield
    `168` -- the pinned default (168h == today's unchanged 7d behavior)."""
    thesis = make_thesis()
    assert thesis.horizon_hours == 168


def test_thesis_contract_from_pre_batch_serialized_dict_validates_default_168(
    thesis_kwargs,
) -> None:
    """AC-1-style (SPEC-inkind-fees precedent): a raw kwargs dict shaped
    like a thesis captured BEFORE this batch (no `horizon_hours` key at
    all -- `thesis_kwargs`'s own fixture shape) must still validate through
    `ThesisContract.model_validate`, and the missing field must resolve to
    `168`, never a validation error."""
    assert "horizon_hours" not in thesis_kwargs  # sanity: genuinely pre-batch shaped
    reconstructed = ThesisContract.model_validate(thesis_kwargs)
    assert reconstructed.horizon_hours == 168


def test_thesis_contract_accepts_explicit_horizon_hours_48_for_s4(make_thesis) -> None:
    """CONTRACT: a producer MAY set `horizon_hours` explicitly (S4's 48h
    time-stop) and it round-trips through the model unchanged -- the field
    is a real int, not silently coerced to the default."""
    thesis = make_thesis(horizon_hours=48)
    assert thesis.horizon_hours == 48


def test_thesis_contract_horizon_hours_is_independent_of_horizon_end(make_thesis) -> None:
    """CONTRACT: `horizon_hours` and `horizon_end` are separate fields
    (the dispatch pins `horizon_end` as the existing grading hard-stop
    datetime, `horizon_hours` as a new, separately-set int) -- setting one
    must not silently derive or overwrite the other. Guards against a
    GREEN implementation that collapses them into a single computed
    property instead of two independently-settable fields."""
    from datetime import UTC, datetime

    explicit_horizon_end = datetime(2099, 1, 1, tzinfo=UTC)
    thesis = make_thesis(horizon_hours=48, horizon_end=explicit_horizon_end)
    assert thesis.horizon_hours == 48
    assert thesis.horizon_end == explicit_horizon_end
