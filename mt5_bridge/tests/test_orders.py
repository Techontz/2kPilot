from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mt5_bridge.app import create_app
from mt5_bridge.journal import DONE, UNKNOWN, Journal

from . import fake_mt5 as f
from .conftest import BridgeClient, FakeClock, make_settings, order_body
from .fake_mt5 import FakeMT5, SendBehaviour

COID = "fx0123456789abcdefghijkl"


def _journal_state(settings_path: str, coid: str) -> str | None:
    j = Journal(settings_path)
    try:
        e = j.get(coid)
        return None if e is None else e.state
    finally:
        j.close()


@pytest.fixture
def journal_path(tmp_path: Path) -> str:
    return str(tmp_path / "journal.sqlite3")


# ---------------------------------------------------------------- submission
def test_market_order_filled(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    order_ticket = body["broker_order_id"]
    assert body == {
        "client_order_id": COID,
        "status": "FILLED",
        "broker_order_id": order_ticket,
        "broker_position_id": order_ticket,
        "filled_volume": "0.10",
        "fill_price": "1.08512",
        "broker_code": "10009",
        "broker_message": "Request executed",
    }
    req = fake.order_send_calls[0]
    assert req["action"] == f.TRADE_ACTION_DEAL
    assert req["type"] == f.ORDER_TYPE_BUY
    assert req["price"] == 1.08512  # ask for BUY
    assert req["deviation"] == 20
    assert req["comment"] == COID
    assert req["magic"] == 20250
    assert req["type_filling"] == f.ORDER_FILLING_FOK
    assert req["sl"] == 1.082
    assert req["tp"] == 1.091
    assert req["volume"] == 0.1


def test_sell_uses_bid_and_comment_with_note(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post(
        "/v1/orders",
        order_body(side="SELL", stop_loss="1.09000", take_profit="1.08000", comment="breakout v2"),
    )
    assert resp.status_code == 200, resp.text
    req = fake.order_send_calls[0]
    assert req["price"] == 1.085
    assert req["comment"] == f"{COID} breako"  # truncated to 31 chars
    positions = client.get("/v1/positions").json()
    assert positions[0]["client_order_id"] == COID


@pytest.mark.parametrize(
    ("symbol", "filling"), [("GBPUSD", f.ORDER_FILLING_IOC), ("EURUSD", f.ORDER_FILLING_FOK)]
)
def test_filling_mode_selection(
    client: BridgeClient, fake: FakeMT5, symbol: str, filling: int
) -> None:
    client.post("/v1/orders", order_body(symbol=symbol, stop_loss=None, take_profit=None))
    assert fake.order_send_calls[0]["type_filling"] == filling


def test_filling_mode_return_fallback() -> None:
    from mt5_bridge.mapping import select_filling

    assert select_filling(0) == f.ORDER_FILLING_RETURN
    assert select_filling(3) == f.ORDER_FILLING_FOK
    assert select_filling(2) == f.ORDER_FILLING_IOC


def test_partial_fill(client: BridgeClient, fake: FakeMT5) -> None:
    fake.send_behaviours.append(SendBehaviour(fill_ratio=0.5))
    body = client.post("/v1/orders", order_body()).json()
    assert body["status"] == "PARTIALLY_FILLED"
    assert body["filled_volume"] == "0.05"
    assert body["broker_code"] == "10010"


def test_pending_limit_order(client: BridgeClient, fake: FakeMT5) -> None:
    body = client.post(
        "/v1/orders",
        order_body(order_type="LIMIT", price="1.08000", stop_loss="1.07700", take_profit="1.08600"),
    ).json()
    assert body["status"] == "PENDING"
    assert body["broker_code"] == "10008"
    assert body["fill_price"] is None
    assert body["broker_position_id"] is None
    assert body["filled_volume"] == "0.00"
    req = fake.order_send_calls[0]
    assert req["action"] == f.TRADE_ACTION_PENDING
    assert req["type"] == f.ORDER_TYPE_BUY_LIMIT
    assert req["price"] == 1.08


def test_pending_stop_sell(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post(
        "/v1/orders",
        order_body(
            side="SELL",
            order_type="STOP",
            price="1.08000",
            stop_loss="1.08300",
            take_profit="1.07500",
        ),
    )
    assert resp.json()["status"] == "PENDING"
    assert fake.order_send_calls[0]["type"] == f.ORDER_TYPE_SELL_STOP


@pytest.mark.parametrize(
    "patch",
    [
        {"order_type": "LIMIT", "price": None},
        {"volume": "0"},
        {"volume": "abc"},
        {"side": "LONG"},
        {"client_order_id": "FX-UPPER-1"},
        {"client_order_id": "short"},
        {"client_order_id": "a" * 25},
        {"symbol": "EUR USD"},
    ],
)
def test_invalid_requests(client: BridgeClient, fake: FakeMT5, patch: dict[str, Any]) -> None:
    resp = client.post("/v1/orders", order_body(**patch))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_request"
    assert fake.order_send_calls == []


def test_malformed_json(client: BridgeClient) -> None:
    resp = client.post("/v1/orders", raw=b"{not json")
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("setup", "status", "code", "broker_code"),
    [
        ({"volume": "50"}, 409, "insufficient_margin", "10019"),
        ({"stop_loss": "1.09000"}, 409, "rejected", "10016"),
        ({"volume": "500"}, 409, "rejected", "10014"),
    ],
)
def test_retcode_errors(
    client: BridgeClient,
    fake: FakeMT5,
    setup: dict[str, Any],
    status: int,
    code: str,
    broker_code: str,
) -> None:
    resp = client.post("/v1/orders", order_body(**setup))
    assert resp.status_code == status
    err = resp.json()["error"]
    assert err["code"] == code
    assert err["broker_code"] == broker_code
    assert fake.positions == {}


def test_market_closed(client: BridgeClient, fake: FakeMT5) -> None:
    fake.market_closed = True
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 409
    assert resp.json()["error"] == {
        "code": "market_closed",
        "message": "Market is closed",
        "broker_code": "10018",
    }


def test_other_retcode_rejected(client: BridgeClient, fake: FakeMT5) -> None:
    fake.send_behaviours.append(SendBehaviour(retcode=10004))
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "rejected"
    assert resp.json()["error"]["broker_code"] == "10004"


def test_unknown_symbol(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post("/v1/orders", order_body(symbol="NOPE"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "symbol_unavailable"
    assert fake.order_send_calls == []


# ---------------------------------------------------------------- idempotency
def test_duplicate_returns_stored_result(client: BridgeClient, fake: FakeMT5) -> None:
    first = client.post("/v1/orders", order_body())
    second = client.post("/v1/orders", order_body())
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(fake.order_send_calls) == 1
    assert len(fake.positions) == 1


def test_duplicate_of_rejected_returns_stored_error(client: BridgeClient, fake: FakeMT5) -> None:
    fake.market_closed = True
    first = client.post("/v1/orders", order_body())
    fake.market_closed = False
    second = client.post("/v1/orders", order_body())
    assert first.status_code == second.status_code == 409
    assert first.json() == second.json()
    assert len(fake.order_send_calls) == 1
    lookup = client.get(f"/v1/orders/lookup/{COID}").json()
    assert lookup["status"] == "REJECTED"
    assert lookup["broker_code"] == "10018"


def test_journal_survives_restart(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock)
    settings = make_settings(tmp_path, broker_server_utc_offset="+3")
    with TestClient(create_app(settings, mt5_module=fake, clock=clock)) as tc:
        first = BridgeClient(tc, clock).post("/v1/orders", order_body())
    assert first.status_code == 200
    with TestClient(create_app(settings, mt5_module=fake, clock=clock)) as tc:
        second = BridgeClient(tc, clock).post("/v1/orders", order_body())
    assert second.json() == first.json()
    assert len(fake.order_send_calls) == 1


def test_pre_send_failure_allows_retry(client: BridgeClient, fake: FakeMT5) -> None:
    fake.connected = False
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "not_connected"
    fake.connected = True
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 200
    assert len(fake.order_send_calls) == 1


def test_same_id_for_different_operation(client: BridgeClient, fake: FakeMT5) -> None:
    body = client.post("/v1/orders", order_body()).json()
    resp = client.post(
        f"/v1/positions/{body['broker_position_id']}/close",
        {"client_order_id": COID, "volume": None},
    )
    assert resp.status_code == 422
    assert len(fake.order_send_calls) == 1


# ---------------------------------------------------------------- unknown outcome
def test_none_result_executed_then_recovered(
    client: BridgeClient, fake: FakeMT5, settings: Any
) -> None:
    fake.send_behaviours.append(SendBehaviour(return_none=True, execute=True))
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"
    assert _journal_state(settings.journal_path, COID) == UNKNOWN

    again = client.post("/v1/orders", order_body())
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["status"] == "FILLED"
    assert body["filled_volume"] == "0.10"
    assert body["fill_price"] == "1.08512"
    assert len(fake.order_send_calls) == 1  # never resent
    assert _journal_state(settings.journal_path, COID) == DONE
    assert client.get(f"/v1/orders/lookup/{COID}").json() == body


def test_none_result_not_executed_stays_unknown(client: BridgeClient, fake: FakeMT5) -> None:
    fake.send_behaviours.append(SendBehaviour(return_none=True, execute=False))
    assert client.post("/v1/orders", order_body()).status_code == 504
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"
    assert len(fake.order_send_calls) == 1
    resp = client.get(f"/v1/orders/lookup/{COID}")
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"


def test_retcode_timeout_is_unknown(client: BridgeClient, fake: FakeMT5, settings: Any) -> None:
    fake.send_behaviours.append(SendBehaviour(retcode=10012))
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 504
    assert resp.json()["error"] == {
        "code": "outcome_unknown",
        "message": "Request canceled by timeout",
        "broker_code": "10012",
    }
    assert _journal_state(settings.journal_path, COID) == UNKNOWN


def test_exception_and_disconnect_are_unknown(client: BridgeClient, fake: FakeMT5) -> None:
    fake.send_behaviours.append(SendBehaviour(raise_exc=True))
    assert client.post("/v1/orders", order_body()).json()["error"]["code"] == "outcome_unknown"
    fake.send_behaviours.append(SendBehaviour(disconnect=True))
    resp = client.post("/v1/orders", order_body(coid="other0001"))
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"
    # terminal reconnects lazily; lookup finds nothing → still unknown, never resent
    assert client.post("/v1/orders", order_body(coid="other0001")).status_code == 504
    assert len(fake.order_send_calls) == 2


def test_duplicate_unknown_while_terminal_down(client: BridgeClient, fake: FakeMT5) -> None:
    fake.send_behaviours.append(SendBehaviour(return_none=True, execute=True))
    client.post("/v1/orders", order_body())
    fake.connected = False
    resp = client.post("/v1/orders", order_body())
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"
    fake.connected = True
    assert client.post("/v1/orders", order_body()).json()["status"] == "FILLED"
    assert len(fake.order_send_calls) == 1


def test_trade_timeout_then_recovery(tmp_path: Path, clock: FakeClock) -> None:
    fake = FakeMT5(clock=clock)
    settings = make_settings(
        tmp_path, broker_server_utc_offset="+3", trade_timeout_seconds=0.5, read_timeout_seconds=5.0
    )
    fake.send_behaviours.append(SendBehaviour(delay=2.0))
    with TestClient(create_app(settings, mt5_module=fake, clock=clock)) as tc:
        bc = BridgeClient(tc, clock)
        resp = bc.post("/v1/orders", order_body())
        assert resp.status_code == 504
        assert resp.json()["error"]["code"] == "outcome_unknown"
        # a second order submitted while the worker is still busy times out before sending
        resp2 = bc.post("/v1/orders", order_body(coid="second001"))
        assert resp2.status_code == 504
        # the duplicate waits for the worker, then finds the executed order
        again = bc.post("/v1/orders", order_body())
        assert again.status_code == 200, again.text
        assert again.json()["status"] == "FILLED"
        time.sleep(0.1)
        assert len(fake.order_send_calls) == 1  # second001 was abandoned, never sent
        assert bc.get("/v1/orders/lookup/second001").status_code == 404
        # ...so it can safely be submitted again
        assert bc.post("/v1/orders", order_body(coid="second001")).status_code == 200
        assert len(fake.order_send_calls) == 2


# ---------------------------------------------------------------- lookup
def test_lookup_not_found(client: BridgeClient) -> None:
    resp = client.get("/v1/orders/lookup/abcdefgh1234")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_lookup_invalid_id(client: BridgeClient) -> None:
    assert client.get("/v1/orders/lookup/NOT-VALID").status_code == 422


def test_lookup_from_mt5_without_journal(client: BridgeClient, fake: FakeMT5) -> None:
    # placed by another bridge instance/journal: found in positions by comment
    fake.add_position(ticket=777, comment="zz00zz00zz", volume=0.2, price_open=1.0849)
    body = client.get("/v1/orders/lookup/zz00zz00zz").json()
    assert body["status"] == "FILLED"
    assert body["broker_position_id"] == "777"
    assert body["filled_volume"] == "0.20"
    assert body["fill_price"] == "1.08490"
    # found in deal history only
    fake.add_deal(order=901, position_id=902, comment="yy00yy00yy", volume=0.1, price=1.08)
    body = client.get("/v1/orders/lookup/yy00yy00yy").json()
    assert (body["status"], body["broker_order_id"], body["broker_position_id"]) == (
        "FILLED",
        "901",
        "902",
    )


def test_lookup_pending_and_cancelled(client: BridgeClient, fake: FakeMT5, settings: Any) -> None:
    placed = client.post(
        "/v1/orders",
        order_body(order_type="LIMIT", price="1.08000", stop_loss=None, take_profit=None),
    ).json()
    # simulate lost journal: delete the record, lookup must use MT5 pending orders
    j = Journal(settings.journal_path)
    j.delete(COID)
    j.close()
    body = client.get(f"/v1/orders/lookup/{COID}").json()
    assert body["status"] == "PENDING"
    assert body["broker_order_id"] == placed["broker_order_id"]
    client.post(f"/v1/orders/{placed['broker_order_id']}/cancel")
    body = client.get(f"/v1/orders/lookup/{COID}").json()
    assert body["status"] == "CANCELLED"


# ---------------------------------------------------------------- close / modify / cancel
def test_close_position_full_and_idempotent(client: BridgeClient, fake: FakeMT5) -> None:
    opened = client.post("/v1/orders", order_body()).json()
    pid = opened["broker_position_id"]
    fake.set_price("EURUSD", 1.08700)
    resp = client.post(
        f"/v1/positions/{pid}/close", {"client_order_id": "close0001", "volume": None}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "FILLED"
    assert body["broker_position_id"] == pid
    assert body["filled_volume"] == "0.10"
    assert body["fill_price"] == "1.08700"  # SELL at bid
    req = fake.order_send_calls[-1]
    assert req["position"] == int(pid)
    assert req["type"] == f.ORDER_TYPE_SELL
    assert req["comment"] == "close0001"
    assert fake.positions == {}
    again = client.post(
        f"/v1/positions/{pid}/close", {"client_order_id": "close0001", "volume": None}
    )
    assert again.json() == body
    assert len(fake.order_send_calls) == 2
    deals = client.get("/v1/deals?start=2026-10-01T00:00:00Z&end=2026-10-02T00:00:00Z").json()
    assert [d["entry"] for d in deals] == ["IN", "OUT"]
    assert deals[1]["client_order_id"] == "close0001"


def test_close_partial(client: BridgeClient, fake: FakeMT5) -> None:
    pid = client.post("/v1/orders", order_body()).json()["broker_position_id"]
    resp = client.post(
        f"/v1/positions/{pid}/close", {"client_order_id": "close0002", "volume": "0.04"}
    )
    assert resp.json()["filled_volume"] == "0.04"
    assert client.get("/v1/positions").json()[0]["volume"] == "0.06"


def test_close_errors(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post("/v1/positions/999/close", {"client_order_id": "close0003", "volume": None})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    pid = client.post("/v1/orders", order_body()).json()["broker_position_id"]
    resp = client.post(
        f"/v1/positions/{pid}/close", {"client_order_id": "close0003", "volume": "1.00"}
    )
    assert resp.status_code == 422
    # pre-send failures leave no journal record: a valid retry with the same id works
    resp = client.post(
        f"/v1/positions/{pid}/close", {"client_order_id": "close0003", "volume": None}
    )
    assert resp.status_code == 200


def test_close_unknown_outcome_recovered_from_history(client: BridgeClient, fake: FakeMT5) -> None:
    pid = client.post("/v1/orders", order_body()).json()["broker_position_id"]
    fake.send_behaviours.append(SendBehaviour(return_none=True, execute=True))
    body = {"client_order_id": "close0004", "volume": None}
    assert client.post(f"/v1/positions/{pid}/close", body).status_code == 504
    resp = client.post(f"/v1/positions/{pid}/close", body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "FILLED"
    assert resp.json()["broker_position_id"] == pid
    assert len(fake.order_send_calls) == 2


def test_modify_position(client: BridgeClient, fake: FakeMT5) -> None:
    pid = client.post("/v1/orders", order_body()).json()["broker_position_id"]
    resp = client.post(f"/v1/positions/{pid}/modify", {"stop_loss": "1.08300"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "FILLED"
    assert body["client_order_id"] == COID
    assert body["broker_position_id"] == pid
    pos = fake.positions[int(pid)]
    assert (pos.sl, pos.tp) == (1.083, 1.091)  # absent take_profit kept
    client.post(f"/v1/positions/{pid}/modify", {"stop_loss": None, "take_profit": "1.09500"})
    pos = fake.positions[int(pid)]
    assert (pos.sl, pos.tp) == (0.0, 1.095)  # explicit null removes
    assert fake.order_send_calls[-1]["action"] == f.TRADE_ACTION_SLTP


def test_modify_position_errors(client: BridgeClient, fake: FakeMT5) -> None:
    assert client.post("/v1/positions/42/modify", {"stop_loss": "1.0"}).status_code == 404
    assert client.post("/v1/positions/abc/modify", {"stop_loss": "1.0"}).status_code == 422
    pid = client.post("/v1/orders", order_body()).json()["broker_position_id"]
    fake.send_behaviours.append(SendBehaviour(retcode=10016))
    resp = client.post(f"/v1/positions/{pid}/modify", {"stop_loss": "1.09"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "rejected"
    fake.send_behaviours.append(SendBehaviour(return_none=True, execute=False))
    resp = client.post(f"/v1/positions/{pid}/modify", {"stop_loss": "1.08"})
    assert resp.status_code == 504
    assert resp.json()["error"]["code"] == "outcome_unknown"


def test_modify_and_cancel_order(client: BridgeClient, fake: FakeMT5) -> None:
    oid = client.post(
        "/v1/orders",
        order_body(order_type="LIMIT", price="1.08000", stop_loss="1.07700", take_profit="1.08600"),
    ).json()["broker_order_id"]
    resp = client.post(f"/v1/orders/{oid}/modify", {"price": "1.07900"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "PENDING"
    assert body["client_order_id"] == COID
    o = fake.orders[int(oid)]
    assert (o.price_open, o.sl, o.tp) == (1.079, 1.077, 1.086)
    assert fake.order_send_calls[-1]["action"] == f.TRADE_ACTION_MODIFY

    resp = client.post(f"/v1/orders/{oid}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CANCELLED"
    assert body["broker_order_id"] == oid
    assert fake.orders == {}
    assert client.post(f"/v1/orders/{oid}/cancel").status_code == 404
    assert client.post("/v1/orders/1/modify", {"price": "1.0"}).status_code == 404
