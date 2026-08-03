"""`tradekit.cadence` — T2's pure exit-trigger evaluation (SPEC-cadence.md
T2, "Exit TRIGGER evaluation", docs/specs/SPEC-cadence.md:98-104) plus T3's
autonomous paper cadence runner (SPEC-cadence.md T3, :126-173).

`exit_trigger` only decides WHEN to flatten an open position (stop/target/
horizon touch on the last CLOSED bar); it never decides HOW to close it —
that is `broker._pipeline.execute_exit`'s job. Pure: no I/O, no clock reads —
the caller supplies `now` (mirrors every other TD-17 "no real clock" seam
in this codebase).

Signature/tie-break per ASSUMPTIONS 177 (ratified): five keyword-only
params, Decimal prices, aware datetimes; stop wins a same-bar stop/target
tie (conservative, mirrors grading's own ambiguous-bar doctrine).

`run_once` composes PUBLIC verbs only: `broker`/`policy`/`thesis`/`hud`'s
module-level functions, `ledger.models`'s read surface, and the
`mae._runtime` clock/bars determinism seams every other module in this
codebase already treats as production-sanctioned (CLAUDE.md's own "no real
clock" pin). The ONE deliberate exception is `hud._serve`'s confirm-chain
internals (`_confirm_chain`/`_make_binding_proposal`/
`evaluate_policy_binding`): they ARE the confirm chain T1 made
strategy-def-aware, and duplicating that logic here would be exactly the
forwarding-wrapper anti-pattern the house style rejects — reused directly,
via the module's own dotted path so `evaluate_policy_binding`'s seam still
takes effect.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from tradekit import broker, mae, policy, thesis
from tradekit.contracts import EventFilter, HudState, ReviewCompletedPayload
from tradekit.hud import DEFAULT_SYMBOLS
from tradekit.hud import _serve as hud_serve
from tradekit.hud import build_state as _hud_build_state
from tradekit.ledger import Ledger, default_ledger
from tradekit.ledger._models import ActiveThesisWithSymbol
from tradekit.mae import _runtime as mae_runtime
from tradekit.mae._data.errors import ProviderError
from tradekit.policy._dials import PolicyDials

_TIMEFRAME = "1h"
_LOOKBACK_DAYS = 5  # just enough closed history for a "last closed bar" read

# Test seam (mirrors `hud._build`'s own module-attr convention): tests
# monkeypatch `cadence.build_state` directly; the default is the real HUD
# funnel walk.
build_state = _hud_build_state


class CadenceAccountRefused(Exception):
    """Raised by `run_once` when `PolicyDials.default_account_ref` isn't
    `paper:`-prefixed — Mike's structural red line: the cadence refuses to
    exist off-paper. Carries the offending `account_ref`."""

    def __init__(self, account_ref: str) -> None:
        self.account_ref = account_ref
        super().__init__(
            f"cadence refuses to run off-paper: default_account_ref={account_ref!r} does "
            "not start with 'paper:'"
        )


def exit_trigger(
    *,
    close: Decimal,
    stop_price: Decimal,
    target_price: Decimal,
    now: datetime,
    horizon_end: datetime,
) -> Literal["stop", "target", "horizon"] | None:
    """SPEC-cadence.md T2's three trigger conditions, evaluated in
    stop-first order so a degenerate bracket (stop==target==close) resolves
    to "stop" rather than "target": close<=stop_price -> "stop" (inclusive
    touch); else close>=target_price -> "target" (inclusive touch); else
    now>=horizon_end -> "horizon" (inclusive); else None (no trigger this
    bar)."""
    if close <= stop_price:
        return "stop"
    if close >= target_price:
        return "target"
    if now >= horizon_end:
        return "horizon"
    return None


def _paper_equity_usd(account_ref: str) -> tuple[Decimal, list[str]]:
    """settled cash + Sigma(open position qty x last CLOSED 1h close) — the
    same "mark open positions at the last closed bar" convention `hud._build`
    uses for its own funnel walk (SPEC-cadence T3 Unknowns register U1).

    F2 (review round 22): a single symbol's bar fetch must not take the
    whole run down — `ProviderError` (data provider down) and `IndexError`
    (an empty/degenerate `bars.bars`) are contained PER SYMBOL; that
    symbol's mark is skipped (equity understated is the conservative
    failure direction — never fabricated) and a digest warning names it."""
    port = broker.get(account_ref)
    equity_usd = port.account().settled_cash_usd
    warnings: list[str] = []
    for position in port.positions():
        try:
            bars = mae_runtime.get_closed_bars(position.symbol, _TIMEFRAME, _LOOKBACK_DAYS)
            equity_usd += position.qty * bars.bars[-1].close
        except (ProviderError, IndexError) as exc:
            warnings.append(f"{position.symbol}: equity mark skipped — {exc}")
    return equity_usd, warnings


def _thesis_contracts(ledger: Ledger, thesis_ids: set[str]) -> dict[str, dict[str, Any]]:
    """`ThesisDrafted` contracts for `thesis_ids`, one walk of the event log
    (mirrors `ledger.models.active_theses_with_symbol`'s own convention —
    the trigger needs stop/target/horizon, a different need than that
    verb's symbol-only pin)."""
    contracts: dict[str, dict[str, Any]] = {}
    for event in ledger.query(EventFilter(types=["ThesisDrafted"])):
        thesis_id = event.payload.get("thesis_id")
        if thesis_id in thesis_ids and thesis_id not in contracts:
            contracts[thesis_id] = event.payload.get("contract") or {}
    return contracts


def _confirm_entry(
    ledger: Ledger, ticket_dict: dict[str, Any], strategy_def: Any | None
) -> str:
    """Draft -> submit -> [auto-review], mirroring `hud._serve._confirm_
    chain`'s own first two-thirds — but stops at `reviewed`, ONE state short
    of `approve`, at MARKET rather than a resting LIMIT (cadence is
    autonomous — there is no Mike waiting on a specific limit price, and a
    LIMIT entry can never fill within the SAME `run_once` call anyway;
    `_paper.py::order_status`'s single-poll MVP only trades through a bar
    STRICTLY LATER than the order's own submission — see
    `test_execute_order_for_a_limit_entry_thesis_rests_with_no_fill`).

    F3+F5 (review round 22): `_run_entries` runs its binding policy
    evaluate against THIS state, `reviewed` — not before `draft` as the
    dispatch's literal wording first suggested. Verified during this fix
    round (ASSUMPTIONS-FLAG, CTO to reconcile): R-010/R-012 read
    `thesis_review_artifact_id`/`thesis_market_snapshot_id`/`thesis_ev_ok`/
    `recorded_sizing_usd` off the REAL ledger by `action.thesis_id`
    (`policy/_context.py`), and `evaluate_pure` denies on ANY
    `insufficient_context` hit (never passes vacuously, `_rules.py`'s own
    module docstring) — a pre-`draft` placeholder id therefore denies
    100% of entries, halted account or not (reproduced: every existing
    T3-AC-2/3/4 entry test failed identically). `reviewed` is the FIRST
    state carrying real review/EV/sizing context (`draft()`'s contract
    already carries EV/snapshot; `submit()` just recorded sizing) —
    genuinely "confirm time" per recon-R12's own definition, restated
    below. It is also the LAST state `thesis.reject()` accepts (illegal
    from `approved` — ASSUMPTIONS 64, `thesis/__init__.py::reject`), which
    is exactly why `_run_entries` must evaluate HERE: a deny still reaches
    `reject()`, a terminal, non-`active` state — the thesis never becomes
    `approved` and so never accumulates as the "approved orphan" review
    round 22 found. Reuses `_build_contract` for the heavy lifting
    (EV/bracket/strategy-tag derivation) and `_append_event` for the
    ReviewCompleted append; only the `entry` sub-dict is overridden."""
    contract = hud_serve._build_contract(ticket_dict, strategy_def)
    # F6 (review round 22, belt-and-braces): `_build_contract` re-loads
    # `PolicyDials` itself (a TOCTOU window against `run_once`'s own guard
    # read at the top of the run) — refuse loudly rather than silently
    # minting an off-paper thesis if the dials changed mid-run.
    if not str(contract["account_ref"]).startswith("paper:"):
        raise CadenceAccountRefused(str(contract["account_ref"]))
    contract["entry"] = {
        "order_type": "market",
        "valid_until": contract["entry"]["valid_until"],
    }
    thesis_id: str = thesis.draft(contract)
    thesis.submit(thesis_id)
    review_payload = ReviewCompletedPayload(
        thesis_id=thesis_id,
        review_artifact_id=hud_serve._REVIEW_ARTIFACT_ID,
        passed=True,
        kind="thesis_review",
    )
    hud_serve._append_event(ledger, "ReviewCompleted", review_payload.model_dump(mode="json"))
    return thesis_id


def _run_entries(
    ledger: Ledger, state: HudState, skip_symbols: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """T3-AC-2/T3-AC-3: submit only tickets whose symbol isn't already
    open/active, through the real strategy-aware confirm chain (T1) ->
    `execute_order` (T2).

    F3+F5 (review round 22, CTO-adjudicated pin, kills orphan theses):
    recon-R12 ratified the "two policy evaluations" the spec's preamble
    means as a real TWO-PHASE gate — a BINDING evaluate at confirm time
    (mirroring `hud._serve`'s own /ack confirm path: `_make_binding_
    proposal` + `evaluate_policy_binding`, reused via the module's own
    dotted path so its test seam still takes effect) PLUS `execute_order`'s
    own evaluate at submit time. `_confirm_entry`'s own docstring records
    WHY "confirm time" lands at `reviewed`, one state short of `approve`,
    rather than literally before `thesis.draft`: a deny here calls
    `thesis.reject` — the thesis never reaches `approved`, so it never
    accumulates as the "approved orphan" review round 22 found, without
    needing a pre-mint placeholder thesis_id that R-010/R-012 cannot
    evaluate.

    F7 (review round 22): each successfully entered symbol joins the
    in-loop skip set immediately, so two same-pair tickets in one funnel
    walk can never double-enter."""
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    entered_symbols = set(skip_symbols)
    for ticket in state.tickets:
        if ticket.pair in entered_symbols:
            continue
        strategy_def = mae.STRATEGY_BY_KEY.get(ticket.strategy_key) if ticket.strategy_key else None
        ticket_dict = ticket.model_dump()

        try:
            thesis_id = _confirm_entry(ledger, ticket_dict, strategy_def)
        except (broker.PipelineDenied, broker.ExitNothingToClose, ValueError) as exc:
            warnings.append(f"{ticket.pair}: entry failed — {exc}")
            continue

        proposal = hud_serve._make_binding_proposal(thesis_id, ticket_dict)
        decision = hud_serve.evaluate_policy_binding(proposal)
        if not decision.allowed:
            thesis.reject(thesis_id, decision.rationale or "cadence binding policy deny")
            warnings.append(f"{ticket.pair}: entry denied by policy — {decision.rationale}")
            continue

        try:
            thesis.approve(thesis_id)
            broker.execute_order(thesis_id)
        except (broker.PipelineDenied, broker.ExitNothingToClose, ValueError) as exc:
            warnings.append(f"{ticket.pair}: entry failed — {exc}")
            continue
        entered_symbols.add(ticket.pair)
        entries.append(
            {
                "symbol": ticket.pair,
                "strategy_key": ticket.strategy_key,
                "qty": ticket.quantity,
                "tp_price": ticket.tp_price,
                "sl_price": ticket.sl_price,
            }
        )
    return entries, warnings


def _run_exits(
    ledger: Ledger,
    active: list[ActiveThesisWithSymbol],
    now: datetime,
    open_symbols: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """T3-AC-4: for each ACTIVE thesis, evaluate the T2 trigger off the last
    CLOSED 1h bar; on trigger, `execute_exit` then `grade` (grade is the
    arbiter of PASS/FAIL — the trigger only decides WHEN to flatten).

    F2 (review round 22): the contract's own Decimal/fromisoformat/key
    parsing now sits INSIDE this thesis's own containment — one malformed
    contract warns and continues instead of crashing the whole exits phase.

    F4 (review round 22): `execute_exit` and `thesis.grade` are now separate
    try blocks (a successful flatten must never be masked by a grading
    hiccup's own warning text), and a flat-but-ACTIVE thesis — `row.symbol`
    carries no open position, e.g. an out-of-band fill or a PRIOR run's
    grade hiccup — with a firing trigger is graded DIRECTLY, skipping
    `execute_exit` (nothing left to close): otherwise that trade never
    reaches the promotion record at all, orphaned out of grading."""
    exits: list[dict[str, Any]] = []
    warnings: list[str] = []
    ids = {row.thesis_id for row in active if row.symbol}
    contracts = _thesis_contracts(ledger, ids)
    for row in active:
        if row.symbol is None:
            continue
        contract = contracts.get(row.thesis_id)
        if contract is None:
            continue
        try:
            bars = mae_runtime.get_closed_bars(row.symbol, _TIMEFRAME, _LOOKBACK_DAYS)
            close = bars.bars[-1].close
            target_price = Decimal(str(contract["target_price"]))
            stop_price = Decimal(str(contract["stop_price"]))
            horizon_end = datetime.fromisoformat(str(contract["horizon_end"]))
        except (KeyError, ValueError, TypeError, IndexError, InvalidOperation) as exc:
            warnings.append(f"{row.symbol}: malformed contract — {exc}")
            continue
        reason = exit_trigger(
            close=close,
            stop_price=stop_price,
            target_price=target_price,
            now=now,
            horizon_end=horizon_end,
        )
        if reason is None:
            continue

        if row.symbol not in open_symbols:
            try:
                graded = thesis.grade(row.thesis_id)
            except ValueError as exc:
                warnings.append(
                    f"{row.symbol}: recovery grade failed: {row.thesis_id} — {exc}"
                )
                continue
            exits.append(
                {"symbol": row.symbol, "reason": reason, "pnl_usd": graded.get("pnl_usd")}
            )
            continue

        try:
            broker.execute_exit(row.thesis_id)
        except (broker.PipelineDenied, broker.ExitNothingToClose, ValueError) as exc:
            warnings.append(f"{row.symbol}: exit failed — {exc}")
            continue

        try:
            graded = thesis.grade(row.thesis_id)
        except ValueError as exc:
            warnings.append(f"grade failed after successful exit: {row.thesis_id} — {exc}")
            continue

        exits.append(
            {"symbol": row.symbol, "reason": reason, "pnl_usd": graded.get("pnl_usd")}
        )
    return exits, warnings


def _prefilter_kill_counts(attrition: tuple[dict[str, Any], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in attrition:
        killed_by = entry.get("killed_by")
        if killed_by and "regime_prefilter" in str(killed_by):
            counts[str(killed_by)] = counts.get(str(killed_by), 0) + 1
    return counts


def _render_run_section(
    *,
    now: datetime,
    entries: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    state: HudState,
    warnings: list[str],
) -> str:
    """T3-AC-5's pinned sections (loosest honest substrings, ASSUMPTIONS-
    FLAG 3): run timestamp; entries; exits (reason + graded pnl); per-symbol
    attrition; per-strategy prefilter-kill counts; promotion_status summary;
    a drought line on a zero-entry zero-exit run; warnings."""
    lines = [f"## Run {now.isoformat()}", ""]

    lines.append("### Entries")
    if entries:
        for entry in entries:
            lines.append(
                f"- {entry['symbol']} strategy_key={entry['strategy_key']!r} "
                f"qty={entry['qty']} tp={entry['tp_price']} sl={entry['sl_price']}"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Exits")
    if exits:
        for exit_ in exits:
            lines.append(
                f"- {exit_['symbol']} reason={exit_['reason']} pnl_usd={exit_['pnl_usd']}"
            )
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Attrition")
    if state.attrition:
        for entry in state.attrition:
            lines.append(f"- {entry.get('symbol')}: killed_by={entry.get('killed_by')}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("### Prefilter kill counts")
    kill_counts = _prefilter_kill_counts(state.attrition)
    if kill_counts:
        for name, count in sorted(kill_counts.items()):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- none")
    lines.append("")

    status = policy.promotion_status()
    current_series = status.get("current_series") or {}
    counts = current_series.get("counts") or {}
    lines.append("### Promotion status")
    lines.append(f"- tier={status.get('tier')}")
    lines.append(f"- current_series graded={counts.get('graded')}")
    lines.append(f"- t2_eligible={status.get('t2_eligible')}")
    lines.append("")

    if not entries and not exits:
        lines.append("### Drought")
        lines.append("zero entries, zero exits this run — drought reported, never traded around")
        lines.append("")

    if warnings:
        lines.append("### Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _append_digest(digest_dir: Path, now: datetime, section: str) -> None:
    """One file per UTC day (T3-AC-5), append-per-run — ALWAYS writes, even
    on a drought run."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    path = digest_dir / f"DIGEST-{now.date().isoformat()}.md"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(section)


def run_once(*, digest_dir: Path = Path("docs/digest")) -> None:
    """SPEC-cadence.md T3's runner: guard -> entries -> exits -> digest.

    The guard (T3-AC-1) precedes EVERYTHING — zero evaluation, zero ledger
    mutation — when `PolicyDials.default_account_ref` isn't `paper:`-
    prefixed. Otherwise: build the HUD funnel state for `hud.DEFAULT_
    SYMBOLS`, submit entries for tickets whose symbol has no open position/
    active thesis (T3-AC-2/3), evaluate the T2 exit trigger for every active
    thesis and flatten+grade on a hit (T3-AC-4), then append the day's
    digest (T3-AC-5) — a drought run still writes.

    F1 (review round 22, crash-visible runs): an autonomous hourly job that
    dies mid-run with nothing but a bare traceback in a scheduler log is
    invisible to Mike until he happens to look. Everything past the guard is
    now contained: ANY unexpected exception appends a best-effort `Run
    FAILED` section naming the exception (a digest WRITE failure must never
    mask the ORIGINAL error — swallowed separately) and still RE-RAISES, so
    `scripts/run_cadence.py`'s own exit-code contract (F8) is unaffected.
    `CadenceAccountRefused` is the one deliberate exception to "everything
    past the guard": both the top-level guard above AND `_submit_entry`'s
    own belt-and-braces re-check (F6) raise it as a structural refusal, not
    a run failure — it propagates without a digest entry, matching the
    guard's own pre-digest contract."""
    dials = PolicyDials.load()
    account_ref = dials.default_account_ref
    if not account_ref.startswith("paper:"):
        raise CadenceAccountRefused(account_ref)

    now = mae_runtime.clock()
    try:
        ledger = default_ledger()
        # `ledger.models` is a "post-rebuild() read surface" (its own
        # docstring) — unlike `tk hud`/`tk ...`, this script has no CLI
        # dispatcher to have already refreshed the projections, so the
        # cadence run does it itself.
        ledger.rebuild()
        equity_usd, equity_warnings = _paper_equity_usd(account_ref)

        state = build_state(list(DEFAULT_SYMBOLS), captured_at=now, equity_usd=equity_usd)

        open_symbols = {position.symbol for position in broker.get(account_ref).positions()}
        active = ledger.models.active_theses_with_symbol()
        active_symbols = {row.symbol for row in active if row.symbol}
        skip_symbols = open_symbols | active_symbols

        entries, entry_warnings = _run_entries(ledger, state, skip_symbols)
        exits, exit_warnings = _run_exits(ledger, active, now, open_symbols)

        # This run's own entries/exits just moved the theses projection out
        # of date again — leave it fresh for whatever reads `ledger.models`
        # next (the CLI, a report, or this same process's next hourly run).
        ledger.rebuild()

        section = _render_run_section(
            now=now,
            entries=entries,
            exits=exits,
            state=state,
            warnings=equity_warnings + entry_warnings + exit_warnings,
        )
        _append_digest(digest_dir, now, section)
    except CadenceAccountRefused:
        raise
    except Exception as exc:
        try:
            _append_digest(
                digest_dir,
                now,
                f"### Run FAILED {now.isoformat()}: {type(exc).__name__}: {exc}\n",
            )
        except Exception:
            pass  # a digest WRITE failure must never mask the ORIGINAL error
        raise


__all__ = ["CadenceAccountRefused", "exit_trigger", "run_once"]
