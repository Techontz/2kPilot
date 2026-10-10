"""Broker abstraction layer.

Everything above this package (strategies, risk, execution) talks to the
`BrokerAdapter` interface and broker-neutral DTOs. Broker specifics
(Deriv, the internal paper simulator)
live only in `adapters/`.
"""

from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerTimeoutError,
    InsufficientMarginError,
    InvalidBrokerResponseError,
    MarketClosedError,
    NotFoundError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
    SymbolUnavailableError,
)
from fxrobot.broker_engine.interface import BrokerAdapter

__all__ = [
    "BrokerAdapter",
    "BrokerAuthError",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerTimeoutError",
    "InsufficientMarginError",
    "InvalidBrokerResponseError",
    "MarketClosedError",
    "NotFoundError",
    "OrderOutcomeUnknownError",
    "OrderRejectedError",
    "SymbolUnavailableError",
]
