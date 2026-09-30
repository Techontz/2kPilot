from __future__ import annotations

from datetime import datetime

from . import fake_mt5 as f
from .conftest import BridgeClient
from .fake_mt5 import FakeMT5

COID = "fx0123456789abcdefghijkl"


def _server(fake: FakeMT5, iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) + fake.server_offset


def test_positions_mapping(client: BridgeClient, fake: FakeMT5) -> None:
    fake.add_position(
        ticket=123456789,
        comment=COID,
        sl=1.082,
        tp=1.091,
        profit=12.5,
        price_open=1.085,
        time=_server(fake, "2026-10-01T09:30:00Z"),
    )
    body = client.get("/v1/positions").json()
    assert body == [
        {
            "position_id": "123456789",
            "symbol": "EURUSD",
            "side": "BUY",
            "volume": "0.10",
            "open_price": "1.08500",
            "open_time": "2026-10-01T09:30:00Z",
            "stop_loss": "1.08200",
            "take_profit": "1.09100",
            "unrealized_pnl": "12.50",
            "swap": "0.00",
            "client_order_id": COID,
        }
    ]


def test_positions_client_order_id_recovery(client: BridgeClient, fake: FakeMT5) -> None:
    # comment lost on the position, but present on the opening deal
    p1 = fake.add_position(comment="", type=f.POSITION_TYPE_SELL, symbol="USDJPY", price_open=149.5)
    fake.add_deal(position_id=p1.identifier, entry=f.DEAL_ENTRY_IN, comment="abcdefgh12")
    # a manual position with a broker-rewritten comment
    fake.add_position(comment="[sl 1.08000]")
    # comment with a trailing user note
    fake.add_position(comment="zz99zz99zz note")
    body = client.get("/v1/positions").json()
    assert [p["client_order_id"] for p in body] == ["abcdefgh12", None, "zz99zz99zz"]
    assert body[0]["side"] == "SELL"
    assert body[0]["open_price"] == "149.500"
    assert body[0]["stop_loss"] is None


def test_orders_mapping(client: BridgeClient, fake: FakeMT5) -> None:
    resp = client.post(
        "/v1/orders",
        {
            "client_order_id": "pend0001",
            "symbol": "EURUSD",
            "side": "BUY",
            "order_type": "LIMIT",
            "volume": "0.10",
            "price": "1.08000",
            "stop_loss": "1.07700",
            "take_profit": "1.08600",
        },
    )
    assert resp.status_code == 200, resp.text
    body = client.get("/v1/orders").json()
    assert body == [
        {
            "order_id": resp.json()["broker_order_id"],
            "symbol": "EURUSD",
            "side": "BUY",
            "order_type": "LIMIT",
            "volume": "0.10",
            "status": "PENDING",
            "price": "1.08000",
            "stop_loss": "1.07700",
            "take_profit": "1.08600",
            "created_time": "2026-10-01T13:00:05Z",
            "client_order_id": "pend0001",
        }
    ]


def test_deals_mapping_and_bounds(client: BridgeClient, fake: FakeMT5) -> None:
    t_in = _server(fake, "2026-10-01T08:00:00Z")
    t_out = _server(fake, "2026-10-01T10:00:00Z")
    fake.add_deal(
        ticket=554,
        order=986,
        position_id=123456789,
        time=t_in,
        entry=f.DEAL_ENTRY_IN,
        type=f.DEAL_TYPE_BUY,
        comment=COID,
        reason=f.DEAL_REASON_EXPERT,
        price=1.085,
        commission=-0.7,
    )
    fake.add_deal(
        ticket=555,
        order=987,
        position_id=123456789,
        time=t_out,
        entry=f.DEAL_ENTRY_OUT,
        type=f.DEAL_TYPE_SELL,
        comment="[tp 1.09100]",
        reason=f.DEAL_REASON_TP,
        price=1.091,
        profit=60.0,
        commission=-0.7,
    )
    fake.add_deal(ticket=556, type=f.DEAL_TYPE_BALANCE, time=t_in, comment="deposit")
    fake.add_deal(ticket=557, time=_server(fake, "2026-10-01T12:00:00Z"), reason=1)
    fake.add_deal(
        ticket=558, time=_server(fake, "2026-10-01T11:00:00Z"), reason=7, entry=f.DEAL_ENTRY_INOUT
    )

    resp = client.get("/v1/deals?start=2026-10-01T08:00:00Z&end=2026-10-01T12:00:00Z")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [d["deal_id"] for d in body] == ["554", "555", "558"]  # end exclusive, no balance
    assert body[1] == {
        "deal_id": "555",
        "order_id": "987",
        "position_id": "123456789",
        "symbol": "EURUSD",
        "side": "SELL",
        "entry": "OUT",
        "volume": "0.10",
        "price": "1.09100",
        "time": "2026-10-01T10:00:00Z",
        "profit": "60.00",
        "commission": "-0.70",
        "swap": "0.00",
        "fee": "0.00",
        "client_order_id": None,
        "reason": "TP",
    }
    assert body[0]["client_order_id"] == COID
    assert body[0]["reason"] == "EXPERT"
    assert body[2]["entry"] == "INOUT"
    assert body[2]["reason"] == "OTHER"
    resp = client.get("/v1/deals?start=2026-10-01T12:00:00Z&end=2026-10-01T13:00:00Z")
    assert [(d["deal_id"], d["reason"]) for d in resp.json()] == [("557", "CLIENT")]


def test_deal_reasons_sl_so() -> None:
    from mt5_bridge.mapping import deal_reason

    assert deal_reason(f.DEAL_REASON_SL) == "SL"
    assert deal_reason(f.DEAL_REASON_SO) == "SO"
    assert deal_reason(2) == "CLIENT"


def test_not_logged_in(client: BridgeClient, fake: FakeMT5) -> None:
    fake.logged_in = False
    for path in ("/v1/positions", "/v1/orders", "/v1/account", "/v1/symbols"):
        resp = client.get(path)
        assert resp.status_code == 503, path
        assert resp.json()["error"]["code"] == "not_connected"
