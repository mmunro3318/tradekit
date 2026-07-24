"""CONTRACT tests for SPRINT-TICKET-001 P4 ledger note:
`ScanAttritionRecordedPayload` — additive event payload, summary-only
(ASSUMPTIONS 164: "ledger `ScanAttritionRecorded` carries summary only").

Pinned shape (docs/specs/SPRINT-TICKET-001.md P4):
    {scan_ts, equity_usd, universe: list[str], tickets: int,
     stage_kills: dict[str, int], killer_filter: str | None}
House style (module docstring, `_event_payloads.py`): frozen,
`StrictFrozenModel` (`extra="forbid"`), `Decimal` for money fields,
`AwareDatetime` for timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest


class TestScanAttritionRecordedPayloadContract:
    def test_importable_from_contracts_event_payloads(self) -> None:
        """CONTRACT: the payload model exists at the pinned location."""
        from tradekit.contracts._event_payloads import ScanAttritionRecordedPayload

        assert ScanAttritionRecordedPayload is not None

    def test_constructs_with_all_pinned_fields(self) -> None:
        """CONTRACT: every pinned field round-trips."""
        from tradekit.contracts._event_payloads import ScanAttritionRecordedPayload

        payload = ScanAttritionRecordedPayload(
            scan_ts=datetime(2026, 7, 24, 11, 53, 42, tzinfo=UTC),
            equity_usd=Decimal("5000"),
            universe=["NEAR/USD", "LINK/USD"],
            tickets=1,
            stage_kills={"setup": 1, "sizing": 0, "policy_verdict": 0},
            killer_filter="setup",
        )

        assert payload.scan_ts == datetime(2026, 7, 24, 11, 53, 42, tzinfo=UTC)
        assert payload.equity_usd == Decimal("5000")
        assert payload.universe == ["NEAR/USD", "LINK/USD"]
        assert payload.tickets == 1
        assert payload.stage_kills == {"setup": 1, "sizing": 0, "policy_verdict": 0}
        assert payload.killer_filter == "setup"

    def test_killer_filter_accepts_none_when_no_stage_killed_anything(self) -> None:
        """CONTRACT: `killer_filter: str | None` — None is a valid value
        (every scanned symbol survived every gate)."""
        from tradekit.contracts._event_payloads import ScanAttritionRecordedPayload

        payload = ScanAttritionRecordedPayload(
            scan_ts=datetime(2026, 7, 24, tzinfo=UTC),
            equity_usd=Decimal("5000"),
            universe=["LINK/USD"],
            tickets=1,
            stage_kills={},
            killer_filter=None,
        )

        assert payload.killer_filter is None

    def test_frozen_and_forbids_extra_fields(self) -> None:
        """CONTRACT: `StrictFrozenModel` house style — a stray/typo'd field
        must raise at construction, not be silently dropped."""
        from pydantic import ValidationError

        from tradekit.contracts._event_payloads import ScanAttritionRecordedPayload

        with pytest.raises(ValidationError):
            ScanAttritionRecordedPayload(
                scan_ts=datetime(2026, 7, 24, tzinfo=UTC),
                equity_usd=Decimal("5000"),
                universe=["LINK/USD"],
                tickets=0,
                stage_kills={},
                killer_filter=None,
                unexpected_field="boom",
            )

    def test_naive_datetime_rejected_for_scan_ts(self) -> None:
        """CONTRACT: `AwareDatetime` house style (TD-17/ASSUMPTIONS 20) — a
        naive `scan_ts` must raise, never silently assume a timezone."""
        from pydantic import ValidationError

        from tradekit.contracts._event_payloads import ScanAttritionRecordedPayload

        with pytest.raises(ValidationError):
            ScanAttritionRecordedPayload(
                scan_ts=datetime(2026, 7, 24),  # naive
                equity_usd=Decimal("5000"),
                universe=["LINK/USD"],
                tickets=0,
                stage_kills={},
                killer_filter=None,
            )
