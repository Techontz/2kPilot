"""The contract every broker adapter implements.

Adapters are synchronous: SQLAlchemy sessions and the backtester are
synchronous (Deriv's WebSocket runs on its own reader thread), and the trading engine runs each
account on its own worker thread. Every method may raise the errors in
`broker_engine.errors`; nothing else should escape an adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from decimal import Decimal

from fxrobot.broker_engine.errors import OrderRejectedError, SymbolUnavailableError
from fxrobot.broker_engine.models import (
    AccountInfo,
    BrokerCapabilities,
    BrokerHealth,
    Candle,
    Deal,
    Order,
    OrderHint,
    OrderModification,
    OrderRequest,
    OrderResult,
    Position,
    Quote,
    SymbolInfo,
    Timeframe,
)
from fxrobot.domain.contracts import ContractCapabilities, ContractOrder, StakeQuote


class BrokerAdapter(ABC):
    #: Stable identifier matching a `ConnectorType` value (e.g. "deriv").
    connector_id: str
    #: True for internal simulators. Simulated fills are never shown as broker fills.
    is_simulated: bool = False
    #: What this broker supports (shown on the account card and the Trade page).
    capabilities: BrokerCapabilities = BrokerCapabilities()

    # ── connection ───────────────────────────────────────────────────────
    @abstractmethod
    def connect(self) -> AccountInfo:
        """Open the connection and return the account. Raises BrokerConnectionError."""

    @abstractmethod
    def disconnect(self) -> None: ...

    def test_connection(self) -> AccountInfo:
        """Connect, verify credentials, and return account details."""
        return self.connect()

    @property
    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def health(self) -> BrokerHealth:
        """Cheap liveness probe used by the reconnect loop."""

    # ── time ─────────────────────────────────────────────────────────────
    def now(self) -> datetime:
        """The broker's notion of 'now' (UTC). Simulators return simulated time."""
        return datetime.now(UTC)

    def advance(self, until: datetime | None = None) -> None:  # noqa: B027 (optional hook)
        """Called on every engine tick. Simulators move their market forward here,
        never past `until` (the next close of the finest timeframe a strategy watches)."""

    # ── account & market data ────────────────────────────────────────────
    @abstractmethod
    def get_account(self) -> AccountInfo: ...

    def get_balance(self) -> Decimal:
        return self.get_account().balance

    def get_equity(self) -> Decimal:
        return self.get_account().equity

    @abstractmethod
    def get_symbols(self) -> list[SymbolInfo]: ...

    def get_symbol(self, name: str) -> SymbolInfo:
        for symbol in self.get_symbols():
            if symbol.name == name:
                return symbol
        raise SymbolUnavailableError(f"Symbol {name} is not available")

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        """CLOSED candles with open time in [start, end), oldest first."""

    # ── contracts (Rise/Fall, Multipliers) ───────────────────────────────
    def contract_capabilities(self, symbol: str) -> ContractCapabilities:
        """Which contract families/durations/multipliers this broker offers on `symbol`."""
        info = self.get_symbol(symbol)
        return ContractCapabilities(symbol=info.name, spot=True, market_open=info.market_open)

    def quote_contract(self, symbol: str, contract: ContractOrder) -> StakeQuote:
        """Price a contract without buying it (stake limits, payout). Brokers that
        trade no contracts refuse."""
        raise OrderRejectedError(f"{self.connector_id} does not trade contracts")

    # ── trading state ────────────────────────────────────────────────────
    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_orders(self) -> list[Order]:
        """Currently pending (resting) orders."""

    @abstractmethod
    def get_deals(self, start: datetime, end: datetime) -> list[Deal]:
        """Executions (trade history) in [start, end)."""

    @abstractmethod
    def find_order_by_client_id(
        self, client_order_id: str, hint: OrderHint | None = None
    ) -> OrderResult | None:
        """Reconciliation hook: look up an order/deal by its idempotency key.

        Used after an OrderOutcomeUnknownError to decide whether a retry is safe.
        Brokers that cannot store our key use `hint` to match the order instead.
        """

    # ── trading actions ──────────────────────────────────────────────────
    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order.

        Raises OrderRejectedError (or a subclass) when the broker refuses it,
        and OrderOutcomeUnknownError when the outcome cannot be confirmed.
        """

    @abstractmethod
    def modify_order(self, order_id: str, changes: OrderModification) -> OrderResult: ...

    @abstractmethod
    def modify_position(
        self, position_id: str, stop_loss: Decimal | None, take_profit: Decimal | None
    ) -> OrderResult: ...

    @abstractmethod
    def close_position(
        self, position_id: str, client_order_id: str, volume: Decimal | None = None
    ) -> OrderResult:
        """Close a position fully, or partially when `volume` is given."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderResult: ...
