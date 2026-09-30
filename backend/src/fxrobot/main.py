"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fxrobot import __version__
from fxrobot.api.deps import CSRF_HEADER
from fxrobot.api.middleware import register_middleware
from fxrobot.api.v1 import api_router
from fxrobot.core.config import Settings, get_settings
from fxrobot.core.errors import register_exception_handlers
from fxrobot.core.logging import configure_logging
from fxrobot.core.rate_limit import SlidingWindowRateLimiter
from fxrobot.db.session import build_engine, build_session_factory

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    engine = build_engine(settings)

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
        yield
        engine.dispose()
        logger.info("shutdown complete")

    app = FastAPI(
        title="2kFX ROBOT API",
        version=__version__,
        lifespan=lifespan,
        # Interactive docs are useful locally but expose the surface area in production.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.login_limiter = SlidingWindowRateLimiter(
        settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", CSRF_HEADER, "X-Request-ID"],
        )
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app
