from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mt5_bridge.app import create_app

from . import fake_mt5 as f
from .conftest import BridgeClient, FakeClock, make_settings
from .fake_mt5 import FakeMT5


def _epoch(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _client(tmp_path: Path, fake: FakeMT5, clock: FakeClock, **kw: object) -> TestClient:
    settings = make_settings(tmp_path, **kw)
    return TestClient(create_app(settings, mt5_module=fake, clock=clock))


# ---------------------------------------------------------------- health / session
def test_health(client: BridgeClient) -> None:
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok",
        "bridge_version": "1.0.0",
        "terminal": {
            "initialized": True,
            "connected": True,
            "login": "5012345",
            "server": "MetaQuotes-Demo",
            "trade_allowed": True,
            "build": 4410,
        },
        "server_utc_offset_seconds": 10800,
        "time": "2026-10-01T13:00:05Z",
    }


def test_health_ok_when_terminal_unavailable(client: BridgeClient, fake: FakeMT5) -> None:
    fake.initialize_ok = False
    body = client.get("/v1/health").json()
    assert body["status"] == "ok"
    assert body["terminal"]["initialized"] is False
    assert body["terminal"]["connected"] is False


def test_health_disconnected_from_trade_server(client: BridgeClient, fake: FakeMT5) -> None:
    fake.connected = False
    body = client.get("/v1/health").json()
    assert body["terminal"]["initialized"] is True
    assert body["terminal"]["connected"] is False
    resp = client.get("/v1/account")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not_connected"


def test_package_missing(tmp_path: Path, clock: FakeClock) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, clock=clock)) as tc:  # no MetaTrader5 on this host
        bc = BridgeClient(tc, clock)
        assert bc.get("/v1/health").json()["terminal"]["initialized"] is False
        resp = bc.get("/v1/account")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "not_connected"


