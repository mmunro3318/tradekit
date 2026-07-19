"""`tk hud --serve` — localhost HTTP loop + the confirm/failed reverse
channel (SPEC-hud-ack.md).

GET / regenerates and serves the HUD fresh per request. POST /ack is the
Confirm/Failed reverse channel: **confirm is the binding moment** — the
handler runs the real transactional chain (thesis.draft -> submit ->
[human-confirm-as-review] -> approve -> a fresh policy.evaluate) through
existing public verbs only, then appends `AdvisoryTicketAcked`. Failed
appends only the ack event; thesis/verdict stay untouched.

Two sanctioned test seams (ASSUMPTIONS 160b): `_make_server(*, host, port,
equity_usd)` (ephemeral-port testing — `serve()` is a thin wrapper around
it) and `evaluate_policy_binding` (the confirm-time policy call; default is
the real `policy.evaluate`, mirroring `hud._build`'s own seam-with-real-
default convention).
"""

from __future__ import annotations

import http.server
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from ulid import ULID

from tradekit.contracts import (
    AdvisoryTicketAckedPayload,
    AssetRef,
    Event,
    OrderRequest,
    ProposedAction,
    ReviewCompletedPayload,
)
from tradekit.ledger import Ledger, default_ledger
from tradekit.mae import _runtime as _mae_runtime

# 'agent:<model>' | 'mike' | 'system:<job>' — every event this module
# produces is the direct consequence of Mike's own Confirm/Failed click.
_ACTOR = "mike"

_REVIEW_ARTIFACT_ID = "human confirm via hud-ack"  # ASSUMPTIONS 160a

_REQUIRED_TICKET_FIELDS = ("pair", "side", "limit_price", "quantity", "tp_price", "sl_price")


@dataclass(frozen=True)
class _PolicyBindingDecision:
    allowed: bool
    verdict_id: str | None
    rationale: str


def _default_evaluate_policy_binding(action: ProposedAction) -> _PolicyBindingDecision:
    """Real confirm-time policy evaluation (ASSUMPTIONS 160b default)."""
    from tradekit import policy as policy_mod

    verdict = policy_mod.evaluate(action)
    if verdict.allow:
        return _PolicyBindingDecision(
            allowed=True, verdict_id=verdict.verdict_id, rationale="allow"
        )
    failing = [hit for hit in verdict.rule_hits if hit.outcome == "fail"]
    rationale = "; ".join(f"{hit.rule_id}: {hit.measured} vs {hit.limit}" for hit in failing)
    return _PolicyBindingDecision(
        allowed=False, verdict_id=None, rationale=rationale or "policy denied action"
    )


# Test seam (ASSUMPTIONS 160b). Production code calls this via the module's
# own namespace so a monkeypatch on `_serve.evaluate_policy_binding` takes
# effect regardless of when in the test it is applied.
evaluate_policy_binding = _default_evaluate_policy_binding


def _append_event(ledger: Ledger, event_type: str, payload: dict[str, Any]) -> None:
    event = Event(
        event_id=str(ULID()),
        ts_utc=_mae_runtime.clock(),
        type=event_type,  # type: ignore[arg-type]  # narrowed by callers below
        actor=_ACTOR,
        run_id=None,
        schema_ver=1,
        payload=payload,
    )
    ledger.append(event)


def _append_ack(
    ledger: Ledger,
    *,
    verdict_preview_id: str,
    action: str,
    thesis_id: str | None,
    verdict_id: str | None,
    ticket: dict[str, Any],
) -> None:
    payload = AdvisoryTicketAckedPayload(
        verdict_preview_id=verdict_preview_id,
        action=action,  # type: ignore[arg-type]  # already validated by _parse_ack_body
        thesis_id=thesis_id,
        verdict_id=verdict_id,
        pair=ticket["pair"],
        side=ticket["side"],
        limit_price=Decimal(str(ticket["limit_price"])),
        quantity=Decimal(str(ticket["quantity"])),
        acked_at=_mae_runtime.clock(),
    )
    _append_event(ledger, "AdvisoryTicketAcked", payload.model_dump(mode="json"))


