"""A Deriv account through the whole engine: Test Connection, account choice,
connect + sync, a manual ticket through risk + execution, a stop loss hit at
the broker, reconciliation, disconnect and reconnect. Deriv is the in-memory
imitation (tests/fake_deriv.py) — no real servers, no real money."""

from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import fxrobot.broker_engine.factory as factory
from fxrobot.broker_engine.adapters.deriv import DerivAdapter
from fxrobot.broker_engine.adapters.deriv_client import DerivRest
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectionStatus, ConnectorType, ExitReason, TradeStatus
from fxrobot.models import BrokerConnection, BrokerSymbol, Notification, Trade, TradingAccount
from tests import factories
from tests.conftest import SignedClient, secret_box
from tests.fake_deriv import ACCOUNT_ID, TOKEN, FakeDeriv
from tests.test_engine_pipeline import LOOSE_RISK, engine_for


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeDeriv:
    server = FakeDeriv(now=int(time.time()))

    def deriv_from(settings: dict[str, Any], secrets_: dict[str, Any], app_id: str) -> DerivAdapter:
        rest = DerivRest(token=secrets_["token"], app_id=app_id, transport=server.transport())
        return DerivAdapter(
            token=secrets_["token"],
            app_id=app_id,
            account_id=settings["account_id"],
            rest=rest,
            connector=server.connector,
            clock=lambda: datetime.fromtimestamp(server.now, UTC),
        )

    monkeypatch.setattr(factory, "deriv_from", deriv_from)
    import fxrobot.services.brokers as brokers

    monkeypatch.setattr(brokers, "deriv_from", deriv_from)
    return server


def credentials(token: str = TOKEN) -> str:
    return secret_box().encrypt(json.dumps({"token": token, "token_kind": "pat"}))


def test_connection_reports_what_deriv_returns(client: SignedClient, fake: FakeDeriv) -> None:
    response = client.post(
        "/internal/connections/test",
        json={
            "connector_type": "deriv",
            "expected_environment": "DEMO",
            "settings": {"account_id": ACCOUNT_ID},
            "credentials_encrypted": credentials(),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["account"]["environment"] == "DEMO"
    assert body["account"]["account_id"] == ACCOUNT_ID
    assert body["account"]["balance"] == "10000"
    assert body["categories"] == {"forex": 2, "synthetic": 1}
    assert body["capabilities"]["pending_orders"] is False
    assert body["normalized_settings"] == {"account_id": ACCOUNT_ID, "multiplier": None}


def test_demo_selected_but_real_account_is_refused(client: SignedClient, fake: FakeDeriv) -> None:
    fake.account_type = "real"
    response = client.post(
        "/internal/connections/test",
        json={
            "connector_type": "deriv",
            "expected_environment": "DEMO",
            "settings": {"account_id": ACCOUNT_ID},
            "credentials_encrypted": credentials(),
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "environment_mismatch"


def test_bad_token_fails_the_test(client: SignedClient, fake: FakeDeriv) -> None:
    response = client.post(
        "/internal/connections/test",
        json={
            "connector_type": "deriv",
            "expected_environment": "DEMO",
            "settings": {"account_id": ACCOUNT_ID},
            "credentials_encrypted": credentials("wrong-token"),
        },
    )
    assert response.status_code == 422
    assert "refused the token" in response.json()["error"]["message"]


def test_accounts_reachable_with_the_token(client: SignedClient, fake: FakeDeriv) -> None:
    response = client.post(
        "/internal/deriv/accounts", json={"credentials_encrypted": credentials()}
    )
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "account_id": ACCOUNT_ID,
            "account_type": "demo",
            "currency": "USD",
            "balance": "10000",
            "status": "active",
        }
    ]


def deriv_account(db: Session) -> TradingAccount:
    connection = BrokerConnection(
        label="Deriv demo",
        connector_type=ConnectorType.DERIV,
        expected_environment=AccountEnvironment.DEMO,
        settings={"account_id": ACCOUNT_ID, "multiplier": None},
        credentials_encrypted=credentials(),
        status=ConnectionStatus.DISCONNECTED,
    )
    db.add(connection)
    db.flush()
    account = TradingAccount(
        connection_id=connection.id,
        broker_account_id=ACCOUNT_ID,
        label="Deriv demo",
        currency="USD",
        environment=AccountEnvironment.DEMO,
        capabilities={},
    )
    db.add(account)
    db.commit()
    return account


def test_connect_syncs_account_and_instruments(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    response = client.post(f"/internal/connections/{account.connection_id}/connect")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONNECTED"
    db.expire_all()
    account = db.get(TradingAccount, account.id)  # type: ignore[assignment]
    assert account.balance == Decimal("10000") and account.capabilities["volume_unit"] == "lots"
    symbols = {s.name: s for s in db.scalars(select(BrokerSymbol))}
    assert symbols["frxEURUSD"].category == "forex" and symbols["frxEURUSD"].canonical == "EURUSD"
    assert symbols["R_100"].category == "synthetic" and symbols["R_100"].market_open is True
    quotes = client.get(
        f"/internal/accounts/{account.id}/quotes", params={"symbols": "frxEURUSD,R_100"}
    ).json()
    assert quotes["quotes"]["frxEURUSD"]["bid"] == "1.1" and quotes["simulated"] is False

    disconnected = client.post(f"/internal/connections/{account.connection_id}/disconnect")
    assert disconnected.json() == {"status": "DISCONNECTED"}
    db.expire_all()
    connection = db.get(BrokerConnection, account.connection_id)
    assert connection is not None and connection.status is ConnectionStatus.DISCONNECTED
    client.post(f"/internal/connections/{account.connection_id}/connect")
    assert fake.otps_issued == 2  # every (re)connect uses a fresh one-time password


def test_manual_ticket_and_broker_side_stop_loss(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    factories.resume_trading(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    body = {
        "account_id": str(account.id),
        "symbol": "frxEURUSD",
        "side": "BUY",
        "volume": "0.01",
        "stop_loss": "1.09500",
        "take_profit": "1.11000",
        "idempotency_key": secrets.token_hex(16),
        "actor_label": "owner@example.com",
    }
    preview = client.post("/internal/orders/preview", json=body).json()
    assert preview["approved"] is True, preview["rejection_reason"]
    assert preview["risk_amount"] == "5"  # 0.01 lot, 50 pips → 5 USD
    assert any("multiplier" in note for note in preview["notes"])

    result = client.post("/internal/orders", json=body).json()
    assert result["status"] == "EXECUTED", result
    assert result["order"]["is_simulated"] is False
    trade = db.get(Trade, uuid.UUID(result["trade_id"]))
    assert trade is not None and trade.broker_position_id in {str(c) for c in fake.contracts}

    # The broker closes the contract at the stop loss; the engine reconciles it.
    fake.close_externally(int(trade.broker_position_id))
    adapter = client.app.state.broker_manager.get(account.connection_id)  # type: ignore[attr-defined]
    adapter._portfolio_at = 0  # force the portfolio refresh on the next tick
    results = engine_for(client).tick_once()
    assert results and results[0].ok, results
    db.expire_all()
    trade = db.get(Trade, trade.id)
    assert trade is not None and trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.net_pnl == Decimal("-5.00") and trade.r_multiple == Decimal("-1.00")
    kinds = {n.type for n in db.scalars(select(Notification))}
    assert "position.stop_loss" in kinds
