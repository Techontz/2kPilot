"""Broker abstraction layer.

Everything above this package (strategies, risk, execution) talks to the
`BrokerAdapter` interface and the broker-neutral DTOs in `models`. Broker
specifics (MetaTrader 5 today, others later) live only in adapters.
"""

from fxrobot.broker_engine.errors import (
    BrokerConnectionError,
    BrokerError,
    BrokerTimeoutError,
    OrderOutcomeUnknownError,
    OrderRejectedError,
)
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.broker_engine.registry import ConnectorDescriptor, ConnectorStatus, list_connectors

__all__ = [
    "BrokerAdapter",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerTimeoutError",
    "ConnectorDescriptor",
    "ConnectorStatus",
    "OrderOutcomeUnknownError",
    "OrderRejectedError",
    "list_connectors",
]
