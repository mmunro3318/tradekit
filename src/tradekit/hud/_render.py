"""HTML templating for the advisory HUD (SPEC-hud-orderbook T2).

Pure templating: every rendered number is ``str()`` of the Decimal read
straight off ``HudState`` — never recomputed, never routed through float.
Layout mirrors the Kraken OSO bracket ticket transcription (docs/handoff/
HANDOFF-2026-07-20-hud-commit.md §elements 1-16), recolored per the DESIGN
Decision-2 palette. One self-contained HTML document — no external
resources, no JS beyond CSS-only radio-driven tab switching.
"""

from __future__ import annotations

import html as _html

from tradekit.contracts import AdvisoryTicket, HudState, ScanReportEntry

_CSS = """
:root {
  --bg: #121212;
  --panel: #1d1d1f;
  --field: #2a2a2c;
  --text: #e8e6e3;
  --muted: #9a948d;
  --accent: #c1581f;
  --accent-deep: #8a3b12;
  --buy: #c1581f;
  --sell: #7d2e2e;
  --warn: #d9a441;
}
* { box-sizing: border-box; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, sans-serif;
  margin: 0;
  padding: 1.5rem;
}
h1, h2 { color: var(--text); }
.panel {
  background: var(--panel);
  border: 1px solid var(--accent-deep);
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1.5rem;
}
.field-row {
  display: flex;
  justify-content: space-between;
  background: var(--field);
  border: 1px solid var(--accent-deep);
  border-radius: 4px;
  padding: 0.4rem 0.6rem;
  margin: 0.3rem 0;
}
.field-label { color: var(--muted); }
.field-value { color: var(--text); font-weight: 600; }
.tabs { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-bottom: 0.5rem; }
.tabs label {
  padding: 0.4rem 0.8rem;
  background: var(--field);
  border: 1px solid var(--accent-deep);
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  color: var(--muted);
}
input.tab-radio { display: none; }
.tab-panel { display: none; }
.buy-side { color: var(--buy); }
.sell-side { color: var(--sell); }
.warn { color: var(--warn); }
button.primary-buy { background: var(--buy); color: var(--text); border: none; }
button.primary-sell { background: var(--sell); color: var(--text); border: none; }
table.report { width: 100%; border-collapse: collapse; }
table.report th, table.report td {
  border: 1px solid var(--accent-deep);
  padding: 0.3rem 0.5rem;
  text-align: left;
}
"""


def _esc(value: object) -> str:
    return _html.escape(str(value))


def _tab_css_for(index: int) -> str:
    """CSS-only radio-driven tab switching: the nth radio's :checked state
    shows the nth panel. Generated per-ticket since panel count is dynamic."""
    return (
        f"#tab-{index}:checked ~ .tab-panels .tab-panel:nth-of-type({index + 1}) "
        "{ display: block; }"
    )


