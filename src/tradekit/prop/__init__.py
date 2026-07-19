"""tradekit.prop — prop-account evaluation machinery (SPRINT P5-PROP).

Deep module, one verb surface (sprint §1b): `simulate_evaluation`. Specs and
results are `tradekit.contracts` payloads (PropSimSpec / PropSimResult and
the trade-model union) — this package owns behavior, not contracts.
"""

from tradekit.prop._sim import simulate_evaluation

__all__ = ["simulate_evaluation"]
