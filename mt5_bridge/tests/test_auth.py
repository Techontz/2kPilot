from __future__ import annotations

import secrets
from pathlib import Path

from fastapi.testclient import TestClient

from mt5_bridge.app import create_app
from mt5_bridge.auth import NonceCache, sign_request, sign_response, verify_response

from .conftest import SECRET, BridgeClient, FakeClock, make_settings, signed_headers
from .fake_mt5 import FakeMT5


def test_canonical_signature_known_vector() -> None:
    sig = sign_request(b"k" * 32, "get", "/v1/health", "1700000000", "0" * 32, b"")
    # computed independently: HMAC-SHA256 over the canonical string
    import hashlib
    import hmac

    canonical = "GET\n/v1/health\n1700000000\n" + "0" * 32 + "\n" + hashlib.sha256(b"").hexdigest()
    assert sig == hmac.new(b"k" * 32, canonical.encode(), hashlib.sha256).hexdigest()


def test_valid_request_and_response_signature(client: BridgeClient) -> None:
    nonce = secrets.token_hex(16)
    hdrs = signed_headers("GET", "/v1/health", b"", client.clock(), nonce)
    resp = client.client.get("/v1/health", headers=hdrs)
    assert resp.status_code == 200
    sig = resp.headers["X-FX-Signature"]
    assert sig == sign_response(SECRET.encode(), nonce, 200, resp.content)
    assert resp.headers["X-Request-ID"]


def test_missing_headers_unauthorized(client: BridgeClient) -> None:
    resp = client.client.get("/v1/health")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
    # error responses are signed too (empty nonce when none was supplied)
    assert verify_response(SECRET.encode(), "", 401, resp.content, resp.headers["X-FX-Signature"])


def test_bad_signature(client: BridgeClient) -> None:
    hdrs = signed_headers("GET", "/v1/health", b"", client.clock(), secret="w" * 40)
    resp = client.client.get("/v1/health", headers=hdrs)
    assert resp.status_code == 401
    assert verify_response(
        SECRET.encode(), hdrs["X-FX-Nonce"], 401, resp.content, resp.headers["X-FX-Signature"]
    )


def test_signature_covers_query_and_body(client: BridgeClient) -> None:
    hdrs = signed_headers("GET", "/v1/deals?start=a", b"", client.clock())
    resp = client.client.get("/v1/deals?start=b", headers=hdrs)
    assert resp.status_code == 401
    body = b'{"login":"1"}'
    hdrs = signed_headers("POST", "/v1/session/connect", body, client.clock())
    resp = client.client.post("/v1/session/connect", content=b'{"login":"2"}', headers=hdrs)
    assert resp.status_code == 401


def test_stale_and_future_timestamp(client: BridgeClient) -> None:
    for delta in (-31, 31):
        hdrs = signed_headers("GET", "/v1/health", b"", client.clock() + delta)
        resp = client.client.get("/v1/health", headers=hdrs)
        assert resp.status_code == 401, delta
    hdrs = signed_headers("GET", "/v1/health", b"", client.clock() - 30)
    assert client.client.get("/v1/health", headers=hdrs).status_code == 200


def test_replayed_nonce(client: BridgeClient) -> None:
    hdrs = signed_headers("GET", "/v1/health", b"", client.clock())
    assert client.client.get("/v1/health", headers=hdrs).status_code == 200
    resp = client.client.get("/v1/health", headers=hdrs)
    assert resp.status_code == 401
    assert "Nonce" in resp.json()["error"]["message"]


def test_malformed_nonce(client: BridgeClient) -> None:
    hdrs = signed_headers("GET", "/v1/health", b"", client.clock(), nonce="ABC")
    assert client.client.get("/v1/health", headers=hdrs).status_code == 401


def test_nonce_cache_expiry() -> None:
    clock = FakeClock()
    cache = NonceCache(120, clock)
    assert cache.check_and_add("a" * 32)
    assert not cache.check_and_add("a" * 32)
    clock.advance(121)
    assert cache.check_and_add("a" * 32)


def test_ip_allowlist(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock)
    for allowed, expected in (("10.0.0.5", 401), ("testclient", 200)):
        if allowed == "testclient":
            # starlette's TestClient reports the client host as "testclient"; allow all
            settings = make_settings(tmp_path, bridge_allowed_ips="")
        else:
            settings = make_settings(tmp_path, bridge_allowed_ips=allowed)
        app = create_app(settings, mt5_module=fake, clock=clock)
        with TestClient(app) as tc:
            resp = BridgeClient(tc, clock).get("/v1/health")
            assert resp.status_code == expected


def test_ip_allowlist_cidr_match(tmp_path: Path, clock: FakeClock) -> None:
    settings = make_settings(tmp_path, bridge_allowed_ips="192.168.1.0/24, 10.0.0.1")
    app = create_app(settings, mt5_module=FakeMT5(clock=clock), clock=clock)
    with TestClient(app, client=("192.168.1.77", 5000)) as tc:
        assert BridgeClient(tc, clock).get("/v1/health").status_code == 200
    with TestClient(app, client=("192.168.2.1", 5000)) as tc:
        assert BridgeClient(tc, clock).get("/v1/health").status_code == 401


def test_body_size_limit(client: BridgeClient) -> None:
    big = b'{"x":"' + b"a" * (64 * 1024) + b'"}'
    resp = client.post("/v1/orders", raw=big)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


def test_unknown_route_is_signed_404(client: BridgeClient) -> None:
    resp = client.get("/v1/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_settings_require_long_secret(tmp_path: Path) -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_settings(tmp_path, bridge_secret="short")