def _ticket_panel(ticket: AdvisoryTicket) -> str:
    side_class = "buy-side" if ticket.side == "buy" else "sell-side"
    btn_class = "primary-buy" if ticket.side == "buy" else "primary-sell"
    warnings_html = (
        "".join(f'<div class="warn">{_esc(w)}</div>' for w in ticket.warnings)
        if ticket.warnings
        else '<div class="field-label">No warnings</div>'
    )
    return f"""
    <div class="tab-panel">
      <h2>{_esc(ticket.pair)}</h2>
      <div class="field-row"><span class="field-label">Side</span>
        <span class="field-value {side_class}">{_esc(ticket.side)}</span></div>
      <div class="field-row"><span class="field-label">Mode</span>
        <span class="field-value">{_esc(ticket.mode)}</span></div>
      <div class="field-row"><span class="field-label">Order type</span>
        <span class="field-value">{_esc(ticket.order_type)}</span></div>
      <div class="field-row"><span class="field-label">Limit price</span>
        <span class="field-value">{_esc(ticket.limit_price)}</span></div>
      <div class="field-row"><span class="field-label">Quantity</span>
        <span class="field-value">{_esc(ticket.quantity)}</span></div>
      <div class="field-row"><span class="field-label">Est. total</span>
        <span class="field-value">{_esc(ticket.est_total_usd)}</span></div>
      <div class="field-row"><span class="field-label">Attach OSO</span>
        <span class="field-value">{_esc(ticket.oso)}</span></div>
      <div class="field-row"><span class="field-label">Take profit</span>
        <span class="field-value">{_esc(ticket.tp_price)}
        (+{_esc(ticket.tp_distance_pct)}%)</span></div>
      <div class="field-row"><span class="field-label">Stop loss</span>
        <span class="field-value">{_esc(ticket.sl_price)}
        ({_esc(ticket.sl_distance_pct)}%)</span></div>
      <div class="field-row"><span class="field-label">Est. P&L</span>
        <span class="field-value">{_esc(ticket.est_pnl_tp_usd)} /
        {_esc(ticket.est_pnl_sl_usd)}</span></div>
      <div class="field-row"><span class="field-label">Conditional trigger signal</span>
        <span class="field-value">{_esc(ticket.trigger_signal)}</span></div>
      <div class="field-row"><span class="field-label">Post only</span>
        <span class="field-value">{_esc(ticket.post_only)}</span></div>
      <div class="field-row"><span class="field-label">Time in force</span>
        <span class="field-value">{_esc(ticket.tif)}</span></div>
      <div class="field-row"><span class="field-label">Est. fee</span>
        <span class="field-value">{_esc(ticket.est_fee_usd)}</span></div>
      {warnings_html}
      <div class="field-row">
        <button type="button">Reset</button>
        <button type="button" class="{btn_class}">Review & Buy
        {_esc(ticket.pair.split("/")[0])}</button>
      </div>
      <div class="field-label">thesis {_esc(ticket.thesis_id)} ·
      verdict {_esc(ticket.verdict_id)}</div>
    </div>
    """


def _report_row(entry: ScanReportEntry) -> str:
    indicators_html = ", ".join(f"{_esc(name)}={_esc(value)}" for name, value in entry.indicators)
    gates_html = "".join(
        f"<li>{_esc(gate.name)}: {'PASS' if gate.passed else 'FAIL'} "
        f"(observed {_esc(gate.observed)} vs {_esc(gate.threshold)}) — {_esc(gate.rationale)}</li>"
        for gate in entry.gates
    )
    return f"""
    <tr>
      <td>{_esc(entry.symbol)}</td>
      <td>{_esc(entry.timeframe)}</td>
      <td>{indicators_html}</td>
      <td><ul>{gates_html}</ul></td>
      <td>{_esc(entry.grade)}</td>
      <td>{_esc(entry.grade_rationale)}</td>
    </tr>
    """


def render(state: HudState) -> str:
    """Render one self-contained HTML document: a tabbed advisory ticket
    book (one tab per pending ticket) followed by the per-asset scan
    report. Templating only — no derived arithmetic happens here."""
    tab_css = "\n".join(_tab_css_for(i) for i in range(len(state.tickets)))

    if state.tickets:
        radios = "".join(
            f'<input type="radio" name="ticket-tab" id="tab-{i}" class="tab-radio"'
            f'{" checked" if i == 0 else ""}>'
            for i in range(len(state.tickets))
        )
        tab_labels = "".join(
            f'<label for="tab-{i}">{_esc(ticket.pair)}</label>'
            for i, ticket in enumerate(state.tickets)
        )
        tab_panels = "".join(_ticket_panel(ticket) for ticket in state.tickets)
        tickets_html = f"""
        {radios}
        <div class="tabs">{tab_labels}</div>
        <div class="tab-panels">{tab_panels}</div>
        """
    else:
        tickets_html = '<p class="field-label">no advisory tickets</p>'

    report_rows = "".join(_report_row(entry) for entry in state.report)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>TradeKit HUD</title>
<style>{_CSS}
{tab_css}
</style>
</head>
<body>
<h1>Advisory order book</h1>
<div class="panel">
{tickets_html}
</div>
<h1>Scan report</h1>
<div class="panel">
<table class="report">
<thead>
<tr><th>Symbol</th><th>Timeframe</th><th>Indicators</th><th>Gates</th><th>Grade</th><th>Rationale</th></tr>
</thead>
<tbody>
{report_rows}
</tbody>
</table>
</div>
<p>Generated at {_esc(state.generated_at)}</p>
</body>
</html>
"""


__all__ = ["render"]