def test_connect_success(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post(
        "/v1/session/connect",
        {
            "login": "5012345",
            "password": "correct-horse",
            "server": "MetaQuotes-Demo",
            "terminal_path": None,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["account_id"] == "5012345"
    assert fake.login_calls == [(5012345, "MetaQuotes-Demo")]


def test_connect_wrong_password_on_initialize(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post(
        "/v1/session/connect", {"login": "5012345", "password": "nope", "server": "MetaQuotes-Demo"}
    )
    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "broker_auth_failed"
    assert err["broker_code"] == "-6"
    assert "nope" not in resp.text


def test_connect_wrong_server_via_login(client: BridgeClient, fake: FakeMT5) -> None:
    assert client.get("/v1/health").status_code == 200  # initialises the terminal
    resp = client.post(
        "/v1/session/connect",
        {"login": "5012345", "password": "correct-horse", "server": "Wrong-Server"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "broker_auth_failed"


def test_connect_terminal_missing(client: BridgeClient, fake: FakeMT5) -> None:
    fake.initialize_ok = False
    resp = client.post(
        "/v1/session/connect",
        {"login": "5012345", "password": "correct-horse", "server": "MetaQuotes-Demo"},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not_connected"


def test_connect_invalid_login(client: BridgeClient) -> None:
    resp = client.post("/v1/session/connect", {"login": "abc", "password": "x", "server": "s"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"


def test_password_never_logged(client: BridgeClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG", logger="mt5_bridge")
    client.post(
        "/v1/session/connect",
        {"login": "5012345", "password": "correct-horse", "server": "MetaQuotes-Demo"},
    )
    client.post(
        "/v1/session/connect",
        {"login": "5012345", "password": "wrong-horse-pw", "server": "MetaQuotes-Demo"},
    )
    assert "correct-horse" not in caplog.text
    assert "wrong-horse-pw" not in caplog.text


def test_disconnect(client: BridgeClient, fake: FakeMT5) -> None:
    client.get("/v1/health")
    resp = client.post("/v1/session/disconnect")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert fake._initialized is False


# ---------------------------------------------------------------- account
@pytest.mark.parametrize(
    ("mode", "env"),
    [
        (f.ACCOUNT_TRADE_MODE_DEMO, "DEMO"),
        (f.ACCOUNT_TRADE_MODE_REAL, "LIVE"),
        (f.ACCOUNT_TRADE_MODE_CONTEST, "UNKNOWN"),
        (7, "UNKNOWN"),
    ],
)
def test_account_environment(client: BridgeClient, fake: FakeMT5, mode: int, env: str) -> None:
    fake.trade_mode = mode
    body = client.get("/v1/account").json()
    assert body["environment"] == env


def test_account_shape(client: BridgeClient, fake: FakeMT5) -> None:
    fake.add_position(profit=12.5, volume=0.1, price_open=1.0851)
    body = client.get("/v1/account").json()
    assert body == {
        "account_id": "5012345",
        "name": "Conrad",
        "server": "MetaQuotes-Demo",
        "currency": "USD",
        "environment": "DEMO",
        "balance": "10000.00",
        "equity": "10012.50",
        "margin": "108.51",
        "free_margin": "9903.99",
        "margin_level": "9227.26",
        "leverage": 100,
        "trade_allowed": True,
    }


# ---------------------------------------------------------------- symbols / quotes
def test_symbols(client: BridgeClient) -> None:
    body = client.get("/v1/symbols").json()
    names = [s["name"] for s in body]
    assert names == ["EURUSD", "USDJPY", "XAUUSD"]  # hidden, CFD and disabled excluded
    eur = body[0]
    assert eur == {
        "name": "EURUSD",
        "description": "Euro vs US Dollar",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "digits": 5,
        "point": "0.00001",
        "contract_size": "100000",
        "volume_min": "0.01",
        "volume_max": "100",
        "volume_step": "0.01",
        "trade_allowed": True,
        "point_value": "1.00",
    }
    assert body[1]["point_value"] == "0.6689"
    assert body[2]["point_value"] == "1.00"


def test_quote(client: BridgeClient) -> None:
    body = client.get("/v1/quotes/EURUSD").json()
    assert body == {
        "symbol": "EURUSD",
        "bid": "1.08500",
        "ask": "1.08512",
        "time": "2026-10-01T13:00:04Z",
    }


def test_quote_selects_hidden_symbol(client: BridgeClient, fake: FakeMT5) -> None:
    assert client.get("/v1/quotes/GBPUSD").status_code == 200
    assert fake.symbols["GBPUSD"].visible


def test_quote_unknown_symbol(client: BridgeClient) -> None:
    resp = client.get("/v1/quotes/NOPE")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "symbol_unavailable"


def test_quote_invalid_symbol(client: BridgeClient) -> None:
    resp = client.get("/v1/quotes/EUR%20USD")
    assert resp.status_code == 422


# ---------------------------------------------------------------- candles
def _add_h1(fake: FakeMT5, offset: int) -> None:
    first = _epoch("2026-10-01T00:00:00Z") + offset
    fake.add_bars("EURUSD", f.TIMEFRAME_H1, 3600, first, 14)  # 00:00 .. 13:00 UTC


def test_candles_closed_only_and_bounds(client: BridgeClient, fake: FakeMT5) -> None:
    _add_h1(fake, 10800)
    resp = client.get(
        "/v1/candles?symbol=EURUSD&timeframe=H1&start=2026-10-01T02:00:00Z&end=2026-10-01T14:00:00Z"
    )
    assert resp.status_code == 200, resp.text
    bars = resp.json()
    times = [b["time"] for b in bars]
    assert times[0] == "2026-10-01T02:00:00Z"
    assert times[-1] == "2026-10-01T12:00:00Z"  # 13:00 bar is still forming
    assert len(bars) == 11
    assert bars[0] == {
        "time": "2026-10-01T02:00:00Z",
        "open": "1.08010",
        "high": "1.08060",
        "low": "1.07990",
        "close": "1.08030",
        "tick_volume": 102,
        "spread_points": 9,
    }

    resp = client.get(
        "/v1/candles?symbol=EURUSD&timeframe=H1&start=2026-10-01T02:00:00Z&end=2026-10-01T05:00:00Z"
    )
    assert [b["time"][11:16] for b in resp.json()] == ["02:00", "03:00", "04:00"]


def test_candles_validation(client: BridgeClient) -> None:
    base = "/v1/candles?symbol=EURUSD"
    for q in (
        "&timeframe=H2&start=2026-10-01T00:00:00Z&end=2026-10-01T01:00:00Z",
        "&timeframe=H1&start=2026-10-01T00:00:00&end=2026-10-01T01:00:00Z",
        "&timeframe=H1&start=2026-10-01T02:00:00Z&end=2026-10-01T01:00:00Z",
        "&timeframe=H1&start=2026-10-01T02:00:00Z",
    ):
        resp = client.get(base + q)
        assert resp.status_code == 422, q
        assert resp.json()["error"]["code"] == "invalid_request"


def test_candles_fixed_offset_other_value(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock, server_offset=7200)
    _add_h1(fake, 7200)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="+2") as tc:
        bars = (
            BridgeClient(tc, clock)
            .get(
                "/v1/candles?symbol=EURUSD&timeframe=H1"
                "&start=2026-10-01T00:00:00Z&end=2026-10-01T02:00:00Z"
            )
            .json()
        )
        assert [b["time"] for b in bars] == ["2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z"]


def test_candles_auto_offset(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock, server_offset=10800)
    _add_h1(fake, 10800)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        bc = BridgeClient(tc, clock)
        assert bc.get("/v1/health").json()["server_utc_offset_seconds"] == 10800
        bars = bc.get(
            "/v1/candles?symbol=EURUSD&timeframe=H1"
            "&start=2026-10-01T00:00:00Z&end=2026-10-01T01:00:00Z"
        ).json()
        assert [b["time"] for b in bars] == ["2026-10-01T00:00:00Z"]


def test_auto_offset_rounds_to_half_hour(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock, server_offset=int(5.5 * 3600), tick_lag=40)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        assert (
            BridgeClient(tc, clock).get("/v1/health").json()["server_utc_offset_seconds"] == 19800
        )


def test_auto_offset_unknown_when_market_closed(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 10, 3, 12, 0, tzinfo=UTC).timestamp())  # Saturday
    fake = FakeMT5(clock=clock, tick_lag=26 * 3600)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        bc = BridgeClient(tc, clock)
        assert bc.get("/v1/health").json()["server_utc_offset_seconds"] is None
        for path in (
            "/v1/candles?symbol=EURUSD&timeframe=H1"
            "&start=2026-10-01T00:00:00Z&end=2026-10-01T01:00:00Z",
            "/v1/deals?start=2026-10-01T00:00:00Z&end=2026-10-02T00:00:00Z",
        ):
            resp = bc.get(path)
            assert resp.status_code == 503
            assert resp.json()["error"] == {
                "code": "not_connected",
                "message": "server time offset unknown",
            }
        # positions still work (times reported with offset 0 until known)
        assert bc.get("/v1/positions").status_code == 200


def test_auto_offset_stale_tick_rejected(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock, tick_lag=600)  # market "open" by calendar but no fresh tick
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        assert BridgeClient(tc, clock).get("/v1/health").json()["server_utc_offset_seconds"] is None


def test_auto_offset_persisted_across_restart(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        assert (
            BridgeClient(tc, clock).get("/v1/health").json()["server_utc_offset_seconds"] == 10800
        )
    clock.now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC).timestamp()  # weekend
    fake.tick_lag = 26 * 3600
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        resp = BridgeClient(tc, clock).get(
            "/v1/deals?start=2026-10-01T00:00:00Z&end=2026-10-02T00:00:00Z"
        )
        assert resp.status_code == 200


def test_auto_offset_remeasured_hourly(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock, server_offset=10800)
    with _client(tmp_path, fake, clock, broker_server_utc_offset="auto") as tc:
        bc = BridgeClient(tc, clock)
        assert bc.get("/v1/health").json()["server_utc_offset_seconds"] == 10800
        fake.server_offset = 7200  # DST change
        clock.advance(1800)
        assert bc.get("/v1/health").json()["server_utc_offset_seconds"] == 10800
        clock.advance(1801)
        assert bc.get("/v1/health").json()["server_utc_offset_seconds"] == 7200
