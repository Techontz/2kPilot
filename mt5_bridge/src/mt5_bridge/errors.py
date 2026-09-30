"""Protocol error model (see docs/MT5_BRIDGE_PROTOCOL.md, *Errors*)."""

from __future__ import annotations

from typing import Any


class BridgeError(Exception):
    """An error that is returned to the client as ``{"error": {...}}``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        broker_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.broker_code = broker_code

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.broker_code is not None:
            err["broker_code"] = self.broker_code
        return {"error": err}

    def __repr__(self) -> str:
        return f"BridgeError({self.status_code}, {self.code!r}, {self.message!r})"


def unauthorized(message: str = "Unauthorized") -> BridgeError:
    return BridgeError(401, "unauthorized", message)


def invalid_request(message: str) -> BridgeError:
    return BridgeError(422, "invalid_request", message)


def broker_auth_failed(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(400, "broker_auth_failed", message, broker_code)


def not_connected(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(503, "not_connected", message, broker_code)


def not_found(message: str) -> BridgeError:
    return BridgeError(404, "not_found", message)


def symbol_unavailable(message: str) -> BridgeError:
    return BridgeError(404, "symbol_unavailable", message)


def market_closed(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(409, "market_closed", message, broker_code)


def insufficient_margin(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(409, "insufficient_margin", message, broker_code)


def rejected(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(409, "rejected", message, broker_code)


def timeout(message: str = "Terminal call timed out") -> BridgeError:
    return BridgeError(504, "timeout", message)


def outcome_unknown(message: str, broker_code: str | None = None) -> BridgeError:
    return BridgeError(504, "outcome_unknown", message, broker_code)


def internal(message: str = "Internal bridge error") -> BridgeError:
    return BridgeError(500, "internal", message)
