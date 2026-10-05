"""The internal API refuses anything not signed by Laravel."""

from __future__ import annotations

import time

from fxrobot.internal.auth import NonceCache, sign, verify
from tests.conftest import ENGINE_SECRET, SignedClient


def test_unsigned_requests_are_refused(client: SignedClient) -> None:
    from fastapi.testclient import TestClient

    raw = TestClient(client.app)
    response = raw.get("/internal/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert raw.get("/internal/health/live").status_code == 200  # liveness only


def test_signed_requests_are_accepted(client: SignedClient) -> None:
    body = client.get("/internal/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["live_trading_enabled"] is False
    assert body["broker_credentials_key"] is True


def test_wrong_secret_is_refused(client: SignedClient) -> None:
    client.secret = "another-secret-that-is-long-enough-000000"
    assert client.get("/internal/health").status_code == 401


def test_signature_covers_body_time_and_nonce() -> None:
    nonces = NonceCache()
    now = int(time.time())
    sig = sign(ENGINE_SECRET, "POST", "/internal/orders", str(now), "n" * 16, b'{"a":1}')
    args = {"method": "POST", "path": "/internal/orders", "timestamp": str(now), "nonce": "n" * 16}
    assert (
        verify(ENGINE_SECRET, body=b'{"a":2}', signature=sig, nonces=nonces, **args)
        == "bad signature"
    )
    assert verify(ENGINE_SECRET, body=b'{"a":1}', signature=sig, nonces=nonces, **args) is None
    assert (
        verify(ENGINE_SECRET, body=b'{"a":1}', signature=sig, nonces=nonces, **args)
        == "replayed request"
    )
    old = str(now - 120)
    stale = sign(ENGINE_SECRET, "POST", "/internal/orders", old, "m" * 16, b"")
    assert (
        verify(
            ENGINE_SECRET,
            method="POST",
            path="/internal/orders",
            body=b"",
            timestamp=old,
            nonce="m" * 16,
            signature=stale,
            nonces=nonces,
        )
        == "stale request"
    )
    assert (
        verify("short", body=b"", signature=sig, nonces=nonces, **args)
        == "engine secret not configured"
    )
