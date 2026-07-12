"""Model bases (DESIGN §5): frozen everywhere — no in-place mutation ever.

Amendments happen via ``model_copy(update=...)`` producing a superseding
version; a mutable contract breaks replay determinism (TD-4).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    """Base for every cross-boundary payload."""

    model_config = ConfigDict(frozen=True)


class StrictFrozenModel(FrozenModel):
    """Frozen + ``extra="forbid"`` — for discriminated-union variants.

    ``extra="forbid"`` is load-bearing: it is how ``time_expiry`` rejects a
    stray ``cmp``/``value`` and how a typo'd field dies at authoring time
    instead of being silently ignored by the grader (ASSUMPTIONS 5).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
