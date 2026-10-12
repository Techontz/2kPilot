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
from fxrobot.domain.contracts import ContractFamily, ContractOutcome, ContractType
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
    owner = factories.ensure_user(db)
    connection = BrokerConnection(
        user_id=owner,
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
        user_id=owner,
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
    assert account.balance == Decimal("10000") and account.capabilities["volume_unit"] == "stake"
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


def test_manual_multiplier_ticket_and_broker_side_stop_loss(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    risk = {**LOOSE_RISK, "stake_amount": "11", "max_stake_amount": "20"}
    factories.enable_account(db, account, factories.risk_profile(db, **risk))
    factories.resume_trading(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    body = {
        "account_id": str(account.id),
        "symbol": "frxEURUSD",
        "side": "BUY",
        "stop_loss": "1.09500",
        "take_profit": "1.11000",
        "idempotency_key": secrets.token_hex(16),
        "actor_label": "owner@example.com",
        "contract": {"contract_family": "MULTIPLIER", "multiplier": 100},
    }
    preview = client.post("/internal/orders/preview", json=body).json()
    assert preview["approved"] is True, preview["rejection_reason"]
    assert preview["risk_amount"] == "11" and preview["stake"] == "11"  # the stake is the risk
    assert preview["contract_type"] == "MULTUP"
    checks = {c["rule"]: c for c in preview["checks"]}
    assert "bounded" in checks["Stop loss required"]["detail"]
    assert "1.00 USD–2000.00 USD" in checks["Stake"]["detail"]  # from the proposal

    result = client.post("/internal/orders", json=body).json()
    assert result["status"] == "EXECUTED", result
    assert result["contract_type"] == "MULTUP" and result["stake"] == "11.000000"
    trade = db.get(Trade, uuid.UUID(result["trade_id"]))
    assert trade is not None and trade.broker_position_id in {str(c) for c in fake.contracts}
    assert trade.contract_family is ContractFamily.MULTIPLIER and trade.multiplier == 100
    assert trade.broker_contract_id == trade.broker_position_id
    assert trade.outcome is ContractOutcome.OPEN

    # The broker closes the contract at the stop loss; the engine reconciles it.
    fake.close_externally(int(trade.broker_position_id or 0))
    adapter = client.app.state.broker_manager.get(account.connection_id)  # type: ignore[attr-defined]
    adapter._portfolio_at = 0  # force the portfolio refresh on the next tick
    results = engine_for(client).tick_once()
    assert results and results[0].ok, results
    db.expire_all()
    trade = db.get(Trade, trade.id)
    assert trade is not None and trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is ExitReason.STOP_LOSS
    assert trade.net_pnl == Decimal("-5.00") and trade.r_multiple == Decimal("-0.45")
    assert trade.outcome is ContractOutcome.LOST
    kinds = {n.type for n in db.scalars(select(Notification))}
    assert "position.stop_loss" in kinds


def rise_fall_ticket(account: TradingAccount, **contract: Any) -> dict[str, Any]:
    return {
        "account_id": str(account.id),
        "symbol": "R_100",
        "side": "BUY",
        "idempotency_key": secrets.token_hex(16),
        "actor_label": "owner@example.com",
        "contract": {
            "contract_family": "RISE_FALL",
            "duration": 5,
            "duration_unit": "m",
            **contract,
        },
    }


def test_rise_fall_ticket_settles_at_expiry_through_reconciliation(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    factories.resume_trading(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    body = rise_fall_ticket(account)  # no stop loss: the 1.00 stake is the most it can lose
    preview = client.post("/internal/orders/preview", json=body).json()
    assert preview["approved"] is True, preview["rejection_reason"]
    assert preview["payout"] == "1.95" and preview["contract_type"] == "CALL"

    result = client.post("/internal/orders", json=body).json()
    assert result["status"] == "EXECUTED", result
    trade = db.get(Trade, uuid.UUID(result["trade_id"]))
    assert trade is not None
    assert (trade.contract_type, trade.stake, trade.payout) == (
        ContractType.CALL,
        Decimal("1.000000"),
        Decimal("1.950000"),
    )
    assert (trade.duration, trade.duration_unit) == (5, "m")
    assert trade.expires_at is not None and trade.entry_spot == Decimal("637.4")
    assert trade.longcode and "R_100" in trade.longcode
    assert trade.risk_amount == Decimal("1.000000") and trade.stop_loss is None

    fake.expire(int(trade.broker_position_id or 0), "640.00")  # Deriv settles: won
    adapter = client.app.state.broker_manager.get(account.connection_id)  # type: ignore[attr-defined]
    adapter._portfolio_at = 0
    adapter._contracts.clear()  # the settlement arrives while we were not listening
    engine_for(client).tick_once()
    db.expire_all()
    trade = db.get(Trade, trade.id)
    assert trade is not None and trade.status is TradeStatus.CLOSED
    assert trade.exit_reason is ExitReason.EXPIRED and trade.outcome is ContractOutcome.WON
    assert trade.net_pnl == Decimal("0.95") and trade.exit_spot == Decimal("640.00")
    assert len([r for r in fake.requests if "buy" in r]) == 1


def test_deriv_refuses_spot_and_unsupported_contracts(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    factories.enable_account(db, account, factories.risk_profile(db, **LOOSE_RISK))
    factories.resume_trading(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    spot = {**rise_fall_ticket(account), "contract": None, "stop_loss": "600", "volume": "0.1"}
    preview = client.post("/internal/orders/preview", json=spot).json()
    assert preview["approved"] is False
    assert "Deriv accounts trade contracts" in preview["rejection_reason"]
    long = rise_fall_ticket(account, duration=3, duration_unit="d")
    preview = client.post("/internal/orders/preview", json=long).json()
    assert "Contract supported" in preview["rejection_reason"]
    assert "15s–1d" in preview["rejection_reason"]
    big = {**rise_fall_ticket(account, stake="6.00")}
    preview = client.post("/internal/orders/preview", json=big).json()
    assert "maximum stake 5.00 USD" in preview["rejection_reason"]
    fake.stake_limits = False  # no stake range, but Deriv priced this exact stake
    preview = client.post("/internal/orders/preview", json=rise_fall_ticket(account)).json()
    assert preview["approved"] is True, preview["rejection_reason"]
    assert not fake.contracts


def test_contracts_endpoint_and_validation(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    account = deriv_account(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    data = client.get(f"/internal/accounts/{account.id}/contracts", params={"symbol": "R_100"})
    assert data.status_code == 200, data.text
    body = data.json()
    assert body["families"]["RISE_FALL"]["available"] is True
    assert body["families"]["RISE_FALL"]["durations"][0] == {
        "expiry_type": "tick",
        "min": "1t",
        "max": "10t",
    }
    assert body["families"]["MULTIPLIER"]["multipliers"] == [40, 100, 200, 300, 400]
    assert body["families"]["SPOT"]["available"] is False
    assert body["default_contract"]["duration_unit"] == "m" and body["fetched_at"]
    ok = client.post(
        f"/internal/accounts/{account.id}/contracts/validate",
        json={
            "symbol": "R_100",
            "contract": {
                "contract_family": "RISE_FALL",
                "duration": 5,
                "duration_unit": "m",
                "stake": "2",
            },
        },
    )
    assert ok.status_code == 200 and ok.json()["contract"]["stake"] == "2.00"
    bad = client.post(
        f"/internal/accounts/{account.id}/contracts/validate",
        json={"symbol": "R_100", "contract": {"contract_family": "MULTIPLIER", "multiplier": 7}},
    )
    assert bad.status_code == 422 and "×7 is not offered" in bad.json()["error"]["message"]
    spot = client.post(
        f"/internal/accounts/{account.id}/contracts/validate",
        json={"symbol": "R_100", "contract": {"contract_family": "SPOT"}},
    )
    assert spot.status_code == 422
    malformed = client.post(
        f"/internal/accounts/{account.id}/contracts/validate",
        json={"symbol": "R_100", "contract": {"contract_family": "RISE_FALL"}},
    )
    assert malformed.status_code == 422 and "duration" in malformed.json()["error"]["message"]


def test_history_download_from_deriv_for_a_synthetic_index(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    from datetime import timedelta

    from fxrobot.models import Dataset

    account = deriv_account(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    end = datetime.fromtimestamp(fake.now, UTC)
    response = client.post(
        "/internal/datasets/download",
        json={
            "account_id": str(account.id),
            "symbol": "R_100",
            "timeframe": "M5",
            "start": (end - timedelta(hours=6)).isoformat(),
            "end": end.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    dataset = db.get(Dataset, uuid.UUID(response.json()["id"]))
    assert dataset is not None and dataset.symbol == "R_100" and dataset.bar_count >= 70
    request = next(r for r in fake.requests if "ticks_history" in r)
    assert request["style"] == "candles" and request["granularity"] == 300


def test_the_stored_open_flag_follows_the_broker(
    client: SignedClient, db: Session, fake: FakeDeriv
) -> None:
    """The dashboard's "market is closed" reason reads the stored flag; each
    strategy check keeps it current instead of waiting for a full symbol sync."""
    from fxrobot.trading_engine.runner import AccountRunner

    account = deriv_account(db)
    client.post(f"/internal/connections/{account.connection_id}/connect")
    db.expire_all()
    row = db.scalar(select(BrokerSymbol).where(BrokerSymbol.name == "frxEURUSD"))
    assert row is not None and row.market_open is True
    AccountRunner._store_market_open(db, account, "frxEURUSD", False)  # pyright: ignore[reportPrivateUsage]
    db.expire_all()
    assert (
        db.scalar(select(BrokerSymbol.market_open).where(BrokerSymbol.name == "frxEURUSD")) is False
    )
