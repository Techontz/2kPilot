"""MetaTrader 5 adapter — a client for the Windows `mt5_bridge` service.

Protocol: docs/MT5_BRIDGE_PROTOCOL.md. Every request is HMAC-signed and every
response signature is verified; an unverifiable response is treated as
untrusted (and, for order-changing calls, as an UNKNOWN outcome).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx

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
from fxrobot.broker_engine.models import (
    AccountInfo,
    BrokerHealth,
    Candle,
    Deal,
    DealEntry,
    Order,
    OrderModification,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    SymbolInfo,
    Timeframe,
)
from fxrobot.domain.modes import AccountEnvironment

READ_TIMEOUT = 15.0
TRADE_TIMEOUT = 40.0  # bridge allows 30 s for trade calls


def sign_request(
    secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes
) -> str:
    canonical = "\n".join(
        [method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest()]
    )
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def sign_response(secret: str, nonce: str, status: int, body: bytes) -> str:
    canonical = "\n".join([nonce, str(status), hashlib.sha256(body).hexdigest()])
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class MT5BridgeAdapter(BrokerAdapter):
    connector_id = "mt5_bridge"

    def __init__(
        self,
        *,
        base_url: str,
        secret: str,
        login: str,
        password: str,
        server: str,
        verify_tls: bool | str = True,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("bridge secret must be at least 32 characters")
        self._secret = secret
        self._login, self._password, self._server = login, password, server
        self._clock = clock
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            verify=verify_tls,
            transport=transport,
            timeout=READ_TIMEOUT,
        )
        self._connected = False
        self._symbols: dict[str, SymbolInfo] = {}

    def __repr__(self) -> str:  # never reveal credentials
        return f"MT5BridgeAdapter(url={self._client.base_url!s}, login={self._login})"

    # ── transport ────────────────────────────────────────────────────────
    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        trade: bool = False,
        client_order_id: str | None = None,
    ) -> Any:
        full_path = "/v1" + path + (("?" + urlencode(params)) if params else "")
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        ts, nonce = str(int(self._clock())), secrets.token_hex(16)
        headers = {
            "X-FX-Timestamp": ts,
            "X-FX-Nonce": nonce,
            "X-FX-Signature": sign_request(self._secret, method, full_path, ts, nonce, raw),
            "Content-Type": "application/json",
        }
        try:
            response = self._client.request(
                method,
                full_path,
                content=raw or None,
                headers=headers,
                timeout=TRADE_TIMEOUT if trade else READ_TIMEOUT,
            )
        except httpx.TimeoutException as exc:
            if trade:
                raise OrderOutcomeUnknownError(
                    "Bridge did not answer in time", client_order_id=client_order_id
                ) from exc
            raise BrokerTimeoutError("MT5 bridge timed out") from exc
        except httpx.TransportError as exc:
            self._connected = False
            if trade:
                # The request may have been sent before the link dropped.
                raise OrderOutcomeUnknownError(
                    f"Bridge connection failed during a trade request: {exc.__class__.__name__}",
                    client_order_id=client_order_id,
                ) from exc
            raise BrokerConnectionError(
                f"Cannot reach MT5 bridge: {exc.__class__.__name__}"
            ) from exc

        expected = sign_response(self._secret, nonce, response.status_code, response.content)
        if not hmac.compare_digest(expected, response.headers.get("X-FX-Signature", "")):
            if trade:
                raise OrderOutcomeUnknownError(
                    "Bridge response signature invalid", client_order_id=client_order_id
                )
            raise InvalidBrokerResponseError("Bridge response signature invalid")
        try:
            payload = response.json() if response.content else None
        except ValueError as exc:
            if trade:
                raise OrderOutcomeUnknownError(
                    "Bridge returned malformed JSON", client_order_id=client_order_id
                ) from exc
            raise InvalidBrokerResponseError("Bridge returned malformed JSON") from exc
        if response.status_code >= 400:
            self._raise(response.status_code, payload, client_order_id)
        return payload

    def _raise(self, status: int, payload: Any, client_order_id: str | None) -> None:
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = str(err.get("code", "internal"))
        message = str(err.get("message", f"Bridge error {status}"))[:300]
        broker_code = err.get("broker_code")
        broker_code = str(broker_code) if broker_code is not None else None
        if code == "unauthorized":
            raise BrokerAuthError("Bridge refused our signature — check BRIDGE_SECRET and clocks")
        if code == "broker_auth_failed":
            raise BrokerAuthError(message, broker_code=broker_code)
        if code == "not_connected":
            self._connected = False
            raise BrokerConnectionError(message, broker_code=broker_code)
        if code == "symbol_unavailable":
            raise SymbolUnavailableError(message, broker_code=broker_code)
        if code == "not_found":
            raise NotFoundError(message, broker_code=broker_code)
        if code == "market_closed":
            raise MarketClosedError(message, broker_code=broker_code)
        if code == "insufficient_margin":
            raise InsufficientMarginError(message, broker_code=broker_code)
        if code == "rejected":
            raise OrderRejectedError(message, broker_code=broker_code)
        if code == "outcome_unknown":
            raise OrderOutcomeUnknownError(message, client_order_id=client_order_id)
        if code == "timeout":
            raise BrokerTimeoutError(message)
        if code == "invalid_request":
            raise OrderRejectedError(f"Bridge rejected request: {message}")
        raise BrokerError(message, broker_code=broker_code)

    # ── connection ───────────────────────────────────────────────────────
    def connect(self) -> AccountInfo:
        payload = self._call(
            "POST",
            "/session/connect",
            body={
                "login": self._login,
                "password": self._password,
                "server": self._server,
                "terminal_path": None,
            },
            trade=False,
        )
        account = _account(payload)
        self._connected = True
        self._symbols = {}
        return account

    def disconnect(self) -> None:
        try:
            self._call("POST", "/session/disconnect", body={})
        except BrokerError:
            pass
        finally:
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def health(self) -> BrokerHealth:
        started = time.perf_counter()
        try:
            payload = self._call("GET", "/health")
        except BrokerError as exc:
            self._connected = False
            return BrokerHealth(False, str(exc))
        latency = (time.perf_counter() - started) * 1000
        terminal = payload.get("terminal", {}) if isinstance(payload, dict) else {}
        ok = bool(terminal.get("connected")) and str(terminal.get("login")) == str(self._login)
        if not ok:
            self._connected = False
            return BrokerHealth(False, "MT5 terminal not connected to the trade server", latency)
        return BrokerHealth(True, f"MT5 {terminal.get('server', '')}".strip(), latency)

    # ── data ─────────────────────────────────────────────────────────────
    def get_account(self) -> AccountInfo:
        return _account(self._call("GET", "/account"))

    def get_symbols(self) -> list[SymbolInfo]:
        payload = self._call("GET", "/symbols")
        symbols = [_symbol(s) for s in _list(payload)]
        self._symbols = {s.name: s for s in symbols}
        return symbols

    def get_symbol(self, name: str) -> SymbolInfo:
        if name not in self._symbols:
            self.get_symbols()
        if name not in self._symbols:
            raise SymbolUnavailableError(f"Symbol {name} is not available")
        return self._symbols[name]

    def get_quote(self, symbol: str) -> Quote:
        p = _obj(self._call("GET", f"/quotes/{symbol}"))
        return Quote(
            symbol=str(p["symbol"]), bid=_dec(p["bid"]), ask=_dec(p["ask"]), time=_ts(p["time"])
        )

    def get_candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        payload = self._call(
            "GET",
            "/candles",
            params={
                "symbol": symbol,
                "timeframe": timeframe.value,
                "start": _iso(start),
                "end": _iso(end),
            },
        )
        return [
            Candle(
                time=_ts(c["time"]),
                open=_dec(c["open"]),
                high=_dec(c["high"]),
                low=_dec(c["low"]),
                close=_dec(c["close"]),
                tick_volume=int(c.get("tick_volume") or 0),
                spread_points=None if c.get("spread_points") is None else int(c["spread_points"]),
            )
            for c in _list(payload)
        ]

    def get_positions(self) -> list[Position]:
        return [
            Position(
                position_id=str(p["position_id"]),
                symbol=str(p["symbol"]),
                side=Side(p["side"]),
                volume=_dec(p["volume"]),
                open_price=_dec(p["open_price"]),
                open_time=_ts(p["open_time"]),
                stop_loss=_stop(p.get("stop_loss")),
                take_profit=_stop(p.get("take_profit")),
                unrealized_pnl=_dec(p.get("unrealized_pnl", "0")),
                swap=_dec(p.get("swap", "0")),
                client_order_id=p.get("client_order_id"),
            )
            for p in _list(self._call("GET", "/positions"))
        ]

    def get_orders(self) -> list[Order]:
        return [
            Order(
                order_id=str(o["order_id"]),
                symbol=str(o["symbol"]),
                side=Side(o["side"]),
                order_type=OrderType(o["order_type"]),
                volume=_dec(o["volume"]),
                status=OrderStatus(o.get("status", "PENDING")),
                price=_optdec(o.get("price")),
                stop_loss=_stop(o.get("stop_loss")),
                take_profit=_stop(o.get("take_profit")),
                created_time=_ts(o["created_time"]),
                client_order_id=o.get("client_order_id"),
            )
            for o in _list(self._call("GET", "/orders"))
        ]

    def get_deals(self, start: datetime, end: datetime) -> list[Deal]:
        payload = self._call("GET", "/deals", params={"start": _iso(start), "end": _iso(end)})
        return [
            Deal(
                deal_id=str(d["deal_id"]),
                order_id=_optstr(d.get("order_id")),
                position_id=_optstr(d.get("position_id")),
                symbol=str(d["symbol"]),
                side=Side(d["side"]),
                entry=DealEntry(d["entry"]),
                volume=_dec(d["volume"]),
                price=_dec(d["price"]),
                time=_ts(d["time"]),
                profit=_dec(d.get("profit", "0")),
                commission=_dec(d.get("commission", "0")),
                swap=_dec(d.get("swap", "0")),
                fee=_dec(d.get("fee", "0")),
                client_order_id=d.get("client_order_id"),
                reason=str(d.get("reason", "OTHER")),
            )
            for d in _list(payload)
        ]

    def find_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        try:
            return _result(self._call("GET", f"/orders/lookup/{client_order_id}"))
        except NotFoundError:
            return None

    # ── trading ──────────────────────────────────────────────────────────
    def place_order(self, request: OrderRequest) -> OrderResult:
        body = {
            "client_order_id": request.client_order_id,
            "symbol": request.symbol,
            "side": request.side.value,
            "order_type": request.order_type.value,
            "volume": str(request.volume),
            "price": _optstr(request.price),
            "stop_loss": _optstr(request.stop_loss),
            "take_profit": _optstr(request.take_profit),
            "max_slippage_points": request.max_slippage_points,
            "comment": request.comment,
        }
        payload = self._call(
            "POST", "/orders", body=body, trade=True, client_order_id=request.client_order_id
        )
        return self._trade_result(payload, request.client_order_id)

    def _trade_result(self, payload: Any, client_order_id: str | None) -> OrderResult:
        try:
            return _result(payload)
        except InvalidBrokerResponseError as exc:
            raise OrderOutcomeUnknownError(
                f"Unparseable trade response: {exc}", client_order_id=client_order_id
            ) from exc

    def modify_order(self, order_id: str, changes: OrderModification) -> OrderResult:
        body = {
            "price": _optstr(changes.price),
            "stop_loss": _optstr(changes.stop_loss),
            "take_profit": _optstr(changes.take_profit),
        }
        return self._trade_result(
            self._call("POST", f"/orders/{order_id}/modify", body=body, trade=True), None
        )

    def modify_position(
        self, position_id: str, stop_loss: Decimal | None, take_profit: Decimal | None
    ) -> OrderResult:
        body = {"stop_loss": _optstr(stop_loss), "take_profit": _optstr(take_profit)}
        return self._trade_result(
            self._call("POST", f"/positions/{position_id}/modify", body=body, trade=True), None
        )

    def close_position(
        self, position_id: str, client_order_id: str, volume: Decimal | None = None
    ) -> OrderResult:
        body = {"client_order_id": client_order_id, "volume": _optstr(volume)}
        payload = self._call(
            "POST",
            f"/positions/{position_id}/close",
            body=body,
            trade=True,
            client_order_id=client_order_id,
        )
        return self._trade_result(payload, client_order_id)

    def cancel_order(self, order_id: str) -> OrderResult:
        return self._trade_result(
            self._call("POST", f"/orders/{order_id}/cancel", body={}, trade=True), None
        )


# ── strict parsing helpers (malformed data → InvalidBrokerResponseError) ─────


def _obj(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidBrokerResponseError("expected an object")
    return payload


def _list(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
        raise InvalidBrokerResponseError("expected a list of objects")
    return payload


def _dec(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidBrokerResponseError(f"invalid decimal {value!r}") from exc
    if not result.is_finite():
        raise InvalidBrokerResponseError(f"invalid decimal {value!r}")
    return result


def _optdec(value: Any) -> Decimal | None:
    return None if value in (None, "") else _dec(value)


def _stop(value: Any) -> Decimal | None:
    """MT5 uses 0 for 'no stop loss / take profit'."""
    result = _optdec(value)
    return None if result is None or result == 0 else result


def _optstr(value: Any) -> str | None:
    return None if value is None else str(value)


def _ts(value: Any) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidBrokerResponseError(f"invalid timestamp {value!r}") from exc
    if moment.tzinfo is None:
        raise InvalidBrokerResponseError("timestamp without timezone")
    return moment.astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _account(payload: Any) -> AccountInfo:
    p = _obj(payload)
    try:
        environment = AccountEnvironment(p.get("environment", "UNKNOWN"))
    except ValueError:
        environment = AccountEnvironment.UNKNOWN
    if environment is AccountEnvironment.PAPER:  # a bridge can never be paper
        environment = AccountEnvironment.UNKNOWN
    try:
        return AccountInfo(
            account_id=str(p["account_id"]),
            name=str(p.get("name", "")),
            server=str(p.get("server", "")),
            currency=str(p["currency"]),
            environment=environment,
            balance=_dec(p["balance"]),
            equity=_dec(p["equity"]),
            margin=_optdec(p.get("margin")),
            free_margin=_optdec(p.get("free_margin")),
            margin_level=_optdec(p.get("margin_level")),
            leverage=int(p["leverage"]) if p.get("leverage") is not None else None,
            trade_allowed=bool(p.get("trade_allowed", False)),
        )
    except KeyError as exc:
        raise InvalidBrokerResponseError(f"account field missing: {exc}") from exc


def _symbol(p: dict[str, Any]) -> SymbolInfo:
    try:
        name = str(p["name"])
        base, quote = str(p["base_currency"]), str(p["quote_currency"])
        return SymbolInfo(
            name=name,
            description=str(p.get("description", "")),
            base_currency=base,
            quote_currency=quote,
            digits=int(p["digits"]),
            point=_dec(p["point"]),
            contract_size=_dec(p["contract_size"]),
            volume_min=_dec(p["volume_min"]),
            volume_max=_dec(p["volume_max"]),
            volume_step=_dec(p["volume_step"]),
            trade_allowed=bool(p.get("trade_allowed", False)),
            point_value=_optdec(p.get("point_value")),
            canonical=(base + quote) if len(base) == 3 and len(quote) == 3 else name,
        )
    except KeyError as exc:
        raise InvalidBrokerResponseError(f"symbol field missing: {exc}") from exc


def _result(payload: Any) -> OrderResult:
    p = _obj(payload)
    try:
        return OrderResult(
            client_order_id=p.get("client_order_id"),
            status=OrderStatus(p["status"]),
            broker_order_id=_optstr(p.get("broker_order_id")),
            broker_position_id=_optstr(p.get("broker_position_id")),
            filled_volume=_dec(p.get("filled_volume") or "0"),
            fill_price=_optdec(p.get("fill_price")),
            broker_code=_optstr(p.get("broker_code")),
            broker_message=_optstr(p.get("broker_message")),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidBrokerResponseError(f"invalid order result: {exc}") from exc
