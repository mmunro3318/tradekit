"""`broker._tokens` -- the SHARED `VerdictToken` verifier every `BrokerPort`
adapter's `submit()` runs through (SPRINT P4-PAPER batch A, addendum 2,
"Token verification").

Extraction provenance: `verify_token` below is `PaperBroker._verify_token`'s
algorithm (SPRINT P3 batch B/C hardening -- existence + allow + hash, thesis
binding MED-2a, no-newer-deny MED-2b) moved here VERBATIM, so `PaperBroker`
AND `AlpacaBroker` (and any future adapter) import and run the SAME function
object -- a second hand-rolled copy inside `_alpaca.py` would be exactly the
"no string-shape property separates a registered token from an unregistered
one" dishonesty the original conformance suite caught (`_paper.py`'s own
module docstring), just duplicated instead of prevented. `_paper.py`
re-points `PaperBroker._verify_token` to call this module; its own test
suite (`tests/unit/broker/test_paper_fills.py`) must stay green unchanged
(mechanical extraction, no behavior change for PaperBroker EXCEPT the one
deliberate addition below).

PLUS the submit-time halt seam (addendum 2, NEW behavior this batch,
deliberately RED against PaperBroker's prior behavior): `verify_token` now
ALSO refuses -- `BrokerTokenRequired`, reason `"halted"` -- when this
ledger carries an unresolved `HaltSet` (no later `HaltCleared`). Before this
batch, `PaperBroker.submit` never checked halt state at all (only
`order_status`'s resting-limit poll did, MED-1, P3 review); a `HaltSet`
landing between `VerdictIssued` and `adapter.submit` could still slip a
market order through submit's synchronous fill path. Checked FIRST, before
even the missing/None-token check -- a halted ledger refuses EVERY submit,
token or no token, so the refusal reason is always legible as "the account
is halted", never masked by a token-shape complaint that happens to also be
true.

`is_halted` is the SAME derivation `policy._context._halt_state` and
`_paper.py`'s (former) private `_is_halted` used -- folds every `HaltSet`/
`HaltCleared` event, in ledger (append) order, into the current halt state
(last one wins). Canonical home now: `_paper.py`'s `order_status` halt guard
imports it from here rather than keeping its own copy (one derivation, not
two -- the prior duplication was accepted because `broker` avoiding a
dependency on `policy` mattered more than DRY across two MODULES; within
`broker` itself, DRY wins)."""

from __future__ import annotations

from tradekit.broker._port import BrokerTokenRequired
from tradekit.contracts import Event, EventFilter, VerdictToken
from tradekit.ledger import Ledger


def is_halted(ledger: Ledger) -> bool:
    """Fold every `HaltSet`/`HaltCleared` event, in ledger (append) order,
    into the CURRENT halt state (last one wins) -- see module docstring."""
    halted = False
    for event in ledger.query(EventFilter(types=["HaltSet", "HaltCleared"])):
        halted = event.type == "HaltSet"
    return halted


def verify_token(
    ledger: Ledger,
    verdict: VerdictToken | None,
    thesis_id: str | None,
    *,
    caller_repr: str,
) -> None:
    """Validate `verdict` against `ledger` on behalf of `caller_repr.submit(
    ...)` (e.g. `"PaperBroker('paper:alpha')"`, `"AlpacaBroker('alpaca-
    paper:main')"` -- used only to build legible refusal messages, never for
    control flow). Raises `BrokerTokenRequired` -- the ONE refusal type every
    adapter's `submit` raises -- for ANY of:

    0. Halted (addendum 2, NEW): an unresolved `HaltSet` exists on this
       ledger. Checked FIRST -- see module docstring.
    1. Missing/`None` verdict.
    2. Existence + allow + hash: no `VerdictIssued` event on `ledger` whose
       payload `verdict_id == verdict.verdict_id` AND `allow` is true AND
       `policy_version_hash` matches `verdict.policy_version_hash`.
    3. Thesis binding (MED-2a): that matched `VerdictIssued`'s own
       `thesis_id` must equal `thesis_id` (the order's own) -- a token
       minted for thesis A can never authorize an order for thesis B. A
       `VerdictIssued` with `thesis_id=None` only matches an order whose own
       `thesis_id` is also falsy.
    4. No newer deny (MED-2b): no OTHER `VerdictIssued` for the SAME
       `thesis_id`, at a STRICTLY LATER `ts_utc` than the matched allow
       event, has `allow` false. A later ALLOW does not invalidate the
       token -- only a later DENY does.
    """
    if is_halted(ledger):
        raise BrokerTokenRequired(
            f"{caller_repr}.submit(...): refusing -- an unresolved HaltSet exists on this "
            "ledger (reason=\"halted\"); a halt landing between VerdictIssued and submit "
            "blocks at every adapter now (addendum 2, submit-time halt seam)"
        )

    if verdict is None:
        raise BrokerTokenRequired(
            f"{caller_repr}.submit(...): no VerdictToken supplied (§8.2/§15 -- an order "
            "without a preceding allow-verdict is structurally impossible)"
        )

    saw_verdict_id = False
    matched_event: Event | None = None
    for event in ledger.query(EventFilter(types=["VerdictIssued"])):
        payload = event.payload
        if payload.get("verdict_id") != verdict.verdict_id:
            continue
        saw_verdict_id = True
        if (
            payload.get("allow") is True
            and payload.get("policy_version_hash") == verdict.policy_version_hash
        ):
            matched_event = event
            break
    if matched_event is None:
        if saw_verdict_id:
            raise BrokerTokenRequired(
                f"{caller_repr}.submit(...): VerdictIssued verdict_id={verdict.verdict_id!r} "
                "exists but is not a matching allow (deny verdict or policy_version_hash "
                "mismatch)"
            )
        raise BrokerTokenRequired(
            f"{caller_repr}.submit(...): no VerdictIssued event on the ledger for "
            f"verdict_id={verdict.verdict_id!r} -- token does not reference a real "
            "allow-verdict (§8.2/§15)"
        )

    verdict_thesis_id = matched_event.payload.get("thesis_id")
    if verdict_thesis_id != thesis_id:
        raise BrokerTokenRequired(
            f"{caller_repr}.submit(...): VerdictIssued verdict_id={verdict.verdict_id!r} "
            f"references thesis_id={verdict_thesis_id!r} but the submitted order is for "
            f"thesis_id={thesis_id!r} -- a token cannot authorize a different thesis "
            "(§8.2/§15 thesis binding, MED-2)"
        )

    matched_ts = matched_event.ts_utc
    for event in ledger.query(EventFilter(types=["VerdictIssued"])):
        payload = event.payload
        if payload.get("thesis_id") != thesis_id:
            continue
        if payload.get("allow") is False and event.ts_utc > matched_ts:
            raise BrokerTokenRequired(
                f"{caller_repr}.submit(...): a LATER VerdictIssued (allow=False) exists for "
                f"thesis_id={thesis_id!r} after the presented allow verdict_id="
                f"{verdict.verdict_id!r} -- the allow has been superseded by a deny (§8.2/§15 "
                "no-newer-deny, MED-2)"
            )


__all__ = ["is_halted", "verify_token"]
