"""Event envelope + json_schemas() export (DESIGN §5.3, §6.3, TD-3).

The taxonomy IS a contract: a typo'd event type must die at the envelope, not
become an unqueryable orphan row in the ledger.
"""

import pytest
from pydantic import ValidationError

from tradekit.contracts import Event, json_schemas


@pytest.mark.parametrize(
    "event_type",
    ["RunStarted", "SizingComputed", "VerdictIssued", "ThesisGraded", "FillRecorded"],
)
def test_v1_taxonomy_types_accepted(make_event, event_type: str) -> None:
    # Spot-checks across the §6.3 taxonomy; SizingComputed is included
    # deliberately — it was added by TD-11/R-012 and is easy to omit.
    assert make_event(type=event_type).type == event_type


def test_unknown_type_rejected(make_event) -> None:
    with pytest.raises(ValidationError):
        make_event(type="OrderTeleported")
    # §6.3: "the taxonomy *is* a contract, not stringly-typed convention" — an
    # unknown type accepted here becomes an event no projection ever reads.


def test_payload_round_trips_through_json(make_event) -> None:
    event = make_event(
        type="LessonRecorded",
        payload={"note": "spread widens into the close", "salience": 3, "tags": ["fees", 2]},
    )
    back = Event.model_validate_json(event.model_dump_json())
    assert back == event, (
        "envelope must survive model -> JSON -> model unchanged: the ledger stores "
        "canonical JSON (§6.2) and replay/hash-verification both assume the round trip "
        "is lossless"
    )


def test_run_id_is_optional_on_envelope(make_event) -> None:
    # run_id is nullable in the DDL (§6.2) — the ledger stamps it at append time
    # (TD-20), so the envelope must allow None without complaint.
    assert make_event(run_id=None).run_id is None
    assert make_event(run_id="run-x").run_id == "run-x"


@pytest.mark.parametrize(
    ("field", "value"),
    [("actor", "mike\x1fpayload-shift"), ("run_id", "run\x00null"), ("actor", "a\nb")],
)
def test_control_chars_rejected_in_identity_fields(make_event, field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_event(**{field: value})
    # A control char in an identity field could smuggle hash-preimage structure
    # (delimiter forgery) or garble audit output — die at the envelope, before
    # the ledger ever sees it (reviewer D3, ASSUMPTIONS 22, §6.2).


def test_json_schemas_covers_core_contracts() -> None:
    schemas = json_schemas()
    assert isinstance(schemas, dict)
    for name in ("ThesisContract", "Event", "Verdict", "OrderRequest", "Fill", "Grade"):
        assert name in schemas, (
            f"json_schemas() missing {name!r}: non-Python agents (Codex/Gemini reviewers, "
            "D9) get typed contracts ONLY through this export (§5)"
        )
        schema = schemas[name]
        assert isinstance(schema, dict) and "properties" in schema, (
            f"{name} schema is not JSON-Schema-shaped (no 'properties' key): "
            f"got {type(schema).__name__}"
        )
