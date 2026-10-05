from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fxrobot.broker_engine import BrokerAdapter
from fxrobot.broker_engine.models import (
    OrderRequest,
    OrderType,
    Quote,
    Side,
    SymbolInfo,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment, TradingMode, environment_permitted


def test_incomplete_adapter_cannot_be_instantiated() -> None:
    class HalfAdapter(BrokerAdapter):
        connector_id = "half"

    with pytest.raises(TypeError):
        HalfAdapter()  # type: ignore[abstract]


def test_unknown_account_environment_is_treated_as_real_money() -> None:
    assert AccountEnvironment.UNKNOWN.is_real_money_possible
    assert AccountEnvironment.LIVE.is_real_money_possible
    assert not AccountEnvironment.DEMO.is_real_money_possible
    assert not AccountEnvironment.PAPER.is_real_money_possible


@pytest.mark.parametrize(
    ("mode", "env", "allowed"),
    [
        (TradingMode.DEMO, AccountEnvironment.PAPER, True),
        (TradingMode.DEMO, AccountEnvironment.DEMO, True),
        (TradingMode.DEMO, AccountEnvironment.LIVE, False),
        (TradingMode.DEMO, AccountEnvironment.UNKNOWN, False),
        (TradingMode.LIVE, AccountEnvironment.LIVE, True),
        (TradingMode.LIVE, AccountEnvironment.UNKNOWN, False),
        (TradingMode.BACKTEST, AccountEnvironment.PAPER, False),
    ],
)
def test_environment_permitted(mode: TradingMode, env: AccountEnvironment, allowed: bool) -> None:
    assert environment_permitted(mode, env) is allowed


def _order(**overrides: object) -> OrderRequest:
    values: dict[str, object] = {
        "client_order_id": "c-1",
        "symbol": "EURUSD",
        "side": Side.BUY,
        "order_type": OrderType.MARKET,
        "volume": Decimal("0.10"),
        "stop_loss": Decimal("1.0800"),
        "take_profit": Decimal("1.0900"),
    }
    values.update(overrides)
    return OrderRequest(**values)  # type: ignore[arg-type]


def test_order_request_validation() -> None:
    assert _order().volume == Decimal("0.10")
    with pytest.raises(ValueError, match="positive"):
        _order(volume=Decimal(0))
    with pytest.raises(ValueError, match="price"):
        _order(order_type=OrderType.LIMIT)


def test_quote_spread_and_pip_size() -> None:
    quote = Quote("EURUSD", Decimal("1.08500"), Decimal("1.08512"), datetime.now(UTC))
    assert quote.spread == Decimal("0.00012")
    eurusd = SymbolInfo(
        "EURUSD",
        "Euro vs Dollar",
        "EUR",
        "USD",
        5,
        Decimal("0.00001"),
        Decimal(100000),
        Decimal("0.01"),
        Decimal(100),
        Decimal("0.01"),
        True,
    )
    assert eurusd.pip_size == Decimal("0.00010")
    usdjpy = SymbolInfo(
        "USDJPY",
        "Dollar vs Yen",
        "USD",
        "JPY",
        3,
        Decimal("0.001"),
        Decimal(100000),
        Decimal("0.01"),
        Decimal(100),
        Decimal("0.01"),
        True,
    )
    assert usdjpy.pip_size == Decimal("0.010")


def test_timeframe_seconds() -> None:
    assert Timeframe.H4.seconds == 4 * Timeframe.H1.seconds
