"""AccountState / Position / OrderStatus / AccountConfig / AccountCreatedPayload
(DESIGN §8.1, TD-24; SPRINT P3 batch A). Contracts are REAL this batch — same
"cheap and tests need to construct them" status as P2 batch A's payload
models — so every assertion below targets GREEN behavior.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from tradekit.contracts import (
    AccountConfig,
    AccountCreatedPayload,
    AccountState,
    OrderStatus,
    Position,
)

# ---------------------------------------------------------------------------
# AccountState / Position / OrderStatus — shape + Decimal/frozen discipline
# ---------------------------------------------------------------------------


def test_account_state_money_fields_are_decimal() -> None:
    state = AccountState(
        account_ref="paper:alpha",
        equity_usd=Decimal("500.00"),
        settled_cash_usd=Decimal("500.00"),
        buying_power_usd=Decimal("500.00"),
    )
    for field in ("equity_usd", "settled_cash_usd", "buying_power_usd"):
        assert isinstance(getattr(state, field), Decimal)


def test_account_state_is_frozen() -> None:
    state = AccountState(
        account_ref="paper:alpha",
        equity_usd=Decimal("500"),
        settled_cash_usd=Decimal("500"),
        buying_power_usd=Decimal("500"),
    )
    with pytest.raises(ValidationError):
        state.equity_usd = Decimal("1")  # type: ignore[misc]


def test_position_market_value_defaults_to_none_not_fabricated() -> None:
    position = Position(
        account_ref="paper:alpha", symbol="BTC/USD", qty=Decimal("0.01"), avg_price=Decimal("100")
    )
    assert position.market_value_usd is None


def test_order_status_defaults_zero_filled_qty() -> None:
    status = OrderStatus(order_id="ord-1", status="open")
    assert status.filled_qty == Decimal("0")
    assert status.remaining_qty is None


def test_order_status_rejects_an_unlisted_status_literal() -> None:
    with pytest.raises(ValidationError):
        OrderStatus(order_id="ord-1", status="bogus")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AccountConfig — table-driven validation (TD-24, Mike-signed 2026-07-17)
# ---------------------------------------------------------------------------


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "account_ref": "paper:alpha",
        "principal_usd": Decimal("500.00"),
        "max_trades_per_day": 0,
    }
    base.update(overrides)
    return base


def test_account_config_accepts_minimal_valid_kwargs() -> None:
    config = AccountConfig(**_valid_kwargs())
    assert config.principal_usd == Decimal("500.00")
    assert config.max_daily_drawdown is None
    assert config.max_lifetime_drawdown is None
    assert config.max_daily_profit is None
    assert config.consistency_rule is None


def test_account_config_none_means_disabled_never_infinity() -> None:
    config = AccountConfig(**_valid_kwargs())
    # None is the sentinel for "disabled" — never a sentinel Infinity Decimal.
    assert config.max_daily_drawdown is None
    assert config.max_lifetime_drawdown is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"principal_usd": Decimal("500.005")}, "principal_usd carries 3 decimal places"),
        ({"principal_usd": Decimal("500.123")}, "principal_usd carries 3 decimal places"),
        ({"max_trades_per_day": -1}, "max_trades_per_day must be >= 0"),
        ({"max_daily_drawdown": Decimal("-0.01")}, "max_daily_drawdown must be >= 0"),
        ({"max_lifetime_drawdown": Decimal("-0.01")}, "max_lifetime_drawdown must be >= 0"),
        ({"max_daily_profit": Decimal("-0.01")}, "max_daily_profit must be >= 0"),
    ],
)
def test_account_config_rejects_invalid_field_values(
    overrides: dict[str, object], reason: str
) -> None:
    with pytest.raises(ValidationError):
        AccountConfig(**_valid_kwargs(**overrides))


@pytest.mark.parametrize(
    "principal",
    [Decimal("500"), Decimal("500.0"), Decimal("500.00"), Decimal("0.01")],
)
def test_account_config_accepts_principal_at_or_under_two_decimal_places(
    principal: Decimal,
) -> None:
    config = AccountConfig(**_valid_kwargs(principal_usd=principal))
    assert config.principal_usd == principal


def test_account_config_is_frozen() -> None:
    config = AccountConfig(**_valid_kwargs())
    with pytest.raises(ValidationError):
        config.principal_usd = Decimal("1")  # type: ignore[misc]


def test_account_config_accepts_configured_drawdown_and_consistency_slots() -> None:
    config = AccountConfig(
        **_valid_kwargs(
            max_daily_drawdown=Decimal("0.03"),
            max_lifetime_drawdown=Decimal("0.25"),
            max_daily_profit=Decimal("0.05"),
            consistency_rule="no-single-day-over-40pct-of-total-pnl",
        )
    )
    assert config.max_daily_drawdown == Decimal("0.03")
    assert config.max_lifetime_drawdown == Decimal("0.25")
    assert config.max_daily_profit == Decimal("0.05")
    assert config.consistency_rule == "no-single-day-over-40pct-of-total-pnl"


# ---------------------------------------------------------------------------
# AccountCreatedPayload
# ---------------------------------------------------------------------------


def test_account_created_payload_carries_the_whole_config_dump() -> None:
    from datetime import UTC, datetime

    config = AccountConfig(**_valid_kwargs())
    payload = AccountCreatedPayload(
        account_ref=config.account_ref,
        config=config.model_dump(mode="json"),
        created_ts=datetime(2026, 7, 17, tzinfo=UTC),
    )
    assert payload.config["principal_usd"] == "500.00"


def test_account_created_payload_rejects_unknown_fields() -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        AccountCreatedPayload(
            account_ref="paper:alpha",
            config={},
            created_ts=datetime(2026, 7, 17, tzinfo=UTC),
            extra_field="should not validate",  # type: ignore[call-arg]
        )
