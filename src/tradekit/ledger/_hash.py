"""Hash-chain rules (DESIGN §6.2): the preimage covers prev_hash + EVERY other
column — nothing is editable outside the chain (G-review fix)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Genesis prev_hash: 64 zeros — same width as a sha256 hex digest, cannot
# collide with one in practice, and unambiguous in raw-SQL inspection.
GENESIS_HASH = "0" * 64

# ASCII unit separator. json.dumps escapes control characters (0x1f serializes
# as ) and the
# other fields are ULIDs / ISO timestamps / taxonomy strings, so the delimiter
# cannot be forged from inside a field value.
_DELIM = "\x1f"

# NULL run_id enters the preimage as "" — the DB keeps NULL, only the hash
# input uses the sentinel.
_NULL_RUN_ID = ""


def canonical_json(payload: dict[str, Any]) -> str:
    """Canonical JSON (sorted keys, no whitespace, RFC-8785 style, §6.2)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


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
    preimage = _DELIM.join(
        (
            prev_hash,
            event_id,
            ts_utc,
            type_,
            actor,
            run_id if run_id is not None else _NULL_RUN_ID,
            str(schema_ver),
            payload_json,
        )
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()
