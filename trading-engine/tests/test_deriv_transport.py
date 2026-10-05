"""DerivSocket over a REAL local WebSocket server (the `websockets` library),
and DerivRest error handling. No Deriv servers are contacted."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from websockets.sync.server import ServerConnection, serve

from fxrobot.broker_engine.adapters.deriv_client import DerivApiError, DerivRest, DerivSocket
from fxrobot.broker_engine.errors import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerTimeoutError,
    InvalidBrokerResponseError,
)


def handler(ws: ServerConnection) -> None:
    for raw in ws:
        msg: dict[str, Any] = json.loads(raw)
        req_id = msg.get("req_id")
        if "ping" in msg:
            ws.send(json.dumps({"msg_type": "ping", "ping": "pong", "req_id": req_id}))
        elif "ticks" in msg:
            # reply, then two streamed updates with the same subscription
            ws.send(json.dumps({"msg_type": "tick", "tick": {"quote": 1}, "req_id": req_id}))
            ws.send(json.dumps({"msg_type": "tick", "tick": {"quote": 2}}))
            ws.send(json.dumps({"msg_type": "tick", "tick": {"quote": 3}}))
        elif "slow" in msg:
            pass  # never answers
        elif "bye" in msg:
            ws.close()
            return
        else:
            ws.send(
                json.dumps(
                    {
                        "msg_type": "buy",
                        "error": {
                            "code": "ContractBuyValidationError",
                            "message": "Market closed",
                            "subcode": "MarketIsClosed",
                        },
                        "req_id": req_id,
                    }
                )
            )


@pytest.fixture
def ws_url() -> Iterator[str]:
    server = serve(handler, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.socket.getsockname()[:2]
    yield f"ws://{host}:{port}/ws/demo?otp=abc"
    server.shutdown()


def test_requests_are_matched_by_req_id(ws_url: str) -> None:
    sock = DerivSocket(ws_url)
    try:
        assert sock.request({"ping": 1})["ping"] == "pong"
        assert sock.request({"ping": 1})["ping"] == "pong"
    finally:
        sock.close()


def test_stream_messages_reach_handlers(ws_url: str) -> None:
    sock = DerivSocket(ws_url)
    seen: list[int] = []
    done = threading.Event()

    def on_tick(message: dict[str, Any]) -> None:
        seen.append(message["tick"]["quote"])
        if len(seen) == 3:
            done.set()

    sock.on("tick", on_tick)
    try:
        assert sock.request({"ticks": "R_100", "subscribe": 1})["tick"]["quote"] == 1
        assert done.wait(2)
        assert seen == [1, 2, 3]
    finally:
        sock.close()


def test_api_errors_carry_code_and_subcode(ws_url: str) -> None:
    sock = DerivSocket(ws_url)
    try:
        with pytest.raises(DerivApiError) as info:
            sock.request({"buy": "x", "price": 1})
        assert info.value.deriv_code == "ContractBuyValidationError"
        assert info.value.subcode == "MarketIsClosed"
    finally:
        sock.close()


def test_timeouts_and_lost_connections(ws_url: str) -> None:
    sock = DerivSocket(ws_url)
    with pytest.raises(BrokerTimeoutError):
        sock.request({"slow": 1}, timeout=0.3)
    with pytest.raises(BrokerConnectionError):
        sock.request({"bye": 1}, timeout=2)
    assert not sock.is_open
    with pytest.raises(BrokerConnectionError):
        sock.request({"ping": 1})


def _rest(handler_fn: Any) -> DerivRest:
    return DerivRest(token="t", app_id="app1", transport=httpx.MockTransport(handler_fn))


def test_rest_maps_http_errors() -> None:
    unauthorized = _rest(
        lambda r: httpx.Response(401, json={"errors": [{"code": "Unauthorized", "message": "bad"}]})
    )
    with pytest.raises(BrokerAuthError):
        unauthorized.accounts()
    limited = _rest(
        lambda r: httpx.Response(
            429, json={"errors": [{"code": "RateLimit", "message": "slow down"}]}
        )
    )
    with pytest.raises(BrokerConnectionError, match="rate limit"):
        limited.accounts()
    garbage = _rest(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(InvalidBrokerResponseError):
        garbage.accounts()


def test_rest_sends_app_id_only_for_pats() -> None:
    seen: dict[str, str | None] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen["app"] = request.headers.get("Deriv-App-ID")
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": []})

    DerivRest(token="t", app_id="app1", transport=httpx.MockTransport(capture)).accounts()
    assert seen == {"app": "app1", "auth": "Bearer t"}
    DerivRest(
        token="o", app_id="", token_kind="oauth", transport=httpx.MockTransport(capture)
    ).accounts()
    assert seen == {"app": None, "auth": "Bearer o"}


def test_otp_url_must_be_secure_websocket() -> None:
    bad = _rest(lambda r: httpx.Response(200, json={"data": {"url": "http://evil"}}))
    with pytest.raises(InvalidBrokerResponseError):
        bad.otp_url("DOT1")
