"""Cross-cutting API rules (roles, CSRF), notifications, overview/analytics empty states,
settings, the SSE stream, and the emergency stop that closes paper positions."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.api.v1 import stream as stream_api
from fxrobot.core.events import Event, bus
from fxrobot.domain.trading import ExitReason, TradeStatus
from fxrobot.models import AuditLog, AuditOutcome, Notification, Trade, User
from fxrobot.notifications.service import notify
from tests.conftest import login
from tests.test_engine_pipeline import create_paper_account, run_until, setup_trading

ANY_ID = "00000000-0000-0000-0000-000000000001"

# Every state-changing endpoint, with a body that would otherwise be acceptable.
MUTATIONS: list[tuple[str, str, dict[str, Any] | None]] = [
    (
        "POST",
        "/api/v1/brokers/connections/test",
        {"connector_type": "paper", "expected_environment": "PAPER"},
    ),
    (
        "POST",
        "/api/v1/brokers/connections",
        {"connector_type": "paper", "expected_environment": "PAPER"},
    ),
    ("POST", f"/api/v1/brokers/connections/{ANY_ID}/reconnect", None),
    ("DELETE", f"/api/v1/brokers/connections/{ANY_ID}", None),
    ("PATCH", f"/api/v1/accounts/{ANY_ID}", {"trading_enabled": True}),
    ("POST", f"/api/v1/accounts/{ANY_ID}/sync", None),
    ("POST", f"/api/v1/strategies/{ANY_ID}/versions", {"parameters": {}}),
    (
        "POST",
        "/api/v1/strategies/assignments",
        {"strategy_version_id": ANY_ID, "account_id": ANY_ID, "symbol": "EURUSD"},
    ),
    ("POST", f"/api/v1/strategies/assignments/{ANY_ID}/enable", None),
    ("POST", f"/api/v1/strategies/assignments/{ANY_ID}/pause", {}),
    ("PUT", f"/api/v1/strategies/assignments/{ANY_ID}/version", {"strategy_version_id": ANY_ID}),
    ("DELETE", f"/api/v1/strategies/assignments/{ANY_ID}", None),
    ("POST", "/api/v1/risk/profiles", {"name": "x", "limits": {}}),
    ("PUT", f"/api/v1/risk/profiles/{ANY_ID}", {"limits": {}}),
    ("DELETE", f"/api/v1/risk/profiles/{ANY_ID}", None),
    (
        "POST",
        "/api/v1/market/datasets/import",
        {"symbol": "EURUSD", "timeframe": "H1", "content": "time,open,high,low,close\n"},
    ),
    ("POST", "/api/v1/market/datasets/synthetic", {"symbol": "EURUSD"}),
    (
        "POST",
        "/api/v1/market/datasets/download",
        {
            "account_id": ANY_ID,
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-02-01T00:00:00Z",
        },
    ),
    ("DELETE", f"/api/v1/market/datasets/{ANY_ID}", None),
    ("POST", "/api/v1/trading/stop", {"reason": "x"}),
    ("POST", "/api/v1/trading/resume", {"confirm": True}),
    ("PUT", "/api/v1/trading/mode", {"mode": "BACKTEST"}),
    ("POST", "/api/v1/trading/emergency-stop", {"close_positions": True}),
    ("POST", f"/api/v1/positions/{ANY_ID}/close", None),
    ("PUT", f"/api/v1/positions/{ANY_ID}", {"stop_loss": "1.1"}),
    (
        "POST",
        "/api/v1/backtests",
        {"dataset_id": ANY_ID, "start": "2024-01-01T00:00:00Z", "end": "2024-02-01T00:00:00Z"},
    ),
    ("DELETE", f"/api/v1/backtests/{ANY_ID}", None),
]
MUTATION_IDS = [f"{m} {p}" for m, p, _ in MUTATIONS]

READS = [
    "/api/v1/overview",
    "/api/v1/accounts",
    "/api/v1/brokers/connections",
    "/api/v1/brokers/connectors",
    "/api/v1/strategies",
    "/api/v1/risk/profiles",
    "/api/v1/market/datasets",
    "/api/v1/market/session",
    "/api/v1/notifications",
    "/api/v1/notifications/unread-count",
    "/api/v1/analytics/performance",
    "/api/v1/settings",
    "/api/v1/trading/status",
]


def send(client: TestClient, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return client.request(method, path, json=body)


def audit_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


# ── roles & CSRF ─────────────────────────────────────────────────────────


@pytest.fixture
def viewer_client(client: TestClient, viewer: User) -> TestClient:
    login(client, email="viewer@example.com")
    return client


@pytest.mark.parametrize(("method", "path", "body"), MUTATIONS, ids=MUTATION_IDS)
def test_viewer_is_forbidden_on_every_mutation(
    viewer_client: TestClient,
    db: Session,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    before = audit_count(db)
    response = send(viewer_client, method, path, body)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "permission_denied"
    assert audit_count(db) == before  # nothing happened


def test_every_mutation_requires_csrf(owner_client: TestClient, db: Session) -> None:
    before = audit_count(db)
    for header in (None, "wrong-token"):
        if header is None:
            owner_client.headers.pop("X-CSRF-Token", None)
        else:
            owner_client.headers["X-CSRF-Token"] = header
        for method, path, body in MUTATIONS:
            response = send(owner_client, method, path, body)
            assert response.status_code == 403, f"{method} {path}: {response.text}"
            assert response.json()["error"]["code"] == "csrf_failed", path
    assert audit_count(db) == before


def test_every_mutation_requires_login(client: TestClient) -> None:
    for method, path, body in MUTATIONS:
        response = send(client, method, path, body)
        assert response.status_code == 401, f"{method} {path}"
        assert response.json()["error"]["code"] == "not_authenticated"


def test_viewer_can_read_dashboards(viewer_client: TestClient) -> None:
    for path in READS:
        assert viewer_client.get(path).status_code == 200, path


def test_reads_require_login(client: TestClient) -> None:
    for path in [*READS, "/api/v1/stream"]:
        assert client.get(path).status_code == 401, path


def test_viewer_may_mark_notifications_read(viewer_client: TestClient, db: Session) -> None:
    notify(db, "system.error", "x")
    assert viewer_client.post("/api/v1/notifications/read", json={}).json() == {"updated": 1}


# ── notifications ────────────────────────────────────────────────────────


def test_notifications_empty_state(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/notifications").json()
    assert body["items"] == []
    assert body["unread"] == 0
    assert body["types"]["trading.emergency_stop"] == {
        "severity": "critical",
        "title": "Emergency stop",
    }
    assert owner_client.get("/api/v1/notifications/unread-count").json() == {"unread": 0}


def test_notifications_list_filter_and_mark_read(owner_client: TestClient, db: Session) -> None:
    ids = [
        notify(db, "broker.error", "a").id,
        notify(db, "signal.generated", "b").id,
        notify(db, "position.opened", "c", data={"password": "hunter2"}).id,
    ]
    body = owner_client.get("/api/v1/notifications").json()
    assert [n["id"] for n in body["items"]] == ids[::-1]  # newest first
    assert body["unread"] == 3
    assert body["items"][0]["title"] == "Position opened"
    assert body["items"][0]["severity"] == "success"
    assert "hunter2" not in json.dumps(body)  # notification data is masked

    critical = owner_client.get("/api/v1/notifications?severity=critical").json()["items"]
    assert [n["message"] for n in critical] == ["a"]
    page = owner_client.get(f"/api/v1/notifications?before_id={ids[2]}&limit=1").json()
    assert [n["id"] for n in page["items"]] == [ids[1]]

    marked = owner_client.post("/api/v1/notifications/read", json={"ids": [ids[0]]})
    assert marked.json() == {"updated": 1}
    assert owner_client.get("/api/v1/notifications/unread-count").json() == {"unread": 2}
    unread = owner_client.get("/api/v1/notifications?unread_only=true").json()["items"]
    assert {n["id"] for n in unread} == {ids[1], ids[2]}
    again = owner_client.post("/api/v1/notifications/read", json={"ids": [ids[0]]})
    assert again.json() == {"updated": 0}  # already read

    assert owner_client.post("/api/v1/notifications/read", json={}).json() == {"updated": 2}
    assert owner_client.get("/api/v1/notifications/unread-count").json() == {"unread": 0}
    first = owner_client.get("/api/v1/notifications").json()["items"][-1]
    assert first["read_at"] is not None


def test_notification_query_validation(owner_client: TestClient) -> None:
    assert owner_client.get("/api/v1/notifications?severity=bogus").status_code == 422
    assert owner_client.get("/api/v1/notifications?limit=0").status_code == 422
    assert owner_client.get("/api/v1/notifications?limit=201").status_code == 422
    assert owner_client.get("/api/v1/notifications?before_id=0").status_code == 422


# ── overview & analytics: empty states are honest ────────────────────────


def test_overview_empty_state_has_no_invented_numbers(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/overview").json()
    assert body == {
        "accounts": [],
        "currency": "USD",
        "totals": {
            "balance": None,
            "equity": None,
            "today_pnl": None,
            "realized_today": None,
            "open_pnl": None,
            "open_positions": 0,
            "trades_today": 0,
            "open_risk": None,
            "open_risk_unknown": False,
            "max_drawdown_pct": None,
        },
        "active_strategies": 0,
        "equity_series": [],
        "equity_series_account": None,
        "recent_events": [],
    }


def test_overview_with_fresh_paper_account(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get("/api/v1/overview").json()
    totals = body["totals"]
    assert totals["balance"] == "10000"
    assert totals["equity"] == "10000"
    assert totals["today_pnl"] == "0"
    assert totals["open_pnl"] == "0"
    assert totals["open_positions"] == 0
    assert totals["max_drawdown_pct"] is None  # no snapshots yet → unknown, not 0
    assert body["equity_series_account"] == account["id"]
    assert body["accounts"][0]["connector_type"] == "paper"
    assert body["accounts"][0]["drawdown_pct"] is None


def test_analytics_empty_without_accounts(owner_client: TestClient) -> None:
    assert owner_client.get("/api/v1/analytics/performance").json() == {
        "has_data": False,
        "accounts": [],
    }
    unknown = owner_client.get(f"/api/v1/analytics/performance?account_id={uuid.uuid4()}")
    assert unknown.json() == {"has_data": False, "accounts": []}


def test_analytics_without_trades_reports_nulls_and_zeros(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get(f"/api/v1/analytics/performance?account_id={account['id']}").json()
    assert body["has_data"] is False
    assert body["simulated"] is True
    assert body["trades"] == 0
    assert body["net_pnl"] == 0
    for key in ("win_rate", "profit_factor", "expectancy", "expectancy_r", "avg_win", "avg_loss"):
        assert body[key] is None, key
    assert body["equity_curve"] == []
    assert body["daily"] == [] and body["weekly"] == []
    assert body["open_positions"] == 0
    assert body["unrealized_pnl"] == 0


def test_analytics_days_validation(owner_client: TestClient) -> None:
    assert owner_client.get("/api/v1/analytics/performance?days=0").status_code == 422
    assert owner_client.get("/api/v1/analytics/performance?days=3651").status_code == 422


def test_settings_view_reports_secrets_as_presence_only(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/settings").json()
    app: Any = owner_client.app
    key = app.state.settings.secret_encryption_key.get_secret_value()
    assert body["live_trading_enabled"] is False
    assert body["encryption_key_configured"] is True
    assert key not in json.dumps(body)
    assert "@" not in body["database"] and "root" not in body["database"]


# ── SSE stream ───────────────────────────────────────────────────────────


def test_format_event() -> None:
    at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    text = stream_api._format(Event("position", {"id": 7, "when": at}, at))
    assert text.startswith("event: position\ndata: ")
    assert text.endswith("\n\n")
    payload = json.loads(text.split("data: ", 1)[1])
    assert payload == {
        "topic": "position",
        "at": "2025-01-02T03:04:05+00:00",
        "data": {"id": 7, "when": "2025-01-02 03:04:05+00:00"},
    }


class _FakeRequest:
    def __init__(self) -> None:
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def test_stream_emits_published_events_and_unsubscribes() -> None:
    async def scenario() -> list[str]:
        request = _FakeRequest()
        before = bus.subscriber_count
        response = await stream_api.stream(request, None)  # type: ignore[arg-type]
        body: Any = response.body_iterator
        chunks = [await asyncio.wait_for(body.__anext__(), 2)]
        assert bus.subscriber_count == before + 1
        bus.publish("status", {"kill_switch_engaged": True})
        chunks.append(await asyncio.wait_for(body.__anext__(), 2))
        request.disconnected = True
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(body.__anext__(), 2)
        assert bus.subscriber_count == before
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-store"
        return chunks

    chunks = asyncio.run(asyncio.wait_for(scenario(), 10))
    assert chunks[0] == "retry: 5000\n\n"
    assert chunks[1].startswith("event: status\n")
    assert json.loads(chunks[1].split("data: ", 1)[1])["data"] == {"kill_switch_engaged": True}


def test_notifications_are_published_to_the_stream(db: Session) -> None:
    q = bus.subscribe()
    try:
        note = notify(db, "trading.stopped", "stopped by test")
        event = q.get(timeout=1)
    finally:
        bus.unsubscribe(q)
    assert event.topic == "notification"
    assert event.data["id"] == note.id
    assert event.data["message"] == "stopped by test"


# ── emergency stop ───────────────────────────────────────────────────────


def test_emergency_stop_closes_paper_positions(owner_client: TestClient, db: Session) -> None:
    trading = setup_trading(owner_client)

    def open_trade() -> bool:
        return bool(db.scalar(select(func.count()).where(Trade.status == TradeStatus.OPEN)))

    run_until(owner_client, trading["account"]["connection_id"], db, open_trade)
    open_ids = list(db.scalars(select(Trade.id).where(Trade.status == TradeStatus.OPEN)))
    positions = owner_client.get("/api/v1/positions").json()
    assert len(positions) == len(open_ids) >= 1

    response = owner_client.post(
        "/api/v1/trading/emergency-stop", json={"reason": "drill", "close_positions": True}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == {"closed": len(open_ids), "failed": []}
    assert body["status"]["kill_switch_engaged"] is True
    assert body["status"]["new_orders_permitted"] is False

    db.expire_all()
    for trade_id in open_ids:
        trade = db.get(Trade, trade_id)
        assert trade is not None
        assert trade.status is TradeStatus.CLOSED
        assert trade.exit_reason is ExitReason.EMERGENCY
        assert trade.net_pnl is not None
    assert owner_client.get("/api/v1/positions").json() == []
    row = db.scalars(select(AuditLog).where(AuditLog.action == "trading.emergency_stop")).one()
    assert row.details == {"close_positions": True, "closed": len(open_ids), "failed": []}
    note = db.scalars(
        select(Notification).where(Notification.type == "trading.emergency_stop")
    ).one()
    assert f"closed {len(open_ids)} position(s)" in note.message
    assert owner_client.get("/api/v1/overview").json()["totals"]["open_positions"] == 0


def test_emergency_stop_reports_positions_it_could_not_close(
    owner_client: TestClient, db: Session
) -> None:
    trading = setup_trading(owner_client)
    connection_id = trading["account"]["connection_id"]
    run_until(
        owner_client,
        connection_id,
        db,
        lambda: bool(db.scalar(select(func.count()).where(Trade.status == TradeStatus.OPEN))),
    )
    app: Any = owner_client.app
    app.state.broker_manager.faults[uuid.UUID(connection_id)].disconnected = True

    body = owner_client.post(
        "/api/v1/trading/emergency-stop", json={"reason": "outage", "close_positions": True}
    ).json()
    assert body["result"]["closed"] == 0
    assert len(body["result"]["failed"]) >= 1
    assert body["result"]["failed"][0].startswith("EURUSD: Broker unavailable")
    assert body["status"]["kill_switch_engaged"] is True  # trading stops regardless
    db.expire_all()
    assert db.scalar(select(func.count()).where(Trade.status == TradeStatus.OPEN)) >= 1
    row = db.scalars(select(AuditLog).where(AuditLog.action == "trading.emergency_stop")).one()
    assert row.outcome is AuditOutcome.FAILURE


def test_overview_drawdown_known_after_snapshot(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    assert owner_client.post(f"/api/v1/accounts/{account['id']}/sync").status_code == 200
    body = owner_client.get("/api/v1/overview").json()
    assert body["accounts"][0]["drawdown_pct"] == 0.0
    assert body["totals"]["max_drawdown_pct"] == 0.0
    assert len(body["equity_series"]) == 1
