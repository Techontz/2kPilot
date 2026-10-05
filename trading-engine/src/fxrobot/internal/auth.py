"""HMAC authentication for Laravel → engine requests.

Laravel signs every request (backend/app/Services/Engine/EngineClient.php):

    canonical = METHOD \\n PATH?QUERY \\n TIMESTAMP \\n NONCE \\n sha256_hex(BODY)
    X-Engine-Signature = hex(HMAC-SHA256(ENGINE_API_SECRET, canonical))

Requests older than 60 s, replayed nonces, or bad signatures are refused.
The engine also binds to 127.0.0.1 by default, so it is not reachable from
other machines unless an operator changes that deliberately.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time

MAX_SKEW_SECONDS = 60


def canonical(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    return "\n".join([method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest()])


def sign(secret: str, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
    message = canonical(method, path, timestamp, nonce, body)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class NonceCache:
    """Remembers nonces for the replay window."""

    def __init__(self, ttl: float = MAX_SKEW_SECONDS * 2) -> None:
        self._ttl = ttl
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, nonce: str) -> bool:
        """False if the nonce was already used."""
        now = time.monotonic()
        with self._lock:
            if len(self._seen) > 10_000:
                self._seen = {n: t for n, t in self._seen.items() if now - t < self._ttl}
            seen = self._seen.get(nonce)
            if seen is not None and now - seen < self._ttl:
                return False
            self._seen[nonce] = now
            return True


def verify(
    secret: str,
    *,
    method: str,
    path: str,
    body: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    nonces: NonceCache,
    now: float | None = None,
) -> str | None:
    """None if valid, otherwise a short reason (never echoing secrets)."""
    if len(secret) < 32:
        return "engine secret not configured"
    if not timestamp or not nonce or not signature:
        return "missing signature headers"
    try:
        ts = int(timestamp)
    except ValueError:
        return "bad timestamp"
    if abs((now or time.time()) - ts) > MAX_SKEW_SECONDS:
        return "stale request"
    if not 16 <= len(nonce) <= 64:
        return "bad nonce"
    expected = sign(secret, method, path, timestamp, nonce, body)
    if not hmac.compare_digest(expected, signature):
        return "bad signature"
    if not nonces.add(nonce):
        return "replayed request"
    return None
