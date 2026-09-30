"""The kill switch and mode rules are safety-critical; test every branch."""

from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from fxrobot.domain.modes import TradingMode
from fxrobot.models import AuditLog, SystemState, User
from fxrobot.services.trading_control import LIVE_CONFIRMATION_PHRASE
from tests.conftest import OWNER_PASSWORD, fresh_heartbeat, login


def _actions(db: Session) -> list[str]:
    return [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def test_fresh_install_is_demo_with_kill_switch_engaged(owner_client: TestClient) -> None:
    status = owner_client.get("/api/v1/trading/status").json()
    assert status["trading_mode"] == "DEMO"
    assert status["kill_switch_engaged"] is True
    assert status["new_orders_permitted"] is False
    assert status["live_trading_locked"] is True
    assert status["engine_state"] == "offline"


def test_system_status_requires_login(client: TestClient) -> None:
    assert client.get("/api/v1/system/status").status_code == 401


def test_resume_then_stop(owner_client: TestClient, db: Session) -> None:
    fresh_heartbeat(db)
    resumed = owner_client.post("/api/v1/trading/resume", json={"confirm": True}).json()
    assert resumed["kill_switch_engaged"] is False
    assert resumed["new_orders_permitted"] is True
    assert resumed["engine_state"] == "running"

    stopped = owner_client.post("/api/v1/trading/stop", json={"reason": "news spike"}).json()
    assert stopped["kill_switch_engaged"] is True
    assert stopped["kill_switch_reason"] == "news spike"
    assert stopped["new_orders_permitted"] is False
    assert _actions(db)[-2:] == ["trading.kill_switch.released", "trading.kill_switch.engaged"]


def test_stop_is_idempotent_and_always_audited(owner_client: TestClient, db: Session) -> None:
    for _ in range(2):
        response = owner_client.post("/api/v1/trading/stop", json={})
        assert response.status_code == 200
        assert response.json()["kill_switch_engaged"] is True
    assert _actions(db).count("trading.kill_switch.engaged") == 2


def test_resume_requires_explicit_confirmation(owner_client: TestClient) -> None:
    assert owner_client.post("/api/v1/trading/resume", json={}).status_code == 422
    assert owner_client.post("/api/v1/trading/resume", json={"confirm": False}).status_code == 422


def test_viewer_cannot_control_trading(client: TestClient, viewer: User) -> None:
    login(client, email=viewer.email)
    assert client.get("/api/v1/trading/status").status_code == 200
    assert client.post("/api/v1/trading/stop", json={}).status_code == 403
    assert client.post("/api/v1/trading/resume", json={"confirm": True}).status_code == 403
    assert client.put("/api/v1/trading/mode", json={"mode": "BACKTEST"}).status_code == 403


def test_mode_change_requires_trading_stopped(owner_client: TestClient, db: Session) -> None:
    owner_client.post("/api/v1/trading/resume", json={"confirm": True})
    response = owner_client.put("/api/v1/trading/mode", json={"mode": "BACKTEST"})
    assert response.status_code == 409
    assert _actions(db)[-1] == "trading.mode.change_denied"


def test_switch_between_backtest_and_demo(owner_client: TestClient) -> None:
    body = owner_client.put("/api/v1/trading/mode", json={"mode": "BACKTEST"}).json()
    assert body["trading_mode"] == "BACKTEST"
    assert body["kill_switch_engaged"] is True  # mode change never resumes trading
    assert owner_client.put("/api/v1/trading/mode", json={"mode": "DEMO"}).status_code == 200


def test_backtest_mode_never_permits_orders(owner_client: TestClient) -> None:
    owner_client.put("/api/v1/trading/mode", json={"mode": "BACKTEST"})
    body = owner_client.post("/api/v1/trading/resume", json={"confirm": True}).json()
    assert body["new_orders_permitted"] is False


def test_live_is_refused_while_hard_locked(owner_client: TestClient, db: Session) -> None:
    response = owner_client.put(
        "/api/v1/trading/mode",
        json={
            "mode": "LIVE",
            "password": OWNER_PASSWORD,
            "confirmation_phrase": LIVE_CONFIRMATION_PHRASE,
        },
    )
    assert response.status_code == 403
    assert "locked" in response.json()["error"]["message"].lower()
    assert db.get(SystemState, 1).trading_mode is TradingMode.DEMO  # type: ignore[union-attr]
    denied = db.scalars(select(AuditLog).where(AuditLog.action == "trading.mode.change_denied"))
    assert denied.one().details["to"] == "LIVE"


def test_live_requires_password_and_phrase_even_when_unlocked(
    app_factory,
    owner: User,  # type: ignore[no-untyped-def]
) -> None:
    client = app_factory(live_trading_enabled=True)
    login(client)
    wrong_pw = client.put(
        "/api/v1/trading/mode",
        json={"mode": "LIVE", "password": "wrong", "confirmation_phrase": LIVE_CONFIRMATION_PHRASE},
    )
    assert wrong_pw.status_code == 403
    no_phrase = client.put(
        "/api/v1/trading/mode", json={"mode": "LIVE", "password": OWNER_PASSWORD}
    )
    assert no_phrase.status_code == 403
    ok = client.put(
        "/api/v1/trading/mode",
        json={
            "mode": "LIVE",
            "password": OWNER_PASSWORD,
            "confirmation_phrase": LIVE_CONFIRMATION_PHRASE,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["trading_mode"] == "LIVE"
    assert ok.json()["kill_switch_engaged"] is True


def test_live_state_with_lock_reengaged_blocks_orders(
    owner_client: TestClient, db: Session
) -> None:
    """If the DB says LIVE but the server hard lock is on, nothing may trade."""
    db.execute(update(SystemState).values(trading_mode=TradingMode.LIVE, kill_switch_engaged=False))
    db.commit()
    body = owner_client.get("/api/v1/trading/status").json()
    assert body["trading_mode"] == "LIVE"
    assert body["new_orders_permitted"] is False


def test_system_status_payload(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/system/status").json()
    assert body["environment"] == "test"
    assert body["broker_accounts_connected"] == 0
    assert body["broker_accounts_total"] == 0
    assert body["trading"]["trading_mode"] == "DEMO"


def test_audit_log_endpoint(owner_client: TestClient) -> None:
    owner_client.post("/api/v1/trading/stop", json={"reason": "test"})
    entries = owner_client.get("/api/v1/audit?limit=2").json()
    assert entries[0]["action"] == "trading.kill_switch.engaged"
    older = owner_client.get(f"/api/v1/audit?before_id={entries[-1]['id']}").json()
    assert all(e["id"] < entries[-1]["id"] for e in older)


def test_viewer_cannot_read_audit_log(client: TestClient, viewer: User) -> None:
    login(client, email=viewer.email)
    assert client.get("/api/v1/audit").status_code == 403


def test_missing_state_row_is_recreated_with_kill_switch_engaged(
    owner_client: TestClient, db: Session
) -> None:
    db.execute(text("DELETE FROM system_state"))
    db.commit()
    body = owner_client.get("/api/v1/trading/status").json()
    assert body["kill_switch_engaged"] is True
    assert body["new_orders_permitted"] is False


def test_offline_engine_never_permits_orders(owner_client: TestClient) -> None:
    body = owner_client.post("/api/v1/trading/resume", json={"confirm": True}).json()
    assert body["kill_switch_engaged"] is False
    assert body["engine_state"] == "offline"
    assert body["new_orders_permitted"] is False


def test_emergency_stop_engages_kill_switch_without_closing(
    owner_client: TestClient, db: Session
) -> None:
    owner_client.post("/api/v1/trading/resume", json={"confirm": True})
    body = owner_client.post("/api/v1/trading/emergency-stop", json={"reason": "test"}).json()
    assert body["status"]["kill_switch_engaged"] is True
    assert body["result"] == {"closed": 0, "failed": []}
    assert "trading.emergency_stop" in _actions(db)
