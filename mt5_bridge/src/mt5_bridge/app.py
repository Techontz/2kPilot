"""FastAPI application factory."""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, FastAPI, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import errors
from .auth import NonceCache, SecurityMiddleware
from .config import Settings
from .journal import Journal
from .models import (
    CLIENT_ORDER_ID_PATTERN,
    SYMBOL_PATTERN,
    TICKET_PATTERN,
    ClosePositionRequest,
    ConnectRequest,
    ModifyOrderRequest,
    ModifyPositionRequest,
    OrderRequest,
    Timeframe,
)
from .service import BridgeService
from .terminal import Terminal
from .timeutil import parse_utc

log = logging.getLogger("mt5_bridge.app")


SymbolPath = Annotated[str, Path(pattern=SYMBOL_PATTERN)]
TicketPath = Annotated[str, Path(pattern=TICKET_PATTERN)]
CoidPath = Annotated[str, Path(pattern=CLIENT_ORDER_ID_PATTERN)]


class BridgeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        import json

        return json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_mt5() -> Any | None:
    try:
        return importlib.import_module("MetaTrader5")
    except ImportError:
        log.error("MetaTrader5 package not importable; terminal operations will fail")
        return None


def _error_response(err: errors.BridgeError) -> JSONResponse:
    return BridgeJSONResponse(err.body(), status_code=err.status_code)


def _utc_param(value: str, name: str) -> Any:
    try:
        return parse_utc(value)
    except ValueError as exc:
        raise errors.invalid_request(f"{name}: {exc}") from exc


def create_app(
    settings: Settings, mt5_module: Any | None = None, clock: Callable[[], float] = time.time
) -> FastAPI:
    """Build the bridge app. ``mt5_module`` defaults to the real ``MetaTrader5`` package."""
    mt5 = mt5_module if mt5_module is not None else _load_mt5()
    terminal = Terminal(mt5, settings.mt5_terminal_path, settings.connect_timeout_seconds)
    journal = Journal(settings.journal_path)
    service = BridgeService(settings, terminal, journal, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        terminal.close()
        journal.close()

    app = FastAPI(
        title="2kFX MT5 bridge",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        default_response_class=BridgeJSONResponse,
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.terminal = terminal
    app.state.journal = journal
    app.add_middleware(
        SecurityMiddleware,
        settings=settings,
        nonce_cache=NonceCache(settings.bridge_nonce_ttl_seconds, clock),
        clock=clock,
    )

    # -- error handlers ------------------------------------------------------------
    @app.exception_handler(errors.BridgeError)
    async def _bridge_error(_: Request, exc: errors.BridgeError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts = []
        for e in exc.errors()[:5]:
            loc = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path"))
            parts.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return _error_response(errors.invalid_request("; ".join(parts) or "Invalid request"))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(errors.not_found("Unknown endpoint"))
        if exc.status_code == 405:
            return _error_response(errors.invalid_request("Method not allowed"))
        return _error_response(
            errors.BridgeError(exc.status_code, "invalid_request", str(exc.detail))
        )

    # -- routes --------------------------------------------------------------------------
    @app.get("/v1/health")
    async def health() -> Any:
        return await service.health()

    @app.post("/v1/session/connect")
    async def connect(body: ConnectRequest) -> Any:
        return await service.connect(body)

    @app.post("/v1/session/disconnect")
    async def disconnect() -> Any:
        return await service.disconnect()

    @app.get("/v1/account")
    async def account() -> Any:
        return await service.account()

    @app.get("/v1/symbols")
    async def symbols() -> Any:
        return await service.symbols()

    @app.get("/v1/quotes/{symbol}")
    async def quote(symbol: SymbolPath) -> Any:
        return await service.quote(symbol)

    @app.get("/v1/candles")
    async def candles(
        symbol: Annotated[str, Query(pattern=SYMBOL_PATTERN)],
        timeframe: Annotated[Timeframe, Query()],
        start: Annotated[str, Query()],
        end: Annotated[str, Query()],
    ) -> Any:
        return await service.candles(
            symbol, timeframe, _utc_param(start, "start"), _utc_param(end, "end")
        )

    @app.get("/v1/positions")
    async def positions() -> Any:
        return await service.positions()

    @app.get("/v1/orders")
    async def orders() -> Any:
        return await service.orders()

    @app.get("/v1/deals")
    async def deals(start: Annotated[str, Query()], end: Annotated[str, Query()]) -> Any:
        return await service.deals(_utc_param(start, "start"), _utc_param(end, "end"))

    @app.get("/v1/orders/lookup/{client_order_id}")
    async def lookup(client_order_id: CoidPath) -> Any:
        return await service.lookup(client_order_id)

    @app.post("/v1/orders")
    async def submit_order(body: OrderRequest) -> Any:
        status, payload = await service.submit_order(body)
        return BridgeJSONResponse(payload, status_code=status)

    @app.post("/v1/orders/{order_id}/modify")
    async def modify_order(order_id: TicketPath, body: ModifyOrderRequest) -> Any:
        return await service.modify_order(order_id, body)

    @app.post("/v1/orders/{order_id}/cancel")
    async def cancel_order(
        order_id: TicketPath, _body: Annotated[dict[str, Any] | None, Body()] = None
    ) -> Any:
        return await service.cancel_order(order_id)

    @app.post("/v1/positions/{position_id}/modify")
    async def modify_position(position_id: TicketPath, body: ModifyPositionRequest) -> Any:
        return await service.modify_position(position_id, body)

    @app.post("/v1/positions/{position_id}/close")
    async def close_position(position_id: TicketPath, body: ClosePositionRequest) -> Any:
        status, payload = await service.close_position(position_id, body)
        return BridgeJSONResponse(payload, status_code=status)

    return app
