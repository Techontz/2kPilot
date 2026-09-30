from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mt5_bridge.app import create_app
from mt5_bridge.auth import sign_request, verify_response
from mt5_bridge.config import Settings

from .fake_mt5 import FakeMT5

SECRET = "test-secret-" + "x" * 40
# Thursday 2026-10-01 13:00:05 UTC — FX market open
NOW = datetime(2026, 10, 1, 13, 0, 5, tzinfo=UTC).timestamp()


class FakeClock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "bridge_secret": SECRET,
        "journal_path": str(tmp_path / "journal.sqlite3"),
        "read_timeout_seconds": 2.0,
        "trade_timeout_seconds": 2.0,
        "connect_timeout_seconds": 2.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def signed_headers(
    method: str,
    path_with_query: str,
    body: bytes,
    ts: float,
    nonce: str | None = None,
    secret: str = SECRET,
) -> dict[str, str]:
    nonce = nonce or secrets.token_hex(16)
    stamp = str(int(ts))
    sig = sign_request(secret.encode(), method, path_with_query, stamp, nonce, body)
    return {
        "X-FX-Timestamp": stamp,
        "X-FX-Nonce": nonce,
        "X-FX-Signature": sig,
        "Content-Type": "application/json",
    }


class BridgeClient:
    """Signs every request and verifies every response signature."""

    def __init__(self, client: TestClient, clock: FakeClock) -> None:
        self.client = client
        self.clock = clock

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
        verify: bool = True,
    ) -> httpx.Response:
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        hdrs = signed_headers(method, path, data, self.clock())
        if headers:
            hdrs.update(headers)
        resp: httpx.Response = self.client.request(method, path, content=data, headers=hdrs)
        if verify:
            assert verify_response(
                SECRET.encode(),
                hdrs["X-FX-Nonce"],
                resp.status_code,
                resp.content,
                resp.headers["X-FX-Signature"],
            )
        return resp

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> httpx.Response:
        return self.request("POST", path, body=body, **kw)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake(clock: FakeClock) -> FakeMT5:
    return FakeMT5(clock=clock)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path, broker_server_utc_offset="+3")


@pytest.fixture
def app(settings: Settings, fake: FakeMT5, clock: FakeClock) -> FastAPI:
    return create_app(settings, mt5_module=fake, clock=clock)


@pytest.fixture
def client(app: FastAPI, clock: FakeClock) -> Iterator[BridgeClient]:
    with TestClient(app) as tc:
        yield BridgeClient(tc, clock)


def order_body(coid: str = "fx0123456789abcdefghijkl", **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "client_order_id": coid,
        "symbol": "EURUSD",
        "side": "BUY",
        "order_type": "MARKET",
        "volume": "0.10",
        "price": None,
        "stop_loss": "1.08200",
        "take_profit": "1.09100",
        "max_slippage_points": 20,
        "comment": "",
    }
    body.update(kw)
    return body
