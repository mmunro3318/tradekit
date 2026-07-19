"""Prop evaluation barrier simulator — engine (SPRINT P5-PROP §1b).

RED-phase stub (batch A): contracts are real (`tradekit.contracts._prop`);
the engine lands in the green pass against the pinned goldens in
`tests/unit/prop/`. Semantics pins: ASSUMPTIONS round-26 (entries 143-151).
"""

from __future__ import annotations

from tradekit.contracts import PropSimResult, PropSimSpec


def simulate_evaluation(spec: PropSimSpec, *, seed: int) -> PropSimResult:
    """Monte Carlo (or scripted single-path replay) of one prop evaluation
    against the absorbing MDL/MDD/target barriers. Deterministic for a
    given (spec, seed) — no wall clock, no global RNG."""
    raise NotImplementedError("batch A green pass implements this (RED stub)")


__all__ = ["simulate_evaluation"]
