"""Manual tickets (the Trade page) go through the SAME risk engine and
execution engine as automated signals — no shortcut, idempotent per key."""

from __future__ import annotations

import secrets
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import OrderStatus, SignalSource, SignalStatus, TradeStatus
from fxrobot.models import Order, Signal, Trade, TradeEvent
from tests import factories
from tests.conftest import SignedClient
from tests.test_engine_pipeline import LOOSE_RISK, paper_broker
from tests.test_execution import step_until_open

PIP = Decimal("0.0001")


@pytest.fixture
def setup(client: SignedClient, db: Session, owner: uuid.UUID) -> dict[str, Any]:
    account = factories.paper_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    factories.resume_trading(db)
    broker = paper_broker(client, str(account.connection_id))
    step_until_open(broker)
    return {"account": account, "broker": broker, "owner": owner}


def ticket(setup: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    quote = setup["broker"].get_quote("EURUSD")
    side = overrides.pop("side", "BUY")
    entry = quote.ask if side == "BUY" else quote.bid
    sign = 1 if side == "BUY" else -1
    body = {
        "account_id": str(setup["account"].id),
        "symbol": "EURUSD",
        "side": side,
        "volume": "0.10",
        "stop_loss": str(entry - 20 * PIP * sign),
        "take_profit": str(entry + 40 * PIP * sign),
        "idempotency_key": secrets.token_hex(16),
        "actor_id": str(setup["owner"]),
        "actor_label": "owner@example.com",
    }
    body.update(overrides)
    return {k: v for k, v in body.items() if v is not None}


def count(db: Session, model: Any) -> int:
    db.expire_all()
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def test_preview_suggests_volume_and_shows_risk(
    client: SignedClient, setup: dict[str, Any]
) -> None:
    body = client.post("/internal/orders/preview", json=ticket(setup, volume=None)).json()
    assert body["approved"] is True, body["rejection_reason"]
    assert Decimal(body["suggested_volume"]) == Decimal(body["volume"]) > 0
    assert Decimal(body["reward_risk"]) == Decimal("2")
    assert Decimal(body["risk_amount"]) <= Decimal("50")  # 0.5% of 10 000
    assert body["symbol"]["name"] == "EURUSD"
    assert any("PAPER" in n for n in body["notes"])
    assert {c["rule"] for c in body["checks"]} >= {
        "Kill switch",
        "Stop loss required",
        "Position size",
    }


def test_preview_never_writes(client: SignedClient, db: Session, setup: dict[str, Any]) -> None:
    client.post("/internal/orders/preview", json=ticket(setup))
    assert count(db, Signal) == 0 and count(db, Order) == 0


def test_volume_above_the_risk_budget_is_rejected_with_a_hint(
    client: SignedClient, setup: dict[str, Any]
) -> None:
    body = client.post("/internal/orders/preview", json=ticket(setup, volume="0.90")).json()
    assert body["approved"] is False
    assert body["rejection_reason"].startswith("Position size:")
    assert "the most you can trade is" in body["rejection_reason"]


def test_submit_executes_through_the_execution_engine(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    response = client.post("/internal/orders", json=ticket(setup))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "EXECUTED"
    assert result["order"]["status"] == "FILLED" and result["order"]["is_simulated"] is True
    signal = db.get(Signal, uuid.UUID(result["signal_id"]))
    assert signal is not None and signal.source is SignalSource.MANUAL
    assert signal.strategy_version_id is None and signal.created_by == setup["owner"]
    trade = db.get(Trade, uuid.UUID(result["trade_id"]))
    assert trade is not None and trade.status is TradeStatus.OPEN and trade.is_simulated
    events = list(
        db.scalars(
            select(TradeEvent.event_type)
            .where(TradeEvent.signal_id == signal.id)
            .order_by(TradeEvent.id)
        )
    )
    assert events == [
        "SIGNAL_GENERATED",
        "RISK_APPROVED",
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "POSITION_OPENED",
    ]


def test_same_idempotency_key_never_opens_a_second_position(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    body = ticket(setup)
    first = client.post("/internal/orders", json=body).json()
    second = client.post("/internal/orders", json=body).json()
    assert first["signal_id"] == second["signal_id"]
    assert count(db, Order) == 1 and count(db, Trade) == 1


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ("kill_switch", "Kill switch"),
        ("platform_halt", "Kill switch"),
        ("disabled", "Account trading enabled"),
        ("wrong_stop", "Stop loss required"),
        ("live_account", "Operating mode"),
    ],
)
def test_risk_rejections_send_nothing(
    client: SignedClient, db: Session, setup: dict[str, Any], change: str, rule: str
) -> None:
    body = ticket(setup)
    account = setup["account"]
    if change == "kill_switch":
        factories.stop_trading(db)
    elif change == "platform_halt":
        factories.halt_platform(db)
    elif change == "disabled":
        db.refresh(account)
        account.trading_enabled = False
        db.commit()
    elif change == "wrong_stop":
        quote = setup["broker"].get_quote("EURUSD")
        body["stop_loss"] = str(quote.ask + 20 * PIP)
    elif change == "live_account":
        db.refresh(account)
        account.environment = AccountEnvironment.LIVE
        db.commit()
    result = client.post("/internal/orders", json=body).json()
    assert result["status"] == "REJECTED"
    assert rule in result["rejection_reason"]
    assert result["order"] is None
    assert count(db, Order) == 0
    rejected = db.scalar(select(TradeEvent).where(TradeEvent.event_type == "RISK_REJECTED"))
    assert rejected is not None


def test_account_without_risk_profile_is_rejected(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    account = setup["account"]
    db.refresh(account)
    account.risk_profile_id = None
    db.commit()
    result = client.post("/internal/orders", json=ticket(setup)).json()
    assert result["status"] == "REJECTED" and "risk profile" in result["rejection_reason"]


def test_pending_order_types_are_not_accepted(client: SignedClient, setup: dict[str, Any]) -> None:
    result = client.post("/internal/orders", json=ticket(setup, order_type="LIMIT")).json()
    assert result["status"] == "REJECTED" and "market orders" in result["rejection_reason"]


def test_unresolved_order_blocks_new_tickets(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    db.add(
        Order(
            client_order_id="u" * 24,
            account_id=setup["account"].id,
            purpose="ENTRY",
            symbol="EURUSD",
            side="BUY",
            order_type="MARKET",
            volume=Decimal("0.1"),
            status=OrderStatus.UNKNOWN,
        )
    )
    db.commit()
    response = client.post("/internal/orders", json=ticket(setup))
    assert response.status_code == 409
    assert "reconciled" in response.json()["error"]["message"]


def test_close_modify_and_close_all(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    first = client.post("/internal/orders", json=ticket(setup)).json()
    quote = setup["broker"].get_quote("EURUSD")
    modified = client.put(
        f"/internal/positions/{first['trade_id']}",
        json={"stop_loss": str(quote.bid - 10 * PIP), "take_profit": None, "actor_label": "owner"},
    )
    assert modified.status_code == 200, modified.text
    closed = client.post(
        f"/internal/positions/{first['trade_id']}/close", json={"actor_label": "owner"}
    )
    assert closed.status_code == 200 and closed.json()["order_status"] == "FILLED"
    again = client.post(
        f"/internal/positions/{first['trade_id']}/close", json={"actor_label": "owner"}
    )
    assert again.status_code == 409
    client.post("/internal/orders", json=ticket(setup))
    summary = client.post(
        "/internal/positions/close-all",
        json={"actor_label": "owner", "account_ids": [str(setup["account"].id)]},
    ).json()
    assert summary == {"closed": 1, "failed": []}
    db.expire_all()
    assert (
        db.scalar(select(func.count()).select_from(Trade).where(Trade.status == TradeStatus.OPEN))
        == 0
    )
    signal = db.scalars(select(Signal).where(Signal.status == SignalStatus.EXECUTED)).first()
    assert signal is not None


def other_users_setup(client: SignedClient, db: Session) -> dict[str, Any]:
    """A second user with their own trading paper account and STOP switch."""
    other = factories.make_user(db)
    account = factories.paper_account(db, owner=other)
    factories.enable_account(db, account, factories.risk_profile(db, owner=other, **LOOSE_RISK))
    factories.resume_trading(db, other)
    broker = paper_broker(client, str(account.connection_id))
    step_until_open(broker)
    return {"account": account, "broker": broker, "owner": other}


def test_one_users_stop_never_blocks_another_users_tickets(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    other = other_users_setup(client, db)
    factories.stop_trading(db)  # the default user stops
    mine = client.post("/internal/orders", json=ticket(setup)).json()
    theirs = client.post("/internal/orders", json=ticket(other)).json()
    assert mine["status"] == "REJECTED" and "Kill switch" in mine["rejection_reason"]
    assert theirs["status"] == "EXECUTED", theirs["rejection_reason"]


def test_idempotency_keys_are_scoped_to_the_account(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    """Another tenant's key never returns their signal/order: keys are per account."""
    other = other_users_setup(client, db)
    key = secrets.token_hex(16)
    theirs = client.post("/internal/orders", json=ticket(other, idempotency_key=key)).json()
    mine = client.post("/internal/orders", json=ticket(setup, idempotency_key=key)).json()
    assert theirs["status"] == "EXECUTED", theirs["rejection_reason"]
    assert mine["status"] == "EXECUTED", mine["rejection_reason"]
    assert mine["signal_id"] != theirs["signal_id"]
    signal = db.get(Signal, uuid.UUID(mine["signal_id"]))
    assert signal is not None and signal.account_id == setup["account"].id
    assert count(db, Order) == 2 and count(db, Trade) == 2


def test_close_all_closes_only_the_given_users_accounts(
    client: SignedClient, db: Session, setup: dict[str, Any]
) -> None:
    other = other_users_setup(client, db)
    assert client.post("/internal/orders", json=ticket(setup)).json()["status"] == "EXECUTED"
    assert client.post("/internal/orders", json=ticket(other)).json()["status"] == "EXECUTED"
    summary = client.post(
        "/internal/positions/close-all",
        json={"actor_label": "owner", "account_ids": [str(setup["account"].id)]},
    ).json()
    assert summary == {"closed": 1, "failed": []}
    db.expire_all()
    still_open = list(db.scalars(select(Trade).where(Trade.status == TradeStatus.OPEN)))
    assert [t.account_id for t in still_open] == [other["account"].id]
    assert client.post(
        "/internal/positions/close-all", json={"actor_label": "x", "account_ids": []}
    ).json() == {"closed": 0, "failed": []}
