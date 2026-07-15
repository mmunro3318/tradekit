"""Structure indicators (SPRINT P1B story 5): swing_points, qfl_bases. Pure
functions over `Sequence[float]` highs/lows/closes.

Contract (uniform, non-negotiable — sprint doc): output is aligned 1:1 with
input; positions with insufficient lookback/confirmation are `None`, never
zero-filled, never a shorter array. Both functions here are LAGGING /
CONFIRMATION-based (fractal pivots need `k` bars on both sides before a
level can be confirmed) — see each docstring's no-lookahead note.

STUB (SPRINT P1B stories 4-5 TDD session, red phase): bodies raise
NotImplementedError. Signatures, docstrings, and lookback conventions below
are pinned by docs/handoff/SPRINT-P1B-indicators.md's addendum and are NOT
to be improvised during implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple


class SwingPoints(NamedTuple):
    """(swing_highs, swing_lows) — both `list[float | None]`, aligned to
    input. A non-None value at index i is the swing level itself (the
    high or low price at the confirmed pivot), not a boolean flag."""

    swing_highs: list[float | None]
    swing_lows: list[float | None]


def swing_points(
    highs: Sequence[float], lows: Sequence[float], k: int = 2
) -> SwingPoints:
    """Fractal swing-high / swing-low pivots, aligned 1:1 with input.

    A swing HIGH level is reported AT pivot index i (swing_highs[i] =
    highs[i]) iff highs[i] is STRICTLY GREATER than every one of
    highs[i-k], ..., highs[i-1], highs[i+1], ..., highs[i+k] (all 2k
    neighbors on both sides, k on each side). A swing LOW level is reported
    AT pivot index i (swing_lows[i] = lows[i]) iff lows[i] is STRICTLY LESS
    than every one of lows[i-k], ..., lows[i-1], lows[i+1], ..., lows[i+k].
    Ties (an equal neighbor) DISQUALIFY the candidate index — strict
    inequality against ALL 2k neighbors is required, not just a local
    plateau.

    Edge exclusion: any index within `k` bars of either end of the series
    (i < k or i > n-1-k) can NEVER be a pivot — there are not enough
    neighbors on one side to evaluate the strict-inequality condition, so
    those positions are always None regardless of price shape.

    NO LOOKAHEAD / confirmation lag: a pivot at index i cannot be known to
    be a pivot until index i+k has been observed (you need the k bars AFTER
    i to confirm nothing in that window beats it). A caller consuming this
    series in real time must NOT use swing_highs[i]/swing_lows[i] before
    bar i+k has closed — the value is reported AT index i for indexing
    convenience, but knowledge of it lags by k bars. `qfl_bases` below
    enforces this explicitly via its own confirmation-index check.

    Lookback: for a series of length n, only indices k..n-1-k can ever be
    non-None; a series shorter than 2k+1 bars has NO possible pivots (every
    index is within k of one end or the other) and both outputs are all
    None.
    """
    raise NotImplementedError


def qfl_bases(
    lows: Sequence[float], closes: Sequence[float], k: int = 2
) -> list[float | None]:
    """QFL ("Quantitative Fundamental/Flag Levels" per the canonical MAE
    doc) base level, aligned 1:1 with `lows`/`closes`. Simplest correct
    version — bounce-magnitude and volume filters are explicitly TODO-P5,
    NOT implemented here.

    A "base" is a confirmed swing-low level (see `swing_points` above, same
    `k`, applied to `lows`). At each index i, qfl_bases[i] reports the
    LEVEL (price, a float) of the most recent swing-low whose pivot has
    already been CONFIRMED by index i — i.e. pivot_index + k <= i (the
    confirmation-lag rule from `swing_points`, enforced here explicitly: a
    swing low at pivot index p is not eligible to be reported as a base
    until index p+k) — AND that has not yet been "cracked".

    Crack rule: a base at level L becomes cracked (and is dropped) the
    first time close[i] < L (STRICT). Once cracked, qfl_bases reports None
    at that base's level until a LATER swing-low confirms a new base
    (i.e. cracking does not fall back to an older, earlier base — the slate
    is wiped until the next confirmation).

    Boundary pin (addendum, explicit): on the bar where close[i] FIRST
    drops below the active base's level, qfl_bases[i] is ALREADY None, not
    the about-to-be-cracked level — the crack condition is evaluated for
    index i BEFORE reporting index i's value, so the crack and the None
    output happen on the SAME bar (no one-bar lag on the crack side, unlike
    the k-bar confirmation lag on the base-formation side).

    No base has been confirmed yet at any index before the first swing-low
    pivot's confirmation index (p+k, where p is the first swing-low's pivot
    index) -> qfl_bases is None for all of those leading indices, same as
    `swing_points`'s own edge/lookback exclusion.
    """
    raise NotImplementedError