def _parse_ack_body(body: Any) -> tuple[str, str, dict[str, Any]]:
    """Validates the pinned POST /ack shape; raises on anything malformed
    (caught by the handler, which turns every such raise into a 400 with no
    ledger write)."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    verdict_preview_id = body["verdict_preview_id"]
    if not isinstance(verdict_preview_id, str):
        raise ValueError("verdict_preview_id must be a string")
    action = body["action"]
    if action not in ("confirmed", "failed"):
        raise ValueError(f"invalid action: {action!r}")
    ticket = body["ticket"]
    if not isinstance(ticket, dict):
        raise ValueError("ticket must be a JSON object")
    for field in _REQUIRED_TICKET_FIELDS:
        if field not in ticket:
            raise ValueError(f"missing ticket field: {field}")
    if ticket["side"] not in ("buy", "sell"):
        raise ValueError(f"invalid side: {ticket['side']!r}")
    # Force-parse the Decimal fields now so a garbage price/quantity 400s
    # here rather than crashing later mid-chain.
    Decimal(str(ticket["limit_price"]))
    Decimal(str(ticket["quantity"]))
    Decimal(str(ticket["tp_price"]))
    Decimal(str(ticket["sl_price"]))
    return verdict_preview_id, action, ticket


def _build_minimal_contract(ticket: dict[str, Any]) -> dict[str, Any]:
    """The smallest honest `ThesisContract` kwargs derivable from a ticket
    snapshot (SPEC-hud-ack.md "Unknowns"): every price/EV field is derived
    from the ticket itself (no invented numbers), `p_win=0.5` is the one
    free choice (a genuine market view is not knowable from a bracket
    alone), which makes `ev_usd` exactly reproduce `submit()`'s own EV
    recompute (SME F5 tolerance trivially satisfied)."""
    pair = ticket["pair"]
    side = ticket["side"]
    limit_price = Decimal(str(ticket["limit_price"]))
    quantity = Decimal(str(ticket["quantity"]))
    tp_price = Decimal(str(ticket["tp_price"]))
    sl_price = Decimal(str(ticket["sl_price"]))
    is_crypto = "/" in pair
    now = _mae_runtime.clock()
    horizon_end = now + timedelta(days=7)

    from tradekit.policy._dials import PolicyDials

    account_ref = PolicyDials.load().default_account_ref

    if side == "buy":
        reward_usd = quantity * (tp_price - limit_price)
        risk_usd = quantity * (limit_price - sl_price)
    else:
        reward_usd = quantity * (limit_price - tp_price)
        risk_usd = quantity * (sl_price - limit_price)
    p_win = Decimal("0.5")
    ev_usd = p_win * reward_usd - (Decimal("1") - p_win) * risk_usd

    return {
        "thesis_id": str(ULID()),
        "account_ref": account_ref,
        "asset": {
            "symbol": pair,
            "venue": "kraken" if is_crypto else "alpaca",
            "asset_class": "crypto" if is_crypto else "equity",
            "tick_size": "0.00001" if is_crypto else "0.01",
        },
        "direction": "long" if side == "buy" else "short",
        "strategy_tag": "hud-ack-manual",
        "rationale": "Mike confirmed this advisory ticket via the hud-ack panel.",
        "entry": {
            "order_type": "limit",
            "limit_price": str(limit_price),
            "valid_until": (now + timedelta(hours=1)).isoformat(),
        },
        "horizon_end": horizon_end.isoformat(),
        "target_price": str(tp_price),
        "stop_price": str(sl_price),
        "invalidation": {
            "kind": "structural",
            "description": "manual advisory confirm via hud-ack; no automated structural check",
        },
        "size_usd": str(limit_price * quantity),
        "sizing_method": "min_atr_kelly",
        "ev_block": {
            "p_win": str(p_win),
            "reward_usd": str(reward_usd),
            "risk_usd": str(risk_usd),
            "ev_usd": str(ev_usd),
        },
        "success_criteria": [
            {
                "kind": "price_touch",
                "cmp": "gte" if side == "buy" else "lte",
                "value": str(tp_price),
                "timeframe": "1h",
                "by": horizon_end.isoformat(),
            }
        ],
        "failure_criteria": [
            {
                "kind": "price_close",
                "cmp": "lte" if side == "buy" else "gte",
                "value": str(sl_price),
                "timeframe": "1h",
                "by": horizon_end.isoformat(),
            }
        ],
        "market_snapshot_id": str(ULID()),
        "review_artifact_id": None,
    }


def _confirm_chain(ledger: Ledger, ticket: dict[str, Any]) -> str:
    """draft -> submit -> [human confirm IS the review] -> approve, all
    through `tradekit.thesis`'s public verbs. Returns the real thesis_id."""
    from tradekit import thesis as thesis_mod

    contract = _build_minimal_contract(ticket)
    thesis_id: str = thesis_mod.draft(contract)
    thesis_mod.submit(thesis_id)

    review_payload = ReviewCompletedPayload(
        thesis_id=thesis_id,
        review_artifact_id=_REVIEW_ARTIFACT_ID,
        passed=True,
        kind="thesis_review",
    )
    _append_event(ledger, "ReviewCompleted", review_payload.model_dump(mode="json"))

    thesis_mod.approve(thesis_id)
    return thesis_id


