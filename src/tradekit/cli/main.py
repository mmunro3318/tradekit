"""`tk` entrypoint. Verbs are pure dispatch to deep modules (DESIGN §4.4).

Conventions: every verb honors --json for structured output; mutating verbs
exit non-zero on gate denial with the Verdict as payload; TK_RUN_ID stamps
the experiment registry (TD-20). Exit codes: 0 ok, 1 failed check/denial,
2 usage error (Typer's default).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

import tradekit
from tradekit import broker, policy, thesis
from tradekit.contracts import AccountConfig, EventFilter, json_schemas
from tradekit.ledger import default_ledger

app = typer.Typer(no_args_is_help=True, add_completion=False)
schema_app = typer.Typer(no_args_is_help=True)
ledger_app = typer.Typer(no_args_is_help=True)
thesis_app = typer.Typer(no_args_is_help=True)
grade_app = typer.Typer(no_args_is_help=True)
policy_app = typer.Typer(no_args_is_help=True)
promote_app = typer.Typer(no_args_is_help=True)
account_app = typer.Typer(no_args_is_help=True)
app.add_typer(schema_app, name="schema", help="Contract JSON Schemas (§5).")
app.add_typer(ledger_app, name="ledger", help="Audit surface over the event store (§6).")
app.add_typer(thesis_app, name="thesis", help="Thesis lifecycle (§10.1).")
app.add_typer(grade_app, name="grade", help="Grading (§10.2).")
app.add_typer(policy_app, name="policy", help="Policy engine (§7).")
app.add_typer(promote_app, name="promote", help="Promotion ladder (§7.3).")
app.add_typer(account_app, name="account", help="Named accounts (§8, TD-24).")


def _guard_not_implemented(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Thin-shell hygiene, not business logic (SPRINT P2 batch C): a verb
    this sprint stubs out (`policy.*`, story 4's series/promotion) still
    deserves a CLEAN nonzero exit — a raw traceback is not an acceptable
    CLI failure mode even for work that hasn't landed yet."""
    try:
        return fn(*args, **kwargs)
    except NotImplementedError as exc:
        typer.echo(f"not yet implemented: {exc}")
        raise typer.Exit(code=1) from exc


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


