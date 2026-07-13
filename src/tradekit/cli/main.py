"""`tk` entrypoint. Verbs are pure dispatch to deep modules (DESIGN §4.4).

Conventions: every verb honors --json for structured output; mutating verbs
exit non-zero on gate denial with the Verdict as payload; TK_RUN_ID stamps
the experiment registry (TD-20). Exit codes: 0 ok, 1 failed check/denial,
2 usage error (Typer's default).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

import tradekit
from tradekit.contracts import EventFilter, json_schemas
from tradekit.ledger import default_ledger

app = typer.Typer(no_args_is_help=True, add_completion=False)
schema_app = typer.Typer(no_args_is_help=True)
ledger_app = typer.Typer(no_args_is_help=True)
app.add_typer(schema_app, name="schema", help="Contract JSON Schemas (§5).")
app.add_typer(ledger_app, name="ledger", help="Audit surface over the event store (§6).")


@app.callback()
def _root() -> None:
    """tradekit — deterministic trading core for LLM agents."""


@app.command()
def version() -> None:
    """Print tradekit version."""
    typer.echo(f"tradekit {tradekit.__version__}")


@schema_app.command("export")
def schema_export(
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("docs/schemas"),
) -> None:
    """Write one JSON-Schema file per public contract model (D9)."""
    out.mkdir(parents=True, exist_ok=True)
    for name, schema in json_schemas().items():
        (out / f"{name}.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    typer.echo(f"wrote {len(json_schemas())} schemas to {out}")


@ledger_app.command("verify")
def ledger_verify(
    as_json: Annotated[bool, typer.Option("--json", help="Emit the ChainReport as JSON.")] = False,
) -> None:
    """Recompute the hash chain; nonzero exit on any break (§6.2)."""
    report = default_ledger().verify_chain()
    if as_json:
        typer.echo(report.model_dump_json())
    elif report.ok:
        typer.echo("chain OK")
    else:
        typer.echo(f"chain BROKEN at seq {report.first_bad_seq}")
    if not report.ok:
        raise typer.Exit(code=1)


@ledger_app.command("rebuild")
def ledger_rebuild() -> None:
    """Re-derive all read-model projections from events (idempotent)."""
    default_ledger().rebuild()
    typer.echo("read models rebuilt")


@ledger_app.command("query")
def ledger_query(
    type_: Annotated[
        list[str] | None, typer.Option("--type", help="Event type(s); repeatable.")
    ] = None,
    since: Annotated[
        str | None, typer.Option(help="Inclusive ISO-8601 lower bound (aware).")
    ] = None,
    until: Annotated[
        str | None, typer.Option(help="Inclusive ISO-8601 upper bound (aware).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """Query events in seq order."""
    filter_ = EventFilter(
        types=type_ or None,
        since=since,  # type: ignore[arg-type]  # pydantic parses ISO strings
        until=until,  # type: ignore[arg-type]
    )
    events = default_ledger().query(filter_)
    if as_json:
        typer.echo("[" + ",".join(e.model_dump_json() for e in events) + "]")
    else:
        for e in events:
            typer.echo(f"{e.ts_utc.isoformat()}  {e.type:24}  {e.actor}  {e.event_id}")


if __name__ == "__main__":
    app()