def _make_binding_proposal(thesis_id: str, ticket: dict[str, Any]) -> ProposedAction:
    pair = ticket["pair"]
    is_crypto = "/" in pair

    from tradekit.policy._dials import PolicyDials

    account_ref = PolicyDials.load().default_account_ref
    asset = AssetRef(
        symbol=pair,
        venue="kraken" if is_crypto else "alpaca",
        asset_class="crypto" if is_crypto else "equity",
        tick_size=Decimal("0.00001") if is_crypto else Decimal("0.01"),
    )
    order = OrderRequest(
        thesis_id=thesis_id,
        account_ref=account_ref,
        asset=asset,
        side=ticket["side"],
        order_type="limit",
        qty=Decimal(str(ticket["quantity"])),
        limit_price=Decimal(str(ticket["limit_price"])),
    )
    return ProposedAction(
        kind="submit_order",
        account_ref=account_ref,
        requested_by="mike",
        thesis_id=thesis_id,
        order=order,
    )


def _make_handler_class(equity_usd: Decimal) -> type[http.server.BaseHTTPRequestHandler]:
    class _AckHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # quiet: the test harness doesn't want stderr noise per request

        def _respond(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path != "/":
                self._respond(404, b"not found")
                return
            from tradekit import hud  # lazy: avoids the hud/__init__ <-> _serve cycle

            state = hud.build_state(
                list(hud.DEFAULT_SYMBOLS), captured_at=_mae_runtime.clock(), equity_usd=equity_usd
            )
            body = hud.render(state).encode("utf-8")
            self._respond(200, body, content_type="text/html; charset=utf-8")

        def do_POST(self) -> None:
            if self.path != "/ack":
                self._respond(404, b"not found")
                return
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw)
                verdict_preview_id, action, ticket = _parse_ack_body(parsed)
            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
                InvalidOperation,
            ) as exc:
                self._respond(400, str(exc).encode("utf-8"))
                return

            ledger = default_ledger()
            if action == "failed":
                _append_ack(
                    ledger,
                    verdict_preview_id=verdict_preview_id,
                    action="failed",
                    thesis_id=None,
                    verdict_id=None,
                    ticket=ticket,
                )
                self._respond(204, b"")
                return

            thesis_id = _confirm_chain(ledger, ticket)
            proposal = _make_binding_proposal(thesis_id, ticket)
            decision = evaluate_policy_binding(proposal)
            if not decision.allowed:
                self._respond(409, decision.rationale.encode("utf-8"))
                return

            _append_ack(
                ledger,
                verdict_preview_id=verdict_preview_id,
                action="confirmed",
                thesis_id=thesis_id,
                verdict_id=decision.verdict_id,
                ticket=ticket,
            )
            self._respond(204, b"")

    return _AckHandler


def _make_server(*, host: str, port: int, equity_usd: Decimal) -> http.server.HTTPServer:
    """Test seam (ASSUMPTIONS 160b): construct-only, never blocks. `serve()`
    is a thin `.serve_forever()` wrapper around this."""
    handler_cls = _make_handler_class(equity_usd)
    return http.server.HTTPServer((host, port), handler_cls)


def serve(*, equity_usd: Decimal, host: str = "127.0.0.1", port: int = 7333) -> None:
    """Blocks serving the HUD + /ack reverse channel until Ctrl-C, which
    exits cleanly (AC-A7) rather than propagating `KeyboardInterrupt`."""
    server = _make_server(host=host, port=port, equity_usd=equity_usd)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["serve"]
