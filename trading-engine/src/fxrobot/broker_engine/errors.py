"""Broker error taxonomy — every adapter maps its native errors onto these.

The distinction that matters most for safety: a *rejection* means the
broker definitely did not act; an *unknown outcome* means it may have.
Unknown outcomes must be reconciled against broker state before any retry.
"""

from __future__ import annotations


class BrokerError(Exception):
    """Base class for broker adapter failures."""

    code = "broker_error"

    def __init__(self, message: str, *, broker_code: str | None = None) -> None:
        super().__init__(message)
        self.broker_code = broker_code


class BrokerConnectionError(BrokerError):
    """The adapter is not connected or the connection was lost."""

    code = "not_connected"


class BrokerAuthError(BrokerConnectionError):
    """Credentials were refused by the broker (or the bridge)."""

    code = "auth_failed"


class BrokerTimeoutError(BrokerError):
    """A READ call timed out. Safe to retry reads."""

    code = "timeout"


class InvalidBrokerResponseError(BrokerError):
    """The broker/bridge answered with something we cannot trust or parse."""

    code = "invalid_response"


class SymbolUnavailableError(BrokerError):
    code = "symbol_unavailable"


class NotFoundError(BrokerError):
    code = "not_found"


class OrderRejectedError(BrokerError):
    """The broker explicitly refused the request; nothing was executed."""

    code = "rejected"


class MarketClosedError(OrderRejectedError):
    code = "market_closed"


class InsufficientMarginError(OrderRejectedError):
    code = "insufficient_margin"


class OrderOutcomeUnknownError(BrokerError):
    """The order may or may not have reached the broker (timeout, dropped link).

    Never blindly retry: reconcile using the client order ID first.
    """

    code = "outcome_unknown"

    def __init__(self, message: str, *, client_order_id: str | None = None) -> None:
        super().__init__(message)
        self.client_order_id = client_order_id
