"""Broker error taxonomy.

The distinction that matters most for safety: a *rejection* means the
broker definitely did not act; an *unknown outcome* means it may have.
Unknown outcomes must be reconciled against broker state before any retry.
"""

from __future__ import annotations


class BrokerError(Exception):
    """Base class for broker adapter failures."""


class BrokerConnectionError(BrokerError):
    """The adapter is not connected or the connection was lost."""


class BrokerTimeoutError(BrokerError):
    """A broker call timed out. For read calls, safe to retry."""


class OrderRejectedError(BrokerError):
    """The broker explicitly refused the order; nothing was executed."""

    def __init__(self, message: str, *, broker_code: str | None = None) -> None:
        super().__init__(message)
        self.broker_code = broker_code


class OrderOutcomeUnknownError(BrokerError):
    """The order may or may not have reached the broker (timeout, dropped link).

    Never blindly retry: reconcile using the client order ID first.
    """

    def __init__(self, message: str, *, client_order_id: str) -> None:
        super().__init__(message)
        self.client_order_id = client_order_id
