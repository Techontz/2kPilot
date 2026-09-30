"""The contract every broker adapter implements.

Adapters are asynchronous so the trading engine can run several accounts
concurrently; adapters wrapping blocking SDKs (e.g. the MetaTrader5 Python
package) should run those calls in a worker thread.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from fxrobot.broker_engine.models import (
    AccountInfo,
    Candle,
    Order,
    OrderModification,
    OrderRequest,
    OrderResult,
    Position,
    Quote,
    SymbolInfo,
    Timeframe,
)


class BrokerAdapter(ABC):
    #: Stable identifier matching a `ConnectorDescriptor.id` (e.g. "mt5").
    connector_id: str

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection. Raises BrokerConnectionError on failure."""

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def test_connection(self) -> AccountInfo:
        """Connect, verify credentials, and return account details."""

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    async def get_account(self) -> AccountInfo: ...

    async def get_balance(self) -> Decimal:
        return (await self.get_account()).balance

    async def get_equity(self) -> Decimal:
        return (await self.get_account()).equity

    @abstractmethod
    async def get_symbols(self) -> list[SymbolInfo]: ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    async def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """Closed candles with open time in [start, end), oldest first."""

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_orders(self) -> list[Order]:
        """Currently pending (resting) orders."""

    @abstractmethod
    async def find_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        """Reconciliation hook: look up an order/deal by its idempotency key.

        Used after an OrderOutcomeUnknownError to decide whether a retry is safe.
        """

    @abstractmethod
    async def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order.

        Raises OrderRejectedError when the broker refuses it, and
        OrderOutcomeUnknownError when the outcome cannot be confirmed.
        """

    @abstractmethod
    async def modify_order(self, order_id: str, changes: OrderModification) -> OrderResult: ...

    @abstractmethod
    async def close_position(self, position_id: str, volume: Decimal | None = None) -> OrderResult:
        """Close a position fully, or partially when `volume` is given."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> OrderResult: ...
