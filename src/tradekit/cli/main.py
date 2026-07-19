"""`tk` entrypoint. Verbs are pure dispatch to deep modules (DESIGN §4.4).

Conventions: every verb honors --json for structured output; mutating verbs
exit non-zero on gate denial with the Verdict as payload; TK_RUN_ID stamps
the experiment registry (TD-20). Exit codes: 0 ok, 1 failed check/denial,
2 usage error (Typer's default).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer

import tradekit
from tradekit import broker, memory, policy, report, thesis
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
order_app = typer.Typer(no_args_is_help=True)
fill_app = typer.Typer(no_args_is_help=True)
wiki_app = typer.Typer(no_args_is_help=True)
report_app = typer.Typer(no_args_is_help=True)
bridge_app = typer.Typer(no_args_is_help=True)
app.add_typer(schema_app, name="schema", help="Contract JSON Schemas (§5).")
app.add_typer(ledger_app, name="ledger", help="Audit surface over the event store (§6).")
app.add_typer(thesis_app, name="thesis", help="Thesis lifecycle (§10.1).")
app.add_typer(grade_app, name="grade", help="Grading (§10.2).")
app.add_typer(policy_app, name="policy", help="Policy engine (§7).")
app.add_typer(promote_app, name="promote", help="Promotion ladder (§7.3).")
app.add_typer(account_app, name="account", help="Named accounts (§8, TD-24).")
app.add_typer(order_app, name="order", help="Two-phase order pipeline (§8.2, SPRINT P3 batch C).")
app.add_typer(fill_app, name="fill", help="Advisory/manual fills (§8.4, D16, SPRINT P3 batch D).")
app.add_typer(wiki_app, name="wiki", help="Research-loop notes (§11, SPRINT P3 batch E).")
app.add_typer(report_app, name="report", help="Reporting (§12.3, SPRINT P3 batch E).")
app.add_typer(
    bridge_app, name="bridge", help="UIA prop-panel reconcile aid (SPEC-bridge-read, feature 1+2)."
)


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
    ] = [],  # noqa: B006 — Typer reads this as the CLI default, never mutated
) -> None:
    """`thesis.grade` over an explicit `--thesis` list, OR (SPRINT P3 batch
    E, closing the batch-C-flagged auto-discovery gap) every currently
    `active` thesis via `ledger.models.active_theses()` when NO `--thesis`
    is given — additive: explicit ids still work exactly as before."""
    ids = list(thesis_id)
    if not ids:
        ids = [t.thesis_id for t in _guard_not_implemented(default_ledger().models.active_theses)]
    for tid in ids:
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
def policy_resume(
    live_confirm: Annotated[
        bool,
        typer.Option(
            "--live-confirm",
            help=(
                "Required to clear a live_path halt (SPRINT P4-PAPER batch B, addendum 2 — "
                "'no auto-resume on the live path, ever'). Mike-manual confirmation."
            ),
        ),
    ] = False,
) -> None:
    """`policy.resume` — clears the kill switch (thin dispatch). A halt
    traced to a live-tier account refuses cleanly (`policy.
    LiveHaltRequiresManualConfirm`) without `--live-confirm`, never a raw
    traceback."""
    try:
        _guard_not_implemented(policy.resume, confirm_live=live_confirm)
    except policy.LiveHaltRequiresManualConfirm as exc:
        typer.echo(f"refused: {exc}")
        raise typer.Exit(code=1) from exc
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


@order_app.command("submit")
def order_submit(
    thesis_id: str,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """`broker.execute_order` (thin dispatch, SPRINT P3 batch C, §8.2). A
    deny verdict is a clean nonzero exit carrying the `Verdict`
    (`broker.PipelineDenied`), never a raw traceback — mirrors
    `_guard_not_implemented`'s NotImplementedError handling but for a
    DIFFERENT typed exception (the money-path's own refusal type, not a
    stub marker)."""
    try:
        ack = _guard_not_implemented(broker.execute_order, thesis_id)
    except broker.PipelineDenied as exc:
        if as_json:
            typer.echo(json.dumps({"denied": True, "verdict": exc.verdict.model_dump(mode="json")}))
        else:
            typer.echo(f"denied: {exc}")
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(ack.model_dump_json())
    else:
        typer.echo(f"{ack.order_id} {ack.status}")


@order_app.command("status")
def order_status(
    account_ref: Annotated[str, typer.Option(help="Account_ref that owns this order.")],
    order_id: str,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """`broker.get(account_ref).order_status(order_id)` (thin dispatch) —
    ALSO the polling point that evaluates a still-resting limit order
    (§8.3, ASSUMPTIONS round-17 entry 110)."""
    status = broker.get(account_ref).order_status(order_id)
    if as_json:
        typer.echo(status.model_dump_json())
    else:
        typer.echo(f"{status.order_id} {status.status}")


@order_app.command("cancel")
def order_cancel(
    account_ref: Annotated[str, typer.Option(help="Account_ref that owns this order.")],
    order_id: str,
) -> None:
    """`broker.cancel_order` (thin dispatch, SPRINT P3 batch C, additive
    fifth broker verb, ASSUMPTIONS round-18). MVP: resting limit orders
    only — a filled/canceled/rejected order refuses cleanly
    (`broker.OrderNotCancelable`), never a raw traceback."""
    try:
        _guard_not_implemented(broker.cancel_order, account_ref, order_id)
    except broker.OrderNotCancelable as exc:
        typer.echo(f"cannot cancel: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"canceled {order_id}")


@account_app.command("reconcile")
def account_reconcile(account_ref: str) -> None:
    """`broker.reconcile` (thin dispatch, SPRINT P3 batch C, §8.2 step 7).
    A mismatch appends an automatic HaltSet — this verb itself always exits
    0 on a successful RUN (the halt is the audit signal, not a CLI failure
    exit; `tk policy status --json` surfaces the resulting `halted` state
    for a caller that wants a nonzero-exit gate)."""
    _guard_not_implemented(broker.reconcile, account_ref)
    typer.echo(f"reconciled {account_ref}")


@fill_app.command("record")
def fill_record(
    thesis_id: Annotated[str, typer.Option("--thesis", help="thesis_id this fill executes.")],
    price: Annotated[str, typer.Option(help="Executed price.")],
    qty: Annotated[str, typer.Option(help="Executed quantity.")],
    fees: Annotated[str, typer.Option(help="Fees paid, USD.")],
    side: Annotated[str, typer.Option(help="'buy' or 'sell'.")],
    symbol: Annotated[str, typer.Option(help="Traded symbol, e.g. 'BTC/USD'.")],
    account_ref: Annotated[str, typer.Option("--account-ref", help="'advisory:*' account_ref.")],
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """`broker.record_manual_fill` (thin dispatch, SPRINT P3 batch D, D16/
    §8.4) — writes a `FillRecorded` event with `actor="mike"` for an
    advisory position Mike executed off-platform, then activates the
    thesis (mirrors `order submit`'s fill-triggers-activation shape).
    Money fields are `str` CLI options (Typer has no native `Decimal`
    converter, same reason every other money-carrying CLI verb in this
    codebase reads from a JSON config file instead) — converted to
    `Decimal` here, at the thin-shell boundary, before dispatch."""
    fill = _guard_not_implemented(
        broker.record_manual_fill,
        thesis_id,
        Decimal(price),
        Decimal(qty),
        Decimal(fees),
        cast(Literal["buy", "sell"], side),
        symbol,
        account_ref,
    )
    if as_json:
        typer.echo(fill.model_dump_json())
    else:
        typer.echo(f"{fill.order_id} {fill.price} x {fill.qty}")


@app.command("brief")
def tk_brief() -> None:
    """`memory.brief()` (thin dispatch, DESIGN §11, SPRINT P3 batch E)."""
    typer.echo(_guard_not_implemented(memory.brief))


@app.command("search")
def tk_search(
    query: str,
    k: Annotated[int, typer.Option(help="Max results.")] = 10,
    as_json: Annotated[bool, typer.Option("--json/--no-json")] = True,
) -> None:
    """`memory.search(query, k)` (thin dispatch, DESIGN §11)."""
    results = _guard_not_implemented(memory.search, query, k)
    typer.echo(json.dumps(results) if as_json else str(results))


@wiki_app.command("add")
def wiki_add(
    title: Annotated[str, typer.Option(help="Note title (slugified for the filename).")],
    body: Annotated[str, typer.Option(help="Note body markdown.")],
    status: Annotated[
        str, typer.Option(help="candidate|simulating|rejected|adopted.")
    ] = "candidate",
    salience: Annotated[int, typer.Option(help="1 (low) .. 5 (high).")] = 1,
    provenance: Annotated[str, typer.Option(help="Where this note came from.")] = "",
) -> None:
    """`memory._wiki.add_note` — writes a front-matter file under
    `PolicyDials.load().wiki_dir` (thin dispatch, DESIGN §11)."""
    from tradekit.memory import _wiki
    from tradekit.policy._dials import PolicyDials

    dials = PolicyDials.load()
    try:
        path = _wiki.add_note(
            dials.wiki_dir, title, body, status=status, salience=salience, provenance=provenance
        )
    except (_wiki.InvalidWikiStatus, ValueError) as exc:
        typer.echo(f"invalid wiki note: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(str(path))


@report_app.command("memo")
def report_memo(thesis_id: str) -> None:
    """`report.daily_memo(thesis_id)` (thin dispatch, DESIGN §12.3)."""
    typer.echo(_guard_not_implemented(report.daily_memo, thesis_id))


@report_app.command("readiness")
def report_readiness() -> None:
    """`report.readiness_report()` (thin dispatch, DESIGN §12.3)."""
    typer.echo(_guard_not_implemented(report.readiness_report))


@report_app.command("pnl")
def report_pnl(account_ref: str) -> None:
    """`report.pnl_snapshot(account_ref)` (thin dispatch, DESIGN §12.3)."""
    typer.echo(_guard_not_implemented(report.pnl_snapshot, account_ref))


def _check_bridge_map_drift() -> str | None:
    """AC-12: detect the connected app's `app_version` drifting from the
    element map's own `app_version` and return a warning string (or None).
    RED stub for T5 — GREEN work compares the two versions (S2's window-title
    parse / "unverified" provenance flag); returns None for now so the CLI
    never emits a false-positive warning while unimplemented. Test-writer
    -invented internal seam (flagged, not a spec pin) — tests monkeypatch it
    directly rather than driving real drift through the (also-stubbed)
    driver."""
    return None


@bridge_app.command("snapshot")
def bridge_snapshot() -> None:
    """`tk bridge snapshot` — read-only prop-panel reconcile aid (AC-9/AC-12).
    Exit 0 + pure-JSON `PropPanelSnapshot` on stdout; exit 2 if Kraken Desktop
    isn't running; exit 3 on a panel parse failure (field + raw text named);
    exit 4 on an element-map resolution failure (`ElementMapMiss` /
    `AmbiguousElement` / any other `BridgeError` — fix round F5).
    A map/app_version drift warning (AC-12) goes to stderr only, never stdout.
    """
    from tradekit import bridge as bridge_module

    try:
        result = bridge_module.snapshot(captured_at=datetime.now(UTC))
    except bridge_module.AppNotFound:
        typer.echo("Kraken Desktop not running", err=True)
        raise typer.Exit(code=2) from None
    except bridge_module.PanelParseError as exc:
        typer.echo(f"parse failure: field={exc.field} raw={exc.raw_text!r}", err=True)
        raise typer.Exit(code=3) from exc
    except bridge_module.BridgeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=4) from exc

    warning = _check_bridge_map_drift()
    if warning:
        typer.echo(warning, err=True)
    typer.echo(result.model_dump_json())


@app.command("hud")
def hud_scan(
    symbols: Annotated[
        str, typer.Option("--symbols", help="Comma-separated pairs (default: 11-pair greenlist).")
    ] = "",
    out: Annotated[
        Path, typer.Option("--out", help="HTML output path.")
    ] = Path("docs/hud/hud.html"),
) -> None:
    """`tk hud` — advisory-only order-book HUD scan (SPEC-hud-orderbook AC-9/AC-10).
    Writes a static HTML report to `--out` (atomic replace); exit 4 if the
    write fails, leaving any pre-existing target untouched.
    """
    from tradekit import hud
    from tradekit.mae import _runtime as mae_runtime

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else list(
        hud.DEFAULT_SYMBOLS
    )

    captured_at = mae_runtime.clock()
    state = hud.build_state(symbol_list, captured_at=captured_at)
    html = hud.render(state)

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(html)
            os.replace(tmp_name, out)
        except OSError:
            os.remove(tmp_name)
            raise
    except OSError as exc:
        typer.echo(f"failed to write {out}: {exc}", err=True)
        raise typer.Exit(code=4) from exc


if __name__ == "__main__":
    app()
