"""Engine error types. The internal API maps them to JSON error bodies
(see internal/errors.py); messages are written for the dashboard user."""

from __future__ import annotations

from http import HTTPStatus as status  # noqa: N813


class AppError(Exception):
    status_code: int = status.BAD_REQUEST
    code: str = "bad_request"

    def __init__(
        self, message: str, *, code: str | None = None, details: object | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details  # optional structured detail, e.g. a list of problems
        if code:
            self.code = code


class AuthenticationError(AppError):
    status_code = status.UNAUTHORIZED
    code = "not_authenticated"


class PermissionDeniedError(AppError):
    status_code = status.FORBIDDEN
    code = "permission_denied"


class NotFoundError(AppError):
    status_code = status.NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.CONFLICT
    code = "conflict"


class UnprocessableError(AppError):
    status_code = status.UNPROCESSABLE_ENTITY
    code = "unprocessable"


class BrokerUnavailableError(AppError):
    status_code = status.BAD_GATEWAY
    code = "broker_unavailable"


class ServiceUnavailableError(AppError):
    status_code = status.SERVICE_UNAVAILABLE
    code = "service_unavailable"


class UpstreamError(AppError):
    status_code = status.BAD_GATEWAY
    code = "upstream_error"
