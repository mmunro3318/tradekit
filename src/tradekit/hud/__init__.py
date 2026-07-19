"""tradekit.hud — advisory-only order-book HUD (SPEC-hud-orderbook).

Renders a tabbed OSO-bracket ticket book plus a per-asset scan report as a
single static HTML file. Advisory only: nothing in this package clicks,
types, submits, or otherwise talks to any venue or UI — Mike transcribes
tickets manually into Kraken Desktop; fills come back via
`broker.record_manual_fill` (existing path).
"""

from __future__ import annotations

from tradekit.hud._build import build_state
from tradekit.hud._render import render

__all__ = ["build_state", "render"]
