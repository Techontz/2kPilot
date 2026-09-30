"""Add-broker wizard, trading accounts, and secret handling (api/v1/brokers + accounts)."""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.adapters.paper import PaperBroker, PaperConfig
from fxrobot.broker_engine.models import AccountInfo
from fxrobot.core.crypto import SecretBox
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectionStatus, ConnectorType
from fxrobot.models import (
    AuditLog,
    BrokerConnection,
    Notification,
    TradingAccount,
    User,
)
from fxrobot.services import brokers as broker_svc
from tests.conftest import login
from tests.paper_helpers import make_market
from tests.test_engine_pipeline import LOOSE_RISK, create_paper_account

PASSWORD = "Mt5-Pa55word-Do-Not-Leak"
BRIDGE_SECRET = "bridge-secret-0123456789abcdef-XYZ-do-not-leak"
SECRETS = (PASSWORD, BRIDGE_SECRET)

PAPER_BODY: dict[str, Any] = {
    "connector_type": "paper",
    "expected_environment": "PAPER",
    "label": "Wizard paper",
    "settings": {"price_source": "synthetic", "symbols": "EURUSD,USDJPY", "seconds_per_bar": 0},
}


def mt5_body(environment: str = "DEMO", **extra: Any) -> dict[str, Any]:
    return {
        "connector_type": "mt5_bridge",
        "expected_environment": environment,
        "label": "My MT5",
        # Port 9 on loopback: nothing listens, the connection is refused immediately.
        "settings": {"bridge_url": "http://127.0.0.1:9", "login": "5012345", "server": "Demo-1"},
        "credentials": {"password": PASSWORD, "bridge_secret": BRIDGE_SECRET},
        **extra,
    }


def counts(db: Session) -> tuple[int, int]:
    db.expire_all()
    return (
        db.scalar(select(func.count()).select_from(BrokerConnection)) or 0,
        db.scalar(select(func.count()).select_from(TradingAccount)) or 0,
    )


def audit_text(db: Session) -> str:
    db.expire_all()
    rows = db.scalars(select(AuditLog)).all()
    return json.dumps([[r.action, r.details] for r in rows], default=str)


