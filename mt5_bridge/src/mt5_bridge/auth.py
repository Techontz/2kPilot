"""HMAC request authentication, response signing and the security middleware.

Canonical request (protocol v1)::

    METHOD \\n PATH_WITH_QUERY \\n TIMESTAMP \\n NONCE \\n SHA256_HEX(BODY)

Response signature::

    HMAC-SHA256(secret, REQUEST_NONCE \\n STATUS_CODE \\n SHA256_HEX(RESPONSE_BODY))
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import errors
from .config import Settings
from .logutil import request_id_var

log = logging.getLogger("mt5_bridge.http")

NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
TIMESTAMP_RE = re.compile(r"^[0-9]{1,12}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_request(
    method: str, path_with_query: str, timestamp: str, nonce: str, body: bytes
) -> bytes:
    return "\n".join([method.upper(), path_with_query, timestamp, nonce, sha256_hex(body)]).encode(
        "utf-8"
    )


def sign_request(
    secret: bytes, method: str, path_with_query: str, timestamp: str, nonce: str, body: bytes
) -> str:
    msg = canonical_request(method, path_with_query, timestamp, nonce, body)
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def sign_response(secret: bytes, request_nonce: str, status_code: int, body: bytes) -> str:
    msg = f"{request_nonce}\n{status_code}\n{sha256_hex(body)}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_response(
    secret: bytes, request_nonce: str, status_code: int, body: bytes, signature: str
) -> bool:
    return hmac.compare_digest(sign_response(secret, request_nonce, status_code, body), signature)


class NonceCache:
    """Remembers nonces of accepted requests for ``ttl`` seconds (replay protection)."""

    def __init__(
        self, ttl: float, clock: Callable[[], float] = time.time, max_entries: int = 200_000
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._max = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_add(self, nonce: str) -> bool:
        """Return ``True`` if the nonce is fresh (and record it), ``False`` if replayed."""
        now = self._clock()
        with self._lock:
            if len(self._seen) >= self._max or len(self._seen) % 1024 == 0:
                self._prune(now)
            exp = self._seen.get(nonce)
            if exp is not None and exp > now:
                return False
            if len(self._seen) >= self._max:
                return False  # refuse rather than forget live nonces
            self._seen[nonce] = now + self._ttl
            return True

    def _prune(self, now: float) -> None:
        for k in [k for k, exp in self._seen.items() if exp <= now]:
            del self._seen[k]

    def __len__(self) -> int:
        return len(self._seen)


def _path_with_query(scope: Scope) -> str:
    raw = scope.get("raw_path")
    path = raw.decode("latin-1") if raw else scope.get("path", "")
    qs: bytes = scope.get("query_string", b"")
    return f"{path}?{qs.decode('latin-1')}" if qs else path


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


class _BodyTooLargeError(Exception):
    pass


class SecurityMiddleware:
    """IP allowlist, body limit, HMAC verification, nonce replay cache, response signing,
    request ids and access logging. Every HTTP response leaving the app is signed."""

    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        nonce_cache: NonceCache,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.app = app
        self.settings = settings
        self.secret = settings.secret_bytes
        self.nonces = nonce_cache
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.monotonic()
        request_id = uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        headers = _headers(scope)
        nonce_hdr = headers.get("x-fx-nonce", "")
        # Echo the nonce in the response signature only if it is well-formed.
        sign_nonce = nonce_hdr if NONCE_RE.match(nonce_hdr) else ""
        client_ip = (scope.get("client") or ("", 0))[0]
        method = scope.get("method", "GET")
        pwq = _path_with_query(scope)
        status_holder = {"status": 0}

        async def send_error(err: errors.BridgeError) -> None:
            body = json.dumps(err.body(), separators=(",", ":")).encode()
            await self._send_signed(
                send,
                err.status_code,
                [(b"content-type", b"application/json")],
                body,
                sign_nonce,
                request_id,
            )
            status_holder["status"] = err.status_code

        try:
            # 1. IP allowlist
            if not self._ip_allowed(client_ip):
                log.warning("rejected client ip", extra={"client_ip": client_ip})
                await send_error(errors.unauthorized("Client IP not allowed"))
                return
            # 2. body (bounded)
            try:
                body = await self._read_body(receive, headers)
            except _BodyTooLargeError:
                await send_error(
                    errors.invalid_request(
                        f"Request body exceeds {self.settings.bridge_max_body_bytes} bytes"
                    )
                )
                return
            # 3. signature, timestamp window, nonce
            auth_err = self._authenticate(headers, method, pwq, body)
            if auth_err is not None:
                log.warning(
                    "authentication failed",
                    extra={"reason": auth_err, "client_ip": client_ip, "path": pwq},
                )
                await send_error(errors.unauthorized(auth_err))
                return

            await self._forward(scope, body, send, sign_nonce, request_id, status_holder)
        except Exception:
            log.exception("unhandled error")
            if status_holder["status"] == 0:
                await send_error(errors.internal())
        finally:
            log.info(
                "request",
                extra={
                    "method": method,
                    "path": scope.get("path", ""),
                    "status": status_holder["status"],
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                    "client_ip": client_ip,
                },
            )
            request_id_var.reset(token)

    # -- helpers -----------------------------------------------------------------
    def _ip_allowed(self, ip: str) -> bool:
        nets = self.settings.allowed_networks
        if not nets:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in n for n in nets)

    async def _read_body(self, receive: Receive, headers: dict[str, str]) -> bytes:
        limit = self.settings.bridge_max_body_bytes
        cl = headers.get("content-length")
        if cl is not None and cl.isdigit() and int(cl) > limit:
            raise _BodyTooLargeError
        chunks: list[bytes] = []
        size = 0
        while True:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            chunk = msg.get("body", b"")
            size += len(chunk)
            if size > limit:
                raise _BodyTooLargeError
            chunks.append(chunk)
            if not msg.get("more_body", False):
                break
        return b"".join(chunks)

    def _authenticate(
        self, headers: dict[str, str], method: str, pwq: str, body: bytes
    ) -> str | None:
        ts = headers.get("x-fx-timestamp", "")
        nonce = headers.get("x-fx-nonce", "")
        sig = headers.get("x-fx-signature", "")
        if not ts or not nonce or not sig:
            return "Missing authentication headers"
        if not TIMESTAMP_RE.match(ts) or not NONCE_RE.match(nonce):
            return "Malformed authentication headers"
        if abs(self.clock() - int(ts)) > self.settings.bridge_max_clock_skew_seconds:
            return "Timestamp outside the allowed window"
        expected = sign_request(self.secret, method, pwq, ts, nonce, body)
        if not hmac.compare_digest(expected, sig.lower()):
            return "Invalid signature"
        if not self.nonces.check_and_add(nonce):
            return "Nonce already used"
        return None

    async def _forward(
        self,
        scope: Scope,
        body: bytes,
        send: Send,
        sign_nonce: str,
        request_id: str,
        status_holder: dict[str, int],
    ) -> None:
        body_sent = False

        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        start: dict[str, Any] = {}
        parts: list[bytes] = []

        async def capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                parts.append(message.get("body", b""))

        await self.app(scope, replay_receive, capture)
        status = int(start.get("status", 500))
        hdrs = [
            (k, v)
            for k, v in start.get("headers", [])
            if k.lower() not in (b"content-length", b"x-fx-signature")
        ]
        await self._send_signed(send, status, hdrs, b"".join(parts), sign_nonce, request_id)
        status_holder["status"] = status

    async def _send_signed(
        self,
        send: Send,
        status: int,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
        nonce: str,
        request_id: str,
    ) -> None:
        sig = sign_response(self.secret, nonce, status, body)
        out = [
            *headers,
            (b"content-length", str(len(body)).encode()),
            (b"x-fx-signature", sig.encode()),
            (b"x-request-id", request_id.encode()),
            (b"cache-control", b"no-store"),
        ]
        await send({"type": "http.response.start", "status": status, "headers": out})
        await send({"type": "http.response.body", "body": body, "more_body": False})
