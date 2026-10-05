"""The engine process: internal API + automated trading loop.

    Laravel ──HMAC──► this API (127.0.0.1:8431) ──► broker adapters / engines ──► MySQL

Laravel authenticates users, authorises and audits actions, then calls these
endpoints. The browser never reaches the engine.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from fxrobot import __version__
from fxrobot.backtesting.service import BacktestService
from fxrobot.broker_engine.manager import BrokerManager
from fxrobot.core.config import Settings, get_settings
from fxrobot.core.context import (
    get_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)
from fxrobot.core.crypto import SecretBox, SecretBoxError
from fxrobot.core.errors import AppError
from fxrobot.core.logging import configure_logging
from fxrobot.db.session import build_engine, build_session_factory
from fxrobot.internal.auth import NonceCache, verify
from fxrobot.internal.routes import router
from fxrobot.services import strategies
from fxrobot.trading_engine.engine import TradingEngine

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/internal/health/live"}


def secret_box(settings: Settings) -> SecretBox | None:
    key = settings.broker_credentials_key.get_secret_value()
    if not key:
        return None
    try:
        return SecretBox(key)
    except SecretBoxError:
        logger.error("BROKER_CREDENTIALS_KEY is invalid — broker credentials cannot be used")
        return None


def error_body(code: str, message: str, details: object | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "code": code,
        "message": message,
        "correlation_id": get_correlation_id(),
    }
    if details is not None:
        body["details"] = details
    return {"error": body}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    box = secret_box(settings)
    manager = BrokerManager(session_factory, box, deriv_app_id=settings.deriv_app_id)
    backtests = BacktestService(session_factory, workers=1)
    trading_engine = TradingEngine(
        session_factory,
        manager,
        live_locked=not settings.live_trading_enabled,
        tick_seconds=settings.engine_tick_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "starting %s v%s",
            settings.app_name,
            __version__,
            extra={
                "env": settings.app_env.value,
                "live_trading_enabled": settings.live_trading_enabled,
            },
        )
        if settings.live_trading_enabled:
            logger.warning("LIVE_TRADING_ENABLED=true — the LIVE hard lock is OFF")
        try:
            with session_factory() as db:
                strategies.ensure_builtin_strategies(db)
        except SQLAlchemyError:
            logger.exception("could not seed strategies (database unavailable?) — continuing")
        if settings.engine_enabled:
            trading_engine.start()
        yield
        if settings.engine_enabled:
            trading_engine.stop()
        backtests.shutdown()
        manager.shutdown()
        engine.dispose()
        logger.info("shutdown complete")

    app = FastAPI(
        title="2kFX trading engine (internal)",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.broker_manager = manager
    app.state.secret_box = box
    app.state.backtests = backtests
    app.state.trading_engine = trading_engine
    nonces = NonceCache()

    @app.middleware("http")
    async def authenticate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        set_correlation_id(sanitize_correlation_id(request.headers.get("X-Correlation-ID")))
        if request.url.path not in PUBLIC_PATHS:
            body = await request.body()
            path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            problem = verify(
                settings.engine_api_secret.get_secret_value(),
                method=request.method,
                path=path,
                body=body,
                timestamp=request.headers.get("X-Engine-Timestamp"),
                nonce=request.headers.get("X-Engine-Nonce"),
                signature=request.headers.get("X-Engine-Signature"),
                nonces=nonces,
            )
            if problem is not None:
                logger.warning("refused internal request: %s", problem)
                return JSONResponse(
                    error_body("unauthorized", "Request not signed by the backend"),
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = get_correlation_id() or ""
        return response

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=int(exc.status_code))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details: list[dict[str, Any]] = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg")} for e in exc.errors()
        ]  # submitted values are not echoed: they may contain secrets
        return JSONResponse(
            error_body("validation_error", "Request validation failed", details),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            error_body("internal_error", "The trading engine hit an internal error"),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    app.include_router(router)
    return app
