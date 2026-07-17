"""Pins the suite-wide TK_DATA_DIR autouse fixture (`tests/conftest.py::
_tk_data_dir_isolation`, SPRINT P2 batch A CTO pin).

The lesson this guards against (P1C's cache-poisoning trap, applied to the
ledger this time): `tradekit.ledger.default_ledger()` reads TK_DATA_DIR at
call time and defaults to "./data" relative to the process CWD, which for a
`pytest` run IS the repo root. Without the autouse fixture, any test that
reaches ledger state through a public verb (rather than the `ledger`/
`ledger_path` fixtures, which take an explicit tmp_path) would silently
read/write the REAL `data/ledger.db` checked into the repo — invisible
corruption of production state, exactly the class of bug P1C's `_cache_path`
lesson (ASSUMPTIONS 45/49) already burned us on for market-data caches.

Two tests: one is a pure probe on the environment (no I/O, cannot flake) per
the batch dispatch's explicit allowance ("asserting os.environ inside a
probe test is acceptable"); the other exercises the real seam
(`default_ledger()` + a verb-shaped append) and asserts the REAL
`data/ledger.db` file — located relative to the repo root, not CWD, so this
test is robust to whatever CWD pytest happens to be invoked from — is
byte-for-byte unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_LEDGER_DB = _REPO_ROOT / "data" / "ledger.db"


def test_tk_data_dir_env_points_at_the_per_test_tmp_path(tmp_path) -> None:
    # Pure environment probe (no filesystem I/O of its own) — cannot flake on
    # timing/locking the way a real file comparison could.
    assert os.environ["TK_DATA_DIR"] == str(tmp_path), (
        "TK_DATA_DIR must be monkeypatched to THIS test's own tmp_path by the "
        "autouse fixture in tests/conftest.py — every test gets a private ledger "
        "directory, never a shared or real one"
    )


def test_default_ledger_never_touches_the_real_data_dir(tmp_path) -> None:
    from tradekit.ledger import default_ledger

    # Snapshot the real repo ledger.db BEFORE touching anything through the
    # public seam. It may or may not exist (fresh checkout vs. a dev machine
    # that has run `tk` for real) — either way, its state after must match.
    before = _REAL_LEDGER_DB.read_bytes() if _REAL_LEDGER_DB.exists() else None

    # A verb-shaped op: open the ambient ledger exactly the way thesis/policy
    # verbs will (`ledger.default_ledger()`), then append — the write path
    # most likely to leak into the real file if the env seam were broken.
    ledger = default_ledger()
    ledger.append(
        _make_probe_event(),
    )

    after = _REAL_LEDGER_DB.read_bytes() if _REAL_LEDGER_DB.exists() else None
    assert after == before, (
        "the real data/ledger.db changed after a verb-shaped default_ledger() "
        "append: TK_DATA_DIR isolation is broken — this is the P1C "
        "cache-poisoning lesson, applied to the ledger (CTO pin, SPRINT P2 batch A)"
    )

    # And the write DID land — inside THIS test's own tmp_path, proving the
    # seam is redirected rather than merely inert.
    assert (tmp_path / "ledger.db").exists(), (
        "default_ledger() should have created ledger.db under TK_DATA_DIR "
        "(this test's tmp_path), not silently gone nowhere"
    )


def _make_probe_event():
    from datetime import UTC, datetime

    from ulid import ULID

    from tradekit.contracts import Event

    return Event(
        event_id=str(ULID()),
        ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
        type="LessonRecorded",
        actor="agent:test",
        run_id=None,
        schema_ver=1,
        payload={"note": "tk_data_dir isolation probe", "salience": 1},
    )