def assert_no_secrets(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


def make_profile(client: TestClient, name: str = "loose") -> str:
    response = client.post("/api/v1/risk/profiles", json={"name": name, "limits": LOOSE_RISK})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class FakeMT5(PaperBroker):
    """A paper broker that impersonates an MT5 account of a chosen environment."""

    is_simulated = False

    def __init__(self, environment: AccountEnvironment) -> None:
        super().__init__(make_market(("EURUSD",)), PaperConfig(initial_balance=Decimal(5000)))
        self._environment = environment

    def test_connection(self) -> AccountInfo:
        info = super().test_connection()
        return dataclasses.replace(
            info,
            account_id="5012345",
            server="Demo-1",
            environment=self._environment,
            trade_allowed=True,
        )


@pytest.fixture
def fake_broker(monkeypatch: pytest.MonkeyPatch) -> dict[str, AccountEnvironment]:
    """Make the wizard's temporary adapter report whatever environment the test wants."""
    reported = {"env": AccountEnvironment.DEMO}

    def fake_adapter(db: Session, data: Any, settings: dict[str, Any]) -> Any:
        if data.connector_type is ConnectorType.PAPER:
            return original(db, data, settings)
        return FakeMT5(reported["env"])

    original = broker_svc._temporary_adapter
    monkeypatch.setattr(broker_svc, "_temporary_adapter", fake_adapter)
    return reported


# ── connectors & connection test ─────────────────────────────────────────


def test_connectors_catalogue_marks_secret_fields(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/brokers/connectors").json()
    by_id = {c["id"]: c for c in body}
    assert by_id["paper"]["status"] == "available"
    assert by_id["paper"]["environments"] == ["PAPER"]
    mt5 = by_id["mt5_bridge"]
    assert set(mt5["environments"]) == {"DEMO", "LIVE"}
    secret_fields = {f["name"] for f in mt5["fields"] if f["secret"]}
    assert {"password", "bridge_secret"} <= secret_fields


def test_connectors_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/brokers/connectors").status_code == 401


def test_paper_connection_test_previews_account_and_saves_nothing(
    owner_client: TestClient, db: Session
) -> None:
    response = owner_client.post("/api/v1/brokers/connections/test", json=PAPER_BODY)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["account"]["environment"] == "PAPER"
    assert body["account"]["balance"] == "10000"
    assert body["account"]["currency"] == "USD"
    assert body["account"]["leverage"] == 100
    assert body["symbol_count"] == 2
    assert counts(db) == (0, 0)
    assert "broker.added" not in audit_text(db)


def test_paper_connection_must_be_paper_environment(owner_client: TestClient, db: Session) -> None:
    response = owner_client.post(
        "/api/v1/brokers/connections/test", json={**PAPER_BODY, "expected_environment": "DEMO"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_settings"
    assert counts(db) == (0, 0)


@pytest.mark.parametrize(
    ("settings", "fragment"),
    [
        ({"symbols": "EURUSD,XAUUSD"}, "No synthetic data for: XAUUSD"),
        ({"leverage": 0}, "Leverage must be between 1 and 1000"),
        ({"initial_balance": "-5"}, "Starting balance must be positive"),
        ({"currency": "EUR"}, "USD only"),
        ({"price_source": "live"}, "price_source"),
        ({"price_source": "replay"}, "Replay needs at least one dataset"),
        ({"symbols": " , "}, "At least one symbol"),
    ],
)
def test_invalid_paper_settings_are_rejected(
    owner_client: TestClient, db: Session, settings: dict[str, Any], fragment: str
) -> None:
    body = {**PAPER_BODY, "settings": {**PAPER_BODY["settings"], **settings}}
    response = owner_client.post("/api/v1/brokers/connections", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_settings"
    assert fragment in response.json()["error"]["message"]
    assert counts(db) == (0, 0)


def test_unknown_connector_type_is_a_validation_error(owner_client: TestClient) -> None:
    response = owner_client.post(
        "/api/v1/brokers/connections/test", json={**PAPER_BODY, "connector_type": "ctrader"}
    )
    assert response.status_code == 422


# ── MT5: failures save nothing and never echo secrets ────────────────────


def test_mt5_without_bridge_fails_saves_nothing_and_echoes_no_secret(
    owner_client: TestClient, db: Session
) -> None:
    for path in ("/api/v1/brokers/connections/test", "/api/v1/brokers/connections"):
        response = owner_client.post(path, json=mt5_body())
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "connection_test_failed"
        assert "Cannot reach MT5 bridge" in response.json()["error"]["message"]
        assert_no_secrets(response.text)
    assert counts(db) == (0, 0)
    assert_no_secrets(audit_text(db))
    assert "broker.added" not in audit_text(db)


def test_mt5_short_bridge_secret_is_refused_without_echo(
    owner_client: TestClient, db: Session
) -> None:
    body = mt5_body()
    body["credentials"]["bridge_secret"] = "short-secret-xyz"
    response = owner_client.post("/api/v1/brokers/connections", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_settings"
    assert "short-secret-xyz" not in response.text
    assert_no_secrets(response.text)
    assert counts(db) == (0, 0)


def test_mt5_requires_password(owner_client: TestClient, db: Session) -> None:
    body = mt5_body()
    body["credentials"] = {"bridge_secret": BRIDGE_SECRET}
    response = owner_client.post("/api/v1/brokers/connections/test", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "MT5 password is required"
    assert counts(db) == (0, 0)


@pytest.mark.parametrize(
    ("settings", "fragment"),
    [
        ({"bridge_url": "ftp://bridge"}, "Bridge URL must start with http"),
        ({"login": "abc"}, "account number must be numeric"),
        ({"server": ""}, "MT5 server is required"),
    ],
)
def test_invalid_mt5_settings(
    owner_client: TestClient, db: Session, settings: dict[str, Any], fragment: str
) -> None:
    body = mt5_body()
    body["settings"] = {**body["settings"], **settings}
    response = owner_client.post("/api/v1/brokers/connections/test", json=body)
    assert response.status_code == 400
    assert fragment in response.json()["error"]["message"]
    assert_no_secrets(response.text)
    assert counts(db) == (0, 0)


def test_mt5_cannot_be_declared_paper(owner_client: TestClient) -> None:
    response = owner_client.post(
        "/api/v1/brokers/connections/test", json=mt5_body(environment="PAPER")
    )
    assert response.status_code == 400
    assert "Choose DEMO or LIVE" in response.json()["error"]["message"]


def test_validation_error_never_echoes_credentials(owner_client: TestClient) -> None:
    body = mt5_body()
    body["credentials"]["password"] = {"nested": PASSWORD}  # wrong type → 422
    response = owner_client.post("/api/v1/brokers/connections", json=body)
    assert response.status_code == 422
    assert_no_secrets(response.text)


# ── LIVE acknowledgement & environment verification ──────────────────────


def test_live_requires_explicit_acknowledgement(owner_client: TestClient, db: Session) -> None:
    response = owner_client.post("/api/v1/brokers/connections", json=mt5_body("LIVE"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "live_ack_required"
    assert counts(db) == (0, 0)


def test_live_with_ack_still_needs_a_working_connection(
    owner_client: TestClient, db: Session
) -> None:
    response = owner_client.post(
        "/api/v1/brokers/connections", json=mt5_body("LIVE", acknowledge_live=True)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "connection_test_failed"
    assert counts(db) == (0, 0)


@pytest.mark.parametrize(
    ("expected", "reported", "code"),
    [
        ("DEMO", AccountEnvironment.LIVE, "environment_mismatch"),
        ("LIVE", AccountEnvironment.DEMO, "environment_mismatch"),
        ("DEMO", AccountEnvironment.UNKNOWN, "environment_unknown"),
    ],
)
def test_broker_reported_environment_must_match(
    owner_client: TestClient,
    db: Session,
    fake_broker: dict[str, AccountEnvironment],
    expected: str,
    reported: AccountEnvironment,
    code: str,
) -> None:
    fake_broker["env"] = reported
    body = mt5_body(expected, acknowledge_live=True)
    for path in ("/api/v1/brokers/connections/test", "/api/v1/brokers/connections"):
        response = owner_client.post(path, json=body)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == code
        assert_no_secrets(response.text)
    assert counts(db) == (0, 0)


def test_mt5_demo_saved_with_encrypted_credentials_never_returned(
    owner_client: TestClient, db: Session, fake_broker: dict[str, AccountEnvironment]
) -> None:
    preview = owner_client.post("/api/v1/brokers/connections/test", json=mt5_body())
    assert preview.status_code == 200
    assert preview.json()["account"]["environment"] == "DEMO"
    assert preview.json()["account"]["account_id"] == "5012345"
    assert any("plain HTTP" in w for w in preview.json()["warnings"])
    assert counts(db) == (0, 0)

    created = owner_client.post("/api/v1/brokers/connections", json=mt5_body())
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["environment"] == "DEMO"
    assert account["broker_account_id"] == "5012345"
    assert account["trading_enabled"] is False
    assert counts(db) == (1, 1)

    connection = db.scalars(select(BrokerConnection)).one()
    stored = connection.credentials_encrypted or ""
    assert stored and all(s not in stored for s in SECRETS)
    assert all(s not in json.dumps(connection.settings) for s in SECRETS)
    app: Any = owner_client.app
    key = app.state.settings.secret_encryption_key.get_secret_value()
    assert json.loads(SecretBox(key).decrypt(stored)) == {
        "password": PASSWORD,
        "bridge_secret": BRIDGE_SECRET,
    }

    responses = [
        created,
        owner_client.get("/api/v1/brokers/connections"),
        owner_client.get("/api/v1/accounts"),
        owner_client.get(f"/api/v1/accounts/{account['id']}"),
        owner_client.get("/api/v1/audit"),
        owner_client.get("/api/v1/notifications"),
        owner_client.get("/api/v1/overview"),
        owner_client.post(f"/api/v1/brokers/connections/{connection.id}/reconnect"),
    ]
    for r in responses:
        assert r.status_code in (200, 201), r.text
        assert_no_secrets(r.text)
    listed = owner_client.get("/api/v1/brokers/connections").json()[0]
    assert listed["has_credentials"] is True
    assert "credentials" not in listed and "credentials_encrypted" not in listed
    assert_no_secrets(audit_text(db))


def test_same_mt5_account_cannot_be_added_twice(
    owner_client: TestClient, db: Session, fake_broker: dict[str, AccountEnvironment]
) -> None:
    assert owner_client.post("/api/v1/brokers/connections", json=mt5_body()).status_code == 201
    again = owner_client.post("/api/v1/brokers/connections", json=mt5_body())
    assert again.status_code == 409
    assert counts(db) == (1, 1)


def test_mt5_refused_when_encryption_key_missing(
    app_factory: Any, owner: User, fake_broker: dict[str, AccountEnvironment]
) -> None:
    client = app_factory(secret_encryption_key="")
    login(client)
    response = client.post("/api/v1/brokers/connections", json=mt5_body())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "encryption_unavailable"
    with client.app.state.session_factory() as db:  # type: ignore[attr-defined]
        assert counts(db) == (0, 0)


# ── paper connection lifecycle ───────────────────────────────────────────


def test_create_paper_connection(owner_client: TestClient, db: Session) -> None:
    response = owner_client.post("/api/v1/brokers/connections", json=PAPER_BODY)
    assert response.status_code == 201, response.text
    account = response.json()
    assert account["environment"] == "PAPER"
    assert account["label"] == "Wizard paper"
    assert account["trading_enabled"] is False  # never trades merely because it was added
    assert account["risk_profile_id"] is None
    assert account["balance"] == "10000"
    assert account["broker_account_id"].startswith("PAPER-")
    assert counts(db) == (1, 1)

    symbols = owner_client.get(f"/api/v1/accounts/{account['id']}/symbols").json()
    assert [s["name"] for s in symbols] == ["EURUSD", "USDJPY"]

    audit_row = db.scalars(select(AuditLog).where(AuditLog.action == "broker.added")).one()
    assert audit_row.details == {
        "type": "paper",
        "environment": "PAPER",
        "account": account["broker_account_id"],
        "server": account["server"],
    }
    notes = db.scalars(select(Notification).where(Notification.type == "broker.connected")).all()
    # One from the wizard ("verified and saved"), one from the manager's first connect.
    assert sorted(n.message for n in notes) == [
        "Wizard paper (PAPER) verified and saved. Trading is disabled until you enable it.",
        "Wizard paper: Connected",
    ]

    connections = owner_client.get("/api/v1/brokers/connections").json()
    assert len(connections) == 1
    assert connections[0]["connector_type"] == "paper"
    assert connections[0]["has_credentials"] is False
    assert connections[0]["status"] == "CONNECTED"
    assert connections[0]["accounts"][0]["id"] == account["id"]


def test_create_with_risk_profile(owner_client: TestClient) -> None:
    profile_id = make_profile(owner_client)
    response = owner_client.post(
        "/api/v1/brokers/connections", json={**PAPER_BODY, "risk_profile_id": profile_id}
    )
    assert response.status_code == 201
    assert response.json()["risk_profile_id"] == profile_id
    assert response.json()["trading_enabled"] is False


def test_create_with_unknown_risk_profile_saves_nothing(
    owner_client: TestClient, db: Session
) -> None:
    response = owner_client.post(
        "/api/v1/brokers/connections", json={**PAPER_BODY, "risk_profile_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404
    assert counts(db) == (0, 0)


def test_mutations_require_csrf(owner_client: TestClient, db: Session) -> None:
    del owner_client.headers["X-CSRF-Token"]
    response = owner_client.post("/api/v1/brokers/connections", json=PAPER_BODY)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    assert counts(db) == (0, 0)


def test_reconnect_and_delete_connection(owner_client: TestClient, db: Session) -> None:
    account = create_paper_account(owner_client)
    connection_id = account["connection_id"]
    reconnected = owner_client.post(f"/api/v1/brokers/connections/{connection_id}/reconnect")
    assert reconnected.status_code == 200
    assert reconnected.json()["status"] == "CONNECTED"

    assert owner_client.delete(f"/api/v1/brokers/connections/{connection_id}").status_code == 204
    assert counts(db) == (0, 0)
    assert "broker.removed" in audit_text(db)
    assert owner_client.get(f"/api/v1/accounts/{account['id']}").status_code == 404
    missing = owner_client.delete(f"/api/v1/brokers/connections/{connection_id}")
    assert missing.status_code == 404
    reconnect_missing = owner_client.post(f"/api/v1/brokers/connections/{uuid.uuid4()}/reconnect")
    assert reconnect_missing.status_code == 404


# ── accounts: enabling trading ───────────────────────────────────────────


def test_enabling_trading_requires_risk_profile(owner_client: TestClient, db: Session) -> None:
    account = create_paper_account(owner_client)
    response = owner_client.patch(
        f"/api/v1/accounts/{account['id']}", json={"trading_enabled": True}
    )
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Assign a risk profile before enabling trading."
    assert owner_client.get(f"/api/v1/accounts/{account['id']}").json()["trading_enabled"] is False
    assert "account.trading_enable_denied" in audit_text(db)


def test_enable_then_clearing_profile_disables_trading(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    profile_id = make_profile(owner_client)
    enabled = owner_client.patch(
        f"/api/v1/accounts/{account['id']}",
        json={"risk_profile_id": profile_id, "trading_enabled": True, "label": " Renamed "},
    )
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["trading_enabled"] is True
    assert body["label"] == "Renamed"
    assert body["risk_profile_name"] == "loose"

    cleared = owner_client.patch(
        f"/api/v1/accounts/{account['id']}", json={"clear_risk_profile": True}
    ).json()
    assert cleared["risk_profile_id"] is None
    assert cleared["trading_enabled"] is False  # never trade without a risk profile


def test_patch_unknown_profile_or_account_is_404(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    bad_profile = owner_client.patch(
        f"/api/v1/accounts/{account['id']}", json={"risk_profile_id": str(uuid.uuid4())}
    )
    assert bad_profile.status_code == 404
    assert owner_client.patch(f"/api/v1/accounts/{uuid.uuid4()}", json={}).status_code == 404
    assert owner_client.get(f"/api/v1/accounts/{uuid.uuid4()}").status_code == 404


def _insert_account(db: Session, environment: AccountEnvironment, profile_id: str) -> str:
    connection = BrokerConnection(
        label="Inserted",
        connector_type=ConnectorType.MT5_BRIDGE,
        expected_environment=environment,
        settings={"bridge_url": "http://127.0.0.1:9", "login": "777", "server": "Srv"},
        status=ConnectionStatus.DISCONNECTED,
    )
    db.add(connection)
    db.flush()
    account = TradingAccount(
        connection_id=connection.id,
        broker_account_id="777",
        label="Inserted",
        currency="USD",
        environment=environment,
        risk_profile_id=uuid.UUID(profile_id),
    )
    db.add(account)
    db.commit()
    return str(account.id)


def test_live_account_cannot_enable_trading_while_hard_locked(
    owner_client: TestClient, db: Session
) -> None:
    account_id = _insert_account(db, AccountEnvironment.LIVE, make_profile(owner_client))
    response = owner_client.patch(f"/api/v1/accounts/{account_id}", json={"trading_enabled": True})
    assert response.status_code == 403
    assert "LIVE trading is locked" in response.json()["error"]["message"]
    db.expire_all()
    account = db.get(TradingAccount, uuid.UUID(account_id))
    assert account is not None and account.trading_enabled is False


def test_unknown_environment_account_can_never_trade(
    app_factory: Any, owner: User, db: Session
) -> None:
    client = app_factory(live_trading_enabled=True)  # even with the LIVE lock off
    login(client)
    account_id = _insert_account(db, AccountEnvironment.UNKNOWN, make_profile(client))
    response = client.patch(f"/api/v1/accounts/{account_id}", json={"trading_enabled": True})
    assert response.status_code == 403
    assert "unknown type" in response.json()["error"]["message"]


def test_sync_paper_account_records_snapshot(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    response = owner_client.post(f"/api/v1/accounts/{account['id']}/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == "10000"
    assert body["open_positions"] == 0
    assert body["connection"]["status"] == "CONNECTED"
    series = owner_client.get("/api/v1/overview").json()["equity_series"]
    assert series and series[-1]["equity"] == 10000.0


def test_sync_unknown_account_is_404(owner_client: TestClient) -> None:
    assert owner_client.post(f"/api/v1/accounts/{uuid.uuid4()}/sync").status_code == 404


def test_sync_unreachable_broker_is_reported(owner_client: TestClient, db: Session) -> None:
    account_id = _insert_account(db, AccountEnvironment.DEMO, make_profile(owner_client))
    response = owner_client.post(f"/api/v1/accounts/{account_id}/sync")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "broker_unavailable"


# ── readiness ────────────────────────────────────────────────────────────


def test_readiness_never_ready_while_live_locked(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get(f"/api/v1/accounts/{account['id']}/readiness").json()
    assert body["ready"] is False
    assert body["account_id"] == account["id"]
    items = {i["id"]: i for i in body["items"]}
    assert list(items) == [
        "live_lock",
        "broker_connected",
        "account_recognized",
        "risk_profile",
        "kill_switch",
        "strategy",
        "oos_validation",
        "demo_record",
        "market_data",
        "execution",
        "engine",
        "mfa",
    ]
    assert items["live_lock"]["passed"] is False
    assert "LIVE_TRADING_ENABLED=false" in items["live_lock"]["detail"]
    assert items["account_recognized"]["passed"] is False  # PAPER, not LIVE
    assert items["risk_profile"]["passed"] is False
    assert items["mfa"]["passed"] is False
    assert body["total"] == 12
    assert body["passed"] == sum(i["passed"] for i in body["items"])
    assert "does not enable LIVE" in body["note"]
    for item in body["items"]:
        assert set(item) == {"id", "label", "passed", "detail", "required"}


def test_readiness_reflects_kill_switch_history(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    owner_client.post("/api/v1/trading/stop", json={"reason": "drill"})
    items = {
        i["id"]: i
        for i in owner_client.get(f"/api/v1/accounts/{account['id']}/readiness").json()["items"]
    }
    assert items["kill_switch"]["passed"] is True
    assert "engaged 1 time(s); currently engaged" in items["kill_switch"]["detail"]


def test_readiness_unknown_account_is_404(owner_client: TestClient) -> None:
    assert owner_client.get(f"/api/v1/accounts/{uuid.uuid4()}/readiness").status_code == 404
