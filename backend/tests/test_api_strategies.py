"""Strategies: immutable versions and paused-by-default assignments (api/v1/strategies)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.models import AuditLog, Notification, StrategyVersion
from fxrobot.strategy_engine import get_strategy
from tests.test_engine_pipeline import LOOSE_RISK, create_paper_account


def strategy(client: TestClient) -> dict[str, Any]:
    body = client.get("/api/v1/strategies").json()
    assert len(body) == 1
    return dict(body[0])


def new_version(client: TestClient, strategy_id: str, **params: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/strategies/{strategy_id}/versions", json={"parameters": params, "notes": "t"}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def assign(client: TestClient, version_id: str, account_id: str, symbol: str = "EURUSD") -> Any:
    return client.post(
        "/api/v1/strategies/assignments",
        json={"strategy_version_id": version_id, "account_id": account_id, "symbol": symbol},
    )


def give_profile(client: TestClient, account_id: str) -> None:
    profile = client.post("/api/v1/risk/profiles", json={"name": "p", "limits": LOOSE_RISK})
    assert profile.status_code == 201
    patched = client.patch(
        f"/api/v1/accounts/{account_id}", json={"risk_profile_id": profile.json()["id"]}
    )
    assert patched.status_code == 200


def actions(db: Session) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


@pytest.fixture
def setup(owner_client: TestClient) -> dict[str, Any]:
    account = create_paper_account(owner_client)
    s = strategy(owner_client)
    return {"account": account, "strategy": s, "v1": s["versions"][0]}


def test_default_strategy_is_seeded_with_version_1(owner_client: TestClient) -> None:
    s = strategy(owner_client)
    impl = get_strategy("trend_pullback")
    assert s["key"] == "trend_pullback"
    assert s["code_version"] == impl.code_version
    assert [v["version"] for v in s["versions"]] == [1]
    assert s["versions"][0]["parameters"] == impl.default_params()
    assert s["versions"][0]["notes"] == "Default research parameters"
    assert s["status"] == "PAUSED"
    assert s["assignments"] == []
    assert s["performance"]["closed_trades"] == 0
    assert Decimal(s["performance"]["net_pnl"]) == 0
    assert s["last_trade"] is None and s["last_backtest"] is None
    assert s["backtest_completed"] is False
    assert "ema_fast" in s["parameter_schema"]["properties"]
    assert s["timeframes"]  # derived from the latest version's parameters


def test_strategy_detail_and_404(owner_client: TestClient) -> None:
    s = strategy(owner_client)
    detail = owner_client.get(f"/api/v1/strategies/{s['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == s["id"]
    assert owner_client.get(f"/api/v1/strategies/{uuid.uuid4()}").status_code == 404


def test_strategies_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/strategies").status_code == 401


def test_new_versions_increment_and_old_versions_are_immutable(
    owner_client: TestClient, db: Session
) -> None:
    s = strategy(owner_client)
    v1_params = s["versions"][0]["parameters"]
    v2 = new_version(owner_client, s["id"], ema_fast=20, ema_slow=100)
    assert v2["version"] == 2
    # Omitted parameters are filled with defaults and stored in full.
    assert v2["parameters"] == {**v1_params, "ema_fast": 20, "ema_slow": 100}
    v3 = new_version(owner_client, s["id"], ema_fast=30, ema_slow=120)
    assert v3["version"] == 3

    versions = strategy(owner_client)["versions"]
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert versions[0]["parameters"] == v1_params  # v1 untouched
    assert versions[1]["parameters"]["ema_fast"] == 20
    assert actions(db).count("strategy.version_created") == 2
    assert db.scalar(select(func.count()).select_from(StrategyVersion)) == 3


@pytest.mark.parametrize(
    "params",
    [
        {"ema_fast": 200, "ema_slow": 100},  # fast must be below slow
        {"ema_fast": 1},  # below minimum
        {"not_a_parameter": 5},  # extra keys are forbidden
        {"higher_timeframe": "M15", "entry_timeframe": "H1"},  # HTF must be above entry
        {"allow_long": False, "allow_short": False},
        {"entry_timeframe": "X9"},
    ],
)
def test_invalid_version_parameters_are_rejected(
    owner_client: TestClient, db: Session, params: dict[str, Any]
) -> None:
    s = strategy(owner_client)
    response = owner_client.post(
        f"/api/v1/strategies/{s['id']}/versions", json={"parameters": params}
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_strategy_config"
    assert db.scalar(select(func.count()).select_from(StrategyVersion)) == 1


def test_version_body_is_validated(owner_client: TestClient) -> None:
    s = strategy(owner_client)
    url = f"/api/v1/strategies/{s['id']}/versions"
    assert owner_client.post(url, json={}).status_code == 422
    too_long = owner_client.post(url, json={"parameters": {}, "notes": "x" * 501})
    assert too_long.status_code == 422


def test_version_for_unknown_strategy_is_404(owner_client: TestClient) -> None:
    response = owner_client.post(
        f"/api/v1/strategies/{uuid.uuid4()}/versions", json={"parameters": {}}
    )
    assert response.status_code == 404


def test_assignment_is_created_paused(
    owner_client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    response = assign(owner_client, setup["v1"]["id"], setup["account"]["id"])
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PAUSED"
    assert body["status_reason"] == "Created paused — enable deliberately"
    assert body["version"] == 1
    assert body["symbol"] == "EURUSD"
    assert body["account"]["id"] == setup["account"]["id"]
    assert body["last_evaluation"] is None and body["last_signal"] is None
    assert "strategy.assigned" in actions(db)
    assert strategy(owner_client)["status"] == "PAUSED"


def test_duplicate_assignment_conflicts(owner_client: TestClient, setup: dict[str, Any]) -> None:
    assert assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).status_code == 201
    again = assign(owner_client, setup["v1"]["id"], setup["account"]["id"])
    assert again.status_code == 409
    other_symbol = assign(owner_client, setup["v1"]["id"], setup["account"]["id"], "USDJPY")
    assert other_symbol.status_code == 201


def test_assignment_validation(owner_client: TestClient, setup: dict[str, Any]) -> None:
    missing_account = assign(owner_client, setup["v1"]["id"], str(uuid.uuid4()))
    assert missing_account.status_code == 404
    missing_version = assign(owner_client, str(uuid.uuid4()), setup["account"]["id"])
    assert missing_version.status_code == 404
    blank = assign(owner_client, setup["v1"]["id"], setup["account"]["id"], "   ")
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "invalid_strategy_config"
    too_short = assign(owner_client, setup["v1"]["id"], setup["account"]["id"], "EU")
    assert too_short.status_code == 422


def test_enable_requires_risk_profile(
    owner_client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    denied = owner_client.post(f"/api/v1/strategies/assignments/{a['id']}/enable")
    assert denied.status_code == 403
    assert denied.json()["error"]["message"] == "Assign a risk profile to the account first"
    assert "strategy.enabled" not in actions(db)

    give_profile(owner_client, setup["account"]["id"])
    enabled = owner_client.post(f"/api/v1/strategies/assignments/{a['id']}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "ENABLED"
    assert enabled.json()["status_reason"] == "Enabled by owner@example.com"
    assert strategy(owner_client)["status"] == "ENABLED"
    assert "strategy.enabled" in actions(db)


def test_pause_records_reason_and_notifies(
    owner_client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    give_profile(owner_client, setup["account"]["id"])
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    owner_client.post(f"/api/v1/strategies/assignments/{a['id']}/enable")
    paused = owner_client.post(
        f"/api/v1/strategies/assignments/{a['id']}/pause", json={"reason": "news week"}
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    assert paused.json()["status_reason"] == "news week"
    note = db.scalars(select(Notification).where(Notification.type == "strategy.paused")).one()
    assert note.message == "EURUSD: news week"
    assert "strategy.paused" in actions(db)


def test_switching_version_pauses_assignment(
    owner_client: TestClient, db: Session, setup: dict[str, Any]
) -> None:
    give_profile(owner_client, setup["account"]["id"])
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    owner_client.post(f"/api/v1/strategies/assignments/{a['id']}/enable")
    v2 = new_version(owner_client, setup["strategy"]["id"], ema_fast=20, ema_slow=100)
    switched = owner_client.put(
        f"/api/v1/strategies/assignments/{a['id']}/version",
        json={"strategy_version_id": v2["id"]},
    )
    assert switched.status_code == 200
    body = switched.json()
    assert body["status"] == "PAUSED"  # a new configuration must be re-enabled deliberately
    assert body["version"] == 2
    assert body["strategy_version_id"] == v2["id"]
    assert body["status_reason"] == "Switched to v2 — re-enable to trade"
    assert "strategy.modified" in actions(db)


def test_switch_to_unknown_version_is_404(owner_client: TestClient, setup: dict[str, Any]) -> None:
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    response = owner_client.put(
        f"/api/v1/strategies/assignments/{a['id']}/version",
        json={"strategy_version_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


def test_unknown_assignment_is_404_everywhere(owner_client: TestClient) -> None:
    missing = uuid.uuid4()
    base = f"/api/v1/strategies/assignments/{missing}"
    assert owner_client.post(f"{base}/enable").status_code == 404
    assert owner_client.post(f"{base}/pause", json={}).status_code == 404
    assert owner_client.delete(base).status_code == 404
    assert owner_client.get(f"{base}/evaluations").json() == []


def test_delete_assignment(owner_client: TestClient, db: Session, setup: dict[str, Any]) -> None:
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    assert owner_client.delete(f"/api/v1/strategies/assignments/{a['id']}").status_code == 204
    assert strategy(owner_client)["assignments"] == []
    assert "strategy.unassigned" in actions(db)
    # The slot is free again.
    assert assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).status_code == 201


def test_evaluations_start_empty_and_validate_limit(
    owner_client: TestClient, setup: dict[str, Any]
) -> None:
    a = assign(owner_client, setup["v1"]["id"], setup["account"]["id"]).json()
    url = f"/api/v1/strategies/assignments/{a['id']}/evaluations"
    assert owner_client.get(url).json() == []
    assert owner_client.get(f"{url}?limit=0").status_code == 422
    assert owner_client.get(f"{url}?limit=501").status_code == 422
