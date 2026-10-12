"""Transport for the Deriv API (developers.deriv.com, 2026 "new API").

Two channels:

* REST  `https://api.derivws.com` — list Options accounts and obtain a one-time
  password (OTP) for the trading WebSocket. Auth: `Authorization: Bearer <token>`
  plus `Deriv-App-ID: <app id>` when the token is a Personal Access Token.
* WebSocket  `wss://api.derivws.com/trading/v1/options/ws/{demo|real}?otp=…` —
  everything else (symbols, ticks, candles, proposal/buy/sell, portfolio…).
  The OTP is single-use and valid for 120 s, so every (re)connect asks REST
  for a fresh URL. No auth message is sent after connecting.

`DerivSocket` runs one reader thread that routes replies to waiting callers by
`req_id` and hands subscription messages (ticks, balance, open contracts) to
handlers. Adapter methods stay synchronous, like every other adapter.

Every request is counted against Deriv's documented WebSocket budgets
(`RateLimiter`): proposal + proposal_open_contract + buy + sell 360/min and
14,400/h; balance + statement 100/min, 2,000/h; portfolio + profit_table
30/min, 1,500/h; everything else 220/min, 14,400/h; ping is not counted.
A request that would exceed a budget waits briefly, then is refused BEFORE
it is sent (`BrokerRateLimitError`) — so a refused buy never executed.

Nothing here logs tokens; error messages never include request headers.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    BrokerRateLimitError,
    BrokerTimeoutError,
    InvalidBrokerResponseError,
)

logger = logging.getLogger(__name__)

DEFAULT_REST_URL = "https://api.derivws.com"
PING_INTERVAL = 30.0  # Deriv recommends a ping every 30 s
REQUEST_TIMEOUT = 15.0


class DerivApiError(BrokerError):
    """An error object returned by Deriv: {"error": {"code", "message", "subcode"}}."""

    def __init__(self, code: str, message: str, subcode: str | None = None) -> None:
        super().__init__(f"{message} ({subcode or code})", broker_code=subcode or code)
        self.deriv_code = code
        self.subcode = subcode


# ── REST ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class DerivAccount:
    account_id: str
    account_type: str  # "demo" | "real"
    currency: str
    balance: str
    status: str  # "active" | "inactive"

    def as_json(self) -> dict[str, str]:
        return {
            "account_id": self.account_id,
            "account_type": self.account_type,
            "currency": self.currency,
            "balance": self.balance,
            "status": self.status,
        }


def _money_text(value: Any) -> str:
    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return "0"


class DerivRest:
    def __init__(
        self,
        *,
        token: str,
        app_id: str,
        token_kind: str = "pat",  # noqa: S107 (a kind, not a secret)
        base_url: str = DEFAULT_REST_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        if not token:
            raise BrokerAuthError("A Deriv token is required")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if token_kind == "pat":  # noqa: S105 (a kind, not a secret)
            if not app_id:
                raise BrokerAuthError(
                    "Deriv requires an App ID for personal access tokens (DERIV_APP_ID)."
                )
            headers["Deriv-App-ID"] = app_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str) -> Any:
        try:
            response = self._client.request(method, path)
        except httpx.TimeoutException as exc:
            raise BrokerTimeoutError("Deriv did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"Cannot reach Deriv: {exc.__class__.__name__}") from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise InvalidBrokerResponseError(
                f"Deriv returned a non-JSON response (HTTP {response.status_code})"
            ) from exc
        if response.status_code >= 400:
            errors = body.get("errors") if isinstance(body, dict) else None
            first = errors[0] if isinstance(errors, list) and errors else {}
            code = str(first.get("code") or response.status_code)
            message = str(first.get("message") or "request failed")
            if response.status_code in (401, 403):
                raise BrokerAuthError(f"Deriv refused the token: {message} ({code})")
            if response.status_code == 429:
                raise BrokerConnectionError(f"Deriv rate limit reached: {message}")
            raise DerivApiError(code, message)
        if not isinstance(body, dict) or "data" not in body:
            raise InvalidBrokerResponseError("Deriv response has no 'data'")
        return body["data"]

    def accounts(self) -> list[DerivAccount]:
        data = self._request("GET", "/trading/v1/options/accounts")
        if not isinstance(data, list):
            raise InvalidBrokerResponseError("Deriv accounts response is not a list")
        out = []
        for item in data:
            try:
                out.append(
                    DerivAccount(
                        account_id=str(item["account_id"]),
                        account_type=str(item["account_type"]).lower(),
                        currency=str(item.get("currency") or "USD"),
                        balance=_money_text(item.get("balance", "0")),
                        status=str(item.get("status") or "active"),
                    )
                )
            except (KeyError, TypeError) as exc:
                raise InvalidBrokerResponseError("Malformed Deriv account entry") from exc
        return out

    def otp_url(self, account_id: str) -> str:
        data = self._request("POST", f"/trading/v1/options/accounts/{account_id}/otp")
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str) or not url.startswith("wss://"):
            raise InvalidBrokerResponseError("Deriv did not return a WebSocket URL")
        return url


# ── rate limits ──────────────────────────────────────────────────────────

# (window seconds, max requests) per category — developers.deriv.com limits.
BUDGETS: dict[str, tuple[tuple[float, int], ...]] = {
    "trading": ((60.0, 360), (3600.0, 14_400)),
    "account": ((60.0, 100), (3600.0, 2_000)),
    "history": ((60.0, 30), (3600.0, 1_500)),
    "other": ((60.0, 220), (3600.0, 14_400)),
}
CATEGORIES = {
    "proposal": "trading",
    "proposal_open_contract": "trading",
    "buy": "trading",
    "sell": "trading",
    "balance": "account",
    "statement": "account",
    "portfolio": "history",
    "profit_table": "history",
}
MAX_WAIT = 2.0  # seconds a request may wait for budget before it is refused


def category_of(payload: dict[str, Any]) -> str | None:
    """Budget category of a request (None = not counted, e.g. ping)."""
    if "ping" in payload:
        return None
    first = next(iter(payload), "")
    if "proposal_open_contract" in payload:
        return "trading"
    return CATEGORIES.get(first, "other")


class RateLimiter:
    """Sliding-window request budgets for one Deriv connection. Thread-safe."""

    def __init__(
        self,
        budgets: dict[str, tuple[tuple[float, int], ...]] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_wait: float = MAX_WAIT,
    ) -> None:
        self._budgets = budgets or BUDGETS
        self._clock = clock
        self._sleep = sleep
        self._max_wait = max_wait
        self._sent: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, category: str | None) -> None:
        if category is None:
            return
        windows = self._budgets.get(category) or self._budgets["other"]
        waited = 0.0
        while True:
            with self._lock:
                now = self._clock()
                sent = self._sent.setdefault(category, deque())
                longest = max(w for w, _ in windows)
                while sent and now - sent[0] >= longest:
                    sent.popleft()
                wait = 0.0
                for window, limit in windows:
                    recent = [t for t in sent if now - t < window]
                    if len(recent) >= limit:
                        wait = max(wait, recent[len(recent) - limit] + window - now)
                if wait <= 0:
                    sent.append(now)
                    return
            if waited + wait > self._max_wait:
                raise BrokerRateLimitError(
                    f"Deriv request budget for {category} requests is used up; "
                    f"try again in {int(wait) + 1}s (nothing was sent)"
                )
            self._sleep(wait)
            waited += wait


# ── WebSocket ────────────────────────────────────────────────────────────


class WebSocketLike(Protocol):
    def send(self, message: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str | bytes: ...
    def close(self) -> None: ...


Connector = Callable[[str], WebSocketLike]


def default_connector(url: str) -> WebSocketLike:
    from websockets.sync.client import connect

    try:
        return connect(url, open_timeout=REQUEST_TIMEOUT, close_timeout=2, max_size=8 * 2**20)
    except Exception as exc:  # handshake refused (401 bad OTP), DNS, TLS …
        text = str(exc)
        if "401" in text:
            raise BrokerAuthError("Deriv refused the trading session (invalid OTP)") from exc
        raise BrokerConnectionError(
            f"Cannot open Deriv WebSocket: {exc.__class__.__name__}"
        ) from exc


Handler = Callable[[dict[str, Any]], None]


class DerivSocket:
    """One authenticated WebSocket. Thread-safe request/response by req_id."""

    def __init__(
        self,
        url: str,
        *,
        connector: Connector = default_connector,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._limiter = limiter or RateLimiter()
        self._ws = connector(url)
        self._ids = itertools.count(1)
        self._send_lock = threading.Lock()
        self._pending: dict[int, tuple[threading.Event, list[dict[str, Any]]]] = {}
        self._pending_lock = threading.Lock()
        self._handlers: dict[str, Handler] = {}
        self._closed = threading.Event()
        self.last_message_at = time.monotonic()
        self._reader = threading.Thread(target=self._read_loop, name="deriv-ws", daemon=True)
        self._reader.start()
        self._pinger = threading.Thread(target=self._ping_loop, name="deriv-ping", daemon=True)
        self._pinger.start()

    @property
    def is_open(self) -> bool:
        return not self._closed.is_set()

    def on(self, msg_type: str, handler: Handler) -> None:
        """Receive every streamed message of a type (e.g. "tick", "balance")."""
        self._handlers[msg_type] = handler

    def request(self, payload: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
        """Send and wait for the matching reply. Raises DerivApiError for API errors."""
        if self._closed.is_set():
            raise BrokerConnectionError("Deriv connection is closed")
        self._limiter.acquire(category_of(payload))  # raises before anything is sent
        req_id = next(self._ids)
        event: threading.Event = threading.Event()
        box: list[dict[str, Any]] = []
        with self._pending_lock:
            self._pending[req_id] = (event, box)
        try:
            with self._send_lock:
                self._ws.send(json.dumps({**payload, "req_id": req_id}))
        except Exception as exc:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            self._mark_closed()
            raise BrokerConnectionError("Deriv connection lost while sending") from exc
        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(req_id, None)
            if self._closed.is_set():
                raise BrokerConnectionError("Deriv connection lost")
            raise BrokerTimeoutError(f"Deriv did not answer '{next(iter(payload))}' in time")
        if not box:
            raise BrokerConnectionError("Deriv connection lost before the reply")
        message = box[0]
        error = message.get("error")
        if isinstance(error, dict):
            raise DerivApiError(
                str(error.get("code") or "Error"),
                str(error.get("message") or "request failed"),
                str(error["subcode"]) if error.get("subcode") else None,
            )
        return message

    def close(self) -> None:
        self._mark_closed()
        with contextlib.suppress(Exception):
            self._ws.close()

    # ── internals ────────────────────────────────────────────────────────
    def _mark_closed(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        with self._pending_lock:
            waiting = list(self._pending.values())
            self._pending.clear()
        for event, _ in waiting:
            event.set()  # wake callers; an empty box means "connection lost"

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                raw = self._ws.recv(timeout=1.0)
            except TimeoutError:
                continue
            except Exception as exc:
                # Who closed it and why (websockets: close code + reason), to tell
                # Deriv closing the link from a network drop.
                rcvd = getattr(exc, "rcvd", None)
                logger.warning(
                    "Deriv link closed: %s%s",
                    type(exc).__name__,
                    f" (code {rcvd.code}, reason {rcvd.reason!r})"
                    if rcvd is not None
                    else f": {exc}",
                )
                break
            self.last_message_at = time.monotonic()
            try:
                message = json.loads(raw)
            except ValueError:
                logger.warning("ignored a non-JSON Deriv message")
                continue
            if not isinstance(message, dict):
                continue
            req_id = message.get("req_id")
            waiter = None
            if isinstance(req_id, int):
                with self._pending_lock:
                    waiter = self._pending.pop(req_id, None)
            if waiter is not None:
                event, box = waiter
                box.append(message)
                event.set()
            # Streamed updates (subscriptions) are also dispatched to handlers.
            handler = self._handlers.get(str(message.get("msg_type")))
            if handler is not None and "error" not in message:
                try:
                    handler(message)
                except Exception:
                    logger.exception("Deriv stream handler failed")
        self._mark_closed()

    def _ping_loop(self) -> None:
        while not self._closed.wait(PING_INTERVAL):
            try:
                self.request({"ping": 1}, timeout=10)
            except BrokerError:
                logger.info("Deriv ping failed; connection will be re-opened")
                self.close()
                return
