"""Shared fixtures for tradekit unit tests (DESIGN §16, ring 1).

tradekit.contracts / tradekit.ledger are imported *lazily inside fixtures* so
that, while the implementation does not exist yet, each test module reports its
own collection error instead of one opaque conftest failure.

No network, no sleeps, no real clock: every timestamp is an explicit UTC
datetime (TD-17).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from ulid import ULID

# Frozen reference instants — never datetime.now() (TD-17, §16 "no real clock").
T0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
HORIZON = datetime(2026, 2, 15, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Contracts factories
# ---------------------------------------------------------------------------


@pytest.fixture
def thesis_kwargs() -> dict[str, Any]:
    """Complete, valid ThesisContract constructor kwargs (DESIGN §5.1).

    Pure data — tests mutate/delete keys to probe individual validators.
    Nested payloads are dicts so Pydantic coercion is exercised at the boundary.
    """
    return {
        "thesis_id": str(ULID()),
        "account_ref": "paper:alpha",
        "asset": {
            "symbol": "BTC/USD",
            "venue": "kraken",
            "asset_class": "crypto",
            "tick_size": "0.01",
        },
        "direction": "long",
        "strategy_tag": "momo-breakout-v1",
        "rationale": (
            "Spot ETF inflows resume post quarter-end rebalance; "
            "falsified if net flows stay negative for 5 consecutive sessions."
        ),
        "entry": {
            "order_type": "limit",
            "limit_price": "60000.00",
            "valid_until": "2026-01-20T00:00:00Z",
        },
        "horizon_end": HORIZON,
        "target_price": Decimal("66000.00"),
        "stop_price": Decimal("57000.00"),
        "invalidation": {
            "kind": "measurable",
            "predicate": {
                "kind": "price_close",
                "cmp": "lte",
                "value": "57000.00",
                "timeframe": "1h",
                "by": HORIZON,
            },
        },
        "size_usd": Decimal("25.00"),
        "sizing_method": "min_atr_kelly",
        "ev_block": {
            "p_win": "0.55",
            "reward_usd": "2.50",
            "risk_usd": "1.25",
            "ev_usd": "0.81",
        },
        "success_criteria": [
            {
                "kind": "price_touch",
                "cmp": "gte",
                "value": "66000.00",
                "timeframe": "1h",
                "by": HORIZON,
            }
        ],
        "failure_criteria": [
            {
                "kind": "price_close",
                "cmp": "lte",
                "value": "57000.00",
                "timeframe": "1h",
                "by": HORIZON,
            }
        ],
        "market_snapshot_id": str(ULID()),
        "review_artifact_id": None,
    }


@pytest.fixture
def make_thesis(thesis_kwargs):
    """Factory: valid ThesisContract, with keyword overrides."""

    def _make(**overrides: Any):
        from tradekit.contracts import ThesisContract

        return ThesisContract(**{**thesis_kwargs, **overrides})

    return _make


@pytest.fixture
def make_event():
    """Factory: valid Event envelope (DESIGN §5.3 / §6.2 columns)."""

    def _make(
        *,
        type: str = "LessonRecorded",  # shadows builtin deliberately: matches the field name
        payload: dict[str, Any] | None = None,
        actor: str = "agent:test",
        ts: datetime | None = None,
        run_id: str | None = None,
    ):
        from tradekit.contracts import Event

        return Event(
            event_id=str(ULID()),
            ts_utc=ts or T0,
            type=type,
            actor=actor,
            run_id=run_id,
            schema_ver=1,
            payload=payload if payload is not None else {"note": "fixture event", "salience": 1},
        )

    return _make


# ---------------------------------------------------------------------------
# Ledger fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "ledger.db"


@pytest.fixture
def ledger(ledger_path):
    from tradekit.ledger import Ledger

    return Ledger(ledger_path)


@pytest.fixture
def raw_sql(ledger_path):
    """Raw SQL against the ledger file — a *test-harness* backdoor used only to
    tamper with rows (chain tests) and observe projections (rebuild tests).
    Never a substitute for the public verbs."""

    def _exec(statement: str, *params: Any) -> list[tuple[Any, ...]]:
        con = sqlite3.connect(ledger_path)
        try:
            rows = [tuple(r) for r in con.execute(statement, params).fetchall()]
            con.commit()
        finally:
            con.close()
        return rows

    return _exec


@pytest.fixture
def read_model_snapshot(ledger_path):
    """Dump of every read-model table: {table_name: sorted rows}.

    Skips the source-of-truth `events` table, FTS5 internals, and sqlite
    bookkeeping — what remains is exactly the rebuildable projection state
    (DESIGN §6.2 read models).
    """

    def _skip(name: str) -> bool:
        return name == "events" or name.startswith("events_fts") or name.startswith("sqlite_")

    def _snap() -> dict[str, list[tuple[Any, ...]]]:
        con = sqlite3.connect(ledger_path)
        try:
            names = [
                r[0]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                )
            ]
            return {
                name: sorted(tuple(r) for r in con.execute(f'SELECT * FROM "{name}"'))
                for name in names
                if not _skip(name)
            }
        finally:
            con.close()

    return _snap


# ---------------------------------------------------------------------------
# Zero-network enforcement (P1A DoD, ASSUMPTIONS 27) — guards the WHOLE suite,
# not just tests/unit/mae_data/. respx's own pytest fixture (`respx_mock`,
# registered by the respx package's pytest plugin) defaults to
# assert_all_mocked=True: any httpx request that doesn't match a registered
# route raises AllMockedAssertionError instead of touching the network.
# Making it autouse means every test in the suite is guarded even if it never
# asks for `respx_mock` itself; a provider test that DOES need HTTP responses
# requests `respx_mock` by name in its own signature and gets this SAME
# cached instance (pytest fixture caching is per-test-node, not per
# requester), so it can register routes on it as normal.
#
# assert_all_called is left at respx's default (True) at the router level,
# but that only asserts routes that WERE registered get hit at least once —
# it does not require every registered route to be called every time within
# a single test unless the test itself registers routes it never intends to
# use. See test_cache.py's "closed bars never refetch" test: it registers
# one route, calls the cache twice, and asserts the route's call count is 1 —
# that is a stronger, explicit pin, not something this fixture provides.
@pytest.fixture(autouse=True)
def _no_unmocked_network(respx_mock):
    yield respx_mock


# ---------------------------------------------------------------------------
# TK_DATA_DIR isolation (SPRINT P2 batch A, CTO pin) — the P1C cache-poisoning
# lesson applied to the ledger: `tradekit.ledger.default_ledger()` resolves
# TK_DATA_DIR (default "./data") at call time, so ANY test that reaches state
# through a public verb (thesis.*, eventually policy.*) rather than the
# `ledger`/`ledger_path` fixtures would otherwise open the REAL
# `data/ledger.db` next to the repo. Autouse + suite-wide (not opt-in) because
# the whole point is that no test author has to remember to ask for it —
# same rationale as `_no_unmocked_network` above. Individual tests that also
# want the concrete tmp_path (e.g. to assert on `TK_DATA_DIR/ledger.db`
# directly) can request `tmp_path` themselves; pytest fixture caching returns
# the SAME per-test tmp_path both times.
@pytest.fixture(autouse=True)
def _tk_data_dir_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("TK_DATA_DIR", str(tmp_path))
    yield
