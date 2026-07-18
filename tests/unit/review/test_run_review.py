"""`review.run_review(thesis_id) -> dict` (DESIGN §12.1, TD-21, SPRINT P3
batch D). `tradekit.review.run_review` is an unconditional
`NotImplementedError` stub this batch (dev pass lands the real pipeline
`review/__init__.py`'s own docstring pins step-by-step) -- every test below
describes REAL target behavior and is red for that reason alone, never
wrapped in `pytest.raises(NotImplementedError)` (same discipline as every
other red-phase file this sprint, e.g. `test_void_verb.py`,
`test_pipeline.py`'s original batch-C red pass).

Auto-fail short-circuits (sprint doc addendum, binding): "AUTO-FAIL
SHORT-CIRCUITS FIRST ... before any adapter call, zero tokens spent" -- the
fake adapter below RECORDS every call it receives so each auto-fail test
can assert on an EMPTY call list, not just on the returned verdict.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from tradekit import review
from tradekit.contracts import EventFilter
from tradekit.ledger import default_ledger


class _RecordingFakeAdapter:
    """In-process `LLMReviewerPort` fake (never a real subprocess) --
    canned JSON responses per call, in order; records every prompt it was
    asked to review so auto-fail tests can assert ZERO adapter calls."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def review(self, prompt: str, *, timeout_s: int, max_output_bytes: int) -> str:
        self.calls.append(
            {"prompt": prompt, "timeout_s": timeout_s, "max_output_bytes": max_output_bytes}
        )
        return self._responses.pop(0)


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, adapter: _RecordingFakeAdapter) -> None:
    # Module-attribute seam (house convention): `review/__init__.py`'s own
    # docstring pins `run_review` to resolve its adapter via
    # `_adapters.SubprocessReviewerAdapter.from_dials()` -- patch THAT
    # classmethod so the real pipeline (once it lands) reaches the fake
    # without ever touching a real subprocess.
    monkeypatch.setattr(
        "tradekit.review._adapters.SubprocessReviewerAdapter.from_dials",
        classmethod(lambda cls, dials=None: adapter),
    )


_ALL_RESOLVED_EXCHANGE = [
    {
        "attack": "p_win=0.55 with no base-rate citation.",
        "category": "ev_arithmetic",
        "severity": 2,
        "defense": "Base rate drawn from the strategy_tag's last 40 trades (wiki-cited).",
        "resolved": True,
    }
]

_ONE_UNRESOLVED_FATAL_EXCHANGE = [
    {
        "attack": "Your structural invalidation is just the stop restated in prose.",
        "category": "invalidation_distinctness",
        "severity": 5,
        "defense": "It references delisting risk, not price.",
        "resolved": False,
    }
]


def test_auto_fail_nonpositive_ev_short_circuits_with_zero_adapter_calls(
    seed_submitted_thesis, monkeypatch
) -> None:
    thesis_id = seed_submitted_thesis(ev_usd=Decimal("0"))
    adapter = _RecordingFakeAdapter([])
    _patch_adapter(monkeypatch, adapter)

    artifact = review.run_review(thesis_id)

    assert artifact["passed"] is False
    assert artifact["auto_fail_reason"] is not None
    assert artifact["failure_mode"] is None, "an auto-fail is a verdict, not a boundary failure"
    assert artifact["exchanges"] == []
    assert adapter.calls == [], "auto-fail must short-circuit BEFORE any adapter call (zero tokens)"


def test_auto_fail_no_falsifiable_success_criteria_short_circuits_with_zero_adapter_calls(
    seed_submitted_thesis, monkeypatch
) -> None:
    thesis_id = seed_submitted_thesis(success_criteria=[])
    adapter = _RecordingFakeAdapter([])
    _patch_adapter(monkeypatch, adapter)

    artifact = review.run_review(thesis_id)

    assert artifact["passed"] is False
    assert artifact["auto_fail_reason"] is not None
    assert adapter.calls == []


def test_auto_fail_size_mismatch_vs_sizing_computed_short_circuits_with_zero_adapter_calls(
    seed_submitted_thesis, monkeypatch
) -> None:
    thesis_id = seed_submitted_thesis(
        size_usd=Decimal("25.00"),
        recommended_size_usd=Decimal("40.00"),
    )
    adapter = _RecordingFakeAdapter([])
    _patch_adapter(monkeypatch, adapter)

    artifact = review.run_review(thesis_id)

    assert artifact["passed"] is False
    assert artifact["auto_fail_reason"] is not None
    assert adapter.calls == []


def test_happy_path_attack_defense_all_resolved_passes_and_emits_review_completed(
    seed_submitted_thesis, monkeypatch
) -> None:
    thesis_id = seed_submitted_thesis()
    adapter = _RecordingFakeAdapter([json.dumps(_ALL_RESOLVED_EXCHANGE)])
    _patch_adapter(monkeypatch, adapter)

    artifact = review.run_review(thesis_id)

    assert artifact["passed"] is True
    assert artifact["kind"] == "thesis_review"
    assert artifact["failure_mode"] is None
    assert artifact["auto_fail_reason"] is None
    assert artifact["unresolved_attack_count"] == 0
    assert len(adapter.calls) == 1, "a normal review makes exactly one adapter call this MVP"

    completed = [
        e
        for e in default_ledger().query(EventFilter(types=["ReviewCompleted"]))
        if e.payload.get("thesis_id") == thesis_id
    ]
    assert len(completed) == 1
    assert completed[0].payload["passed"] is True
    assert completed[0].payload["review_artifact_id"] == artifact["review_artifact_id"]
    assert completed[0].payload["kind"] == "thesis_review"


def test_unresolved_attack_at_or_above_threshold_fails_review(
    seed_submitted_thesis, monkeypatch
) -> None:
    thesis_id = seed_submitted_thesis()
    adapter = _RecordingFakeAdapter([json.dumps(_ONE_UNRESOLVED_FATAL_EXCHANGE)])
    _patch_adapter(monkeypatch, adapter)

    artifact = review.run_review(thesis_id)

    assert artifact["passed"] is False
    assert artifact["failure_mode"] is None, "a rubric-driven fail is not a boundary failure"
    assert artifact["unresolved_attack_count"] >= 1

    completed = [
        e
        for e in default_ledger().query(EventFilter(types=["ReviewCompleted"]))
        if e.payload.get("thesis_id") == thesis_id
    ]
    assert len(completed) == 1
    assert completed[0].payload["passed"] is False
