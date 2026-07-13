"""Hash-chain rules (DESIGN §6.2): the preimage covers prev_hash + EVERY other
column — nothing is editable outside the chain (G-review fix)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Genesis prev_hash: 64 zeros — same width as a sha256 hex digest, cannot
# collide with one in practice, and unambiguous in raw-SQL inspection.
GENESIS_HASH = "0" * 64


def canonical_json(payload: dict[str, Any]) -> str:
    """Canonical JSON (sorted keys, no whitespace, RFC-8785 style, §6.2).

    No ``default=`` fallback: a non-JSON-native value (Decimal, datetime, ...)
    raises TypeError at append instead of being silently coerced to a string
    that differs from what the producer holds in memory (reviewer D4,
    ASSUMPTIONS 10/21).
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _lp(field: str | None) -> str:
    """Length-prefix a preimage field: '<len>:<value>', None -> 'N'.

    Length-prefixing makes field boundaries unforgeable regardless of field
    content — no delimiter can be smuggled inside a value to shift bytes
    between adjacent fields — and None is distinct from "" (reviewer D3).
    """
    return "N" if field is None else f"{len(field)}:{field}"


def event_hash(
    prev_hash: str,
    event_id: str,
    ts_utc: str,
    type_: str,
    actor: str,
    run_id: str | None,
    schema_ver: int,
    payload_json: str,
) -> str:
    """sha256 over prev_hash ‖ all other columns, in DDL column order."""
    preimage = "|".join(
        (
            _lp(prev_hash),
            _lp(event_id),
            _lp(ts_utc),
            _lp(type_),
            _lp(actor),
            _lp(run_id),
            _lp(str(schema_ver)),
            _lp(payload_json),
        )
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()