@thesis_app.command("draft")
def thesis_draft(
    file: Annotated[Path, typer.Option(help="Path to a JSON ThesisContract.")],
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """`thesis.draft` from a JSON contract file (thin dispatch, TD-2)."""
    contract = json.loads(file.read_text(encoding="utf-8"))
    thesis_id = thesis.draft(contract)
    if as_json:
        typer.echo(json.dumps({"thesis_id": thesis_id}))
    else:
        typer.echo(thesis_id)


@thesis_app.command("submit")
def thesis_submit(thesis_id: str) -> None:
    """`thesis.submit` (thin dispatch)."""
    thesis.submit(thesis_id)
    typer.echo(f"submitted {thesis_id}")


@thesis_app.command("show")
def thesis_show(
    thesis_id: str,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """This thesis's own lifecycle events, in seq order (thin ledger query —
    no thesis-module internals, TD-2)."""
    events = [
        e
        for e in default_ledger().query(EventFilter())
        if e.payload.get("thesis_id") == thesis_id
    ]
    if not events:
        typer.echo(f"no events found for thesis_id={thesis_id!r}")
        raise typer.Exit(code=1)
    if as_json:
        typer.echo("[" + ",".join(e.model_dump_json() for e in events) + "]")
    else:
        for e in events:
            typer.echo(f"{e.ts_utc.isoformat()}  {e.type:24}  {e.event_id}")


@thesis_app.command("approve")
def thesis_approve(thesis_id: str) -> None:
    """`thesis.approve` (thin dispatch)."""
    thesis.approve(thesis_id)
    typer.echo(f"approved {thesis_id}")


@thesis_app.command("reject")
def thesis_reject(
    thesis_id: str, why: Annotated[str, typer.Option(help="Reason (mandatory, §10.1).")]
) -> None:
    """`thesis.reject` (thin dispatch)."""
    thesis.reject(thesis_id, why)
    typer.echo(f"rejected {thesis_id}")


@thesis_app.command("void")
def thesis_void(
    thesis_id: str,
    attestation: Annotated[str, typer.Option(help="Structural invalidation attestation.")],
) -> None:
    """`thesis.void` (thin dispatch)."""
    thesis.void(thesis_id, attestation)
    typer.echo(f"voided {thesis_id}")


@grade_app.command("sweep")
def grade_sweep(
    thesis_id: Annotated[
        list[str], typer.Option("--thesis", help="thesis_id to grade; repeatable.")
    ],
) -> None:
    """`thesis.grade` over an explicit list of thesis_ids (thin dispatch —
    auto-discovering every `active` thesis needs a projection query surface
    this batch doesn't add to the CLI; FLAGGED, see tests/ASSUMPTIONS.md)."""
    for tid in thesis_id:
        result = thesis.grade(tid)
        typer.echo(json.dumps({"thesis_id": tid, "outcome": result["outcome"]}))


@grade_app.command("show")
def grade_show(
    thesis_id: str,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """Most recent `ThesisGraded` event for `thesis_id` (thin ledger query)."""
    events = [
        e
        for e in default_ledger().query(EventFilter(types=["ThesisGraded"]))
        if e.payload.get("thesis_id") == thesis_id
    ]
    if not events:
        typer.echo(f"no ThesisGraded event found for thesis_id={thesis_id!r}")
        raise typer.Exit(code=1)
    latest = events[-1]
    typer.echo(latest.model_dump_json() if as_json else str(latest.payload))


@policy_app.command("status")
def policy_status(
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = False,
    rules: Annotated[
        bool, typer.Option("--rules", help="Also (re)write rules/RULES.md.")
    ] = False,
) -> None:
    """`policy.status` (thin dispatch); `--rules` additionally regenerates
    `rules/RULES.md` from the registry."""
    result = _guard_not_implemented(policy.status)
    if rules:
        from tradekit.policy import _rules_md

        _guard_not_implemented(_rules_md.write_rules_md)
    if as_json:
        typer.echo(json.dumps(result))
    else:
        typer.echo(str(result))


@policy_app.command("halt")
def policy_halt(reason: str) -> None:
    """`policy.halt` — R-001 kill switch (thin dispatch)."""
    _guard_not_implemented(policy.halt, reason)
    typer.echo(f"halted: {reason}")


@policy_app.command("resume")
def policy_resume() -> None:
    """`policy.resume` — clears the kill switch (thin dispatch)."""
    _guard_not_implemented(policy.resume)
    typer.echo("resumed")


@promote_app.command("status")
def promote_status(as_json: Annotated[bool, typer.Option("--json/--no-json")] = False) -> None:
    """`policy.promotion_status` (thin dispatch; story 4, batch D)."""
    result = _guard_not_implemented(policy.promotion_status)
    typer.echo(json.dumps(result) if as_json else str(result))


@promote_app.command("confirm")
def promote_confirm() -> None:
    """`policy.confirm_promotion` — Mike-only verb (thin dispatch; story 4,
    batch D)."""
    _guard_not_implemented(policy.confirm_promotion)
    typer.echo("promotion confirmed")


@account_app.command("create-paper")
def account_create_paper(
    config: Annotated[Path, typer.Option("--config", help="Path to a JSON AccountConfig.")],
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """TD-24: `tk account create-paper` — validate the JSON config (filling
    `max_trades_per_day`/`max_daily_drawdown`/`max_lifetime_drawdown` from
    config.toml defaults when the file omits them) and ledger AccountCreated.
    A duplicate `account_ref` is a clean nonzero exit, not a traceback."""
    from tradekit.policy import _dials

    raw = json.loads(config.read_text(encoding="utf-8"))
    dials = _dials.PolicyDials.load()
    raw.setdefault("max_trades_per_day", dials.max_trades_per_day_default)
    raw.setdefault("max_daily_drawdown", dials.max_daily_drawdown_default)
    raw.setdefault("max_lifetime_drawdown", dials.max_lifetime_drawdown_default)
    account_config = AccountConfig(**raw)
    try:
        account_ref = broker.create_paper_account(account_config)
    except broker.AccountAlreadyExists as exc:
        typer.echo(f"account already exists: {exc.account_ref}")
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(json.dumps({"account_ref": account_ref}))
    else:
        typer.echo(account_ref)


if __name__ == "__main__":
    app()
