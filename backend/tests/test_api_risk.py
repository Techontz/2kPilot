"""Risk profiles: CRUD, validation, and live usage (api/v1/risk)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.models import AuditLog, RiskProfile
from fxrobot.risk_engine.limits import DEFAULT_LIMITS
from fxrobot.services.risk_profiles import DEFAULT_PROFILE_NAME
from tests.test_engine_pipeline import create_paper_account


def create(client: TestClient, name: str = "Swing", **limits: Any) -> Any:
    return client.post("/api/v1/risk/profiles", json={"name": name, "limits": limits})


def profiles(client: TestClient) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in client.get("/api/v1/risk/profiles").json()}


def dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)


def test_default_profile_is_seeded_with_default_limits(owner_client: TestClient) -> None:
    seeded = profiles(owner_client)
    assert list(seeded) == [DEFAULT_PROFILE_NAME]
    limits = seeded[DEFAULT_PROFILE_NAME]["limits"]
    for key, expected in DEFAULT_LIMITS.as_json().items():
        if isinstance(expected, str):
            assert dec(limits[key]) == Decimal(expected), key
        else:
            assert limits[key] == expected, key


def test_create_profile_merges_with_defaults(owner_client: TestClient, db: Session) -> None:
    response = create(
        owner_client,
        risk_per_trade_pct="1.25",
        max_trades_per_day=8,
        allowed_sessions=["london", "new_york"],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Swing"
    limits = body["limits"]
    assert dec(limits["risk_per_trade_pct"]) == Decimal("1.25")
    assert limits["max_trades_per_day"] == 8
    assert limits["allowed_sessions"] == ["LONDON", "NEW_YORK"]  # normalised
    assert dec(limits["max_daily_loss_pct"]) == DEFAULT_LIMITS.max_daily_loss_pct
    assert limits["max_data_age_seconds"] == DEFAULT_LIMITS.max_data_age_seconds
    audit_row = db.scalars(select(AuditLog).where(AuditLog.action == "risk.profile_created")).one()
    assert audit_row.target_id == body["id"]
    assert audit_row.details["max_trades_per_day"] == 8


def test_optional_limits_can_be_disabled(owner_client: TestClient) -> None:
    body = create(owner_client, max_trades_per_day=None, cooldown_after_losses=None).json()
    assert body["limits"]["max_trades_per_day"] is None
    assert body["limits"]["cooldown_after_losses"] is None


def test_duplicate_name_conflicts(owner_client: TestClient) -> None:
    assert create(owner_client).status_code == 201
    assert create(owner_client).status_code == 409
    assert create(owner_client, name=DEFAULT_PROFILE_NAME).status_code == 409


@pytest.mark.parametrize(
    ("limits", "fragment"),
    [
        ({"risk_per_trade_pct": "10"}, "risk_per_trade_pct must be between 0.01 and 5"),
        ({"risk_per_trade_pct": "0"}, "risk_per_trade_pct"),
        ({"max_daily_loss_pct": "0"}, "max_daily_loss_pct must be between 0 and 100"),
        ({"max_drawdown_pct": "150"}, "max_drawdown_pct"),
        ({"min_stop_pips": "50", "max_stop_pips": "10"}, "min_stop_pips cannot exceed"),
        ({"allowed_sessions": ["LONDON", "SYDNEY"]}, "allowed_sessions"),
        ({"max_data_age_seconds": 0}, "max_data_age_seconds must be positive"),
        ({"max_trades_per_day": "lots"}, "invalid literal"),
        ({"risk_per_trade_pct": "abc"}, ""),
    ],
)
def test_invalid_limits_are_rejected(
    owner_client: TestClient, db: Session, limits: dict[str, Any], fragment: str
) -> None:
    response = create(owner_client, **limits)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_risk_profile"
    assert fragment in response.json()["error"]["message"]
    assert db.scalar(select(func.count()).select_from(RiskProfile)) == 1  # only the default


def test_mandatory_limits_cannot_be_disabled(owner_client: TestClient) -> None:
    for field in ("risk_per_trade_pct", "max_data_age_seconds"):
        response = create(owner_client, name=f"no-{field}", **{field: None})
        assert response.status_code == 400, field


def test_name_is_required(owner_client: TestClient) -> None:
    assert create(owner_client, name="").status_code == 422
    blank = create(owner_client, name="   ")
    assert blank.status_code == 400
    assert blank.json()["error"]["message"] == "Name is required"


def test_unknown_limit_keys_are_ignored(owner_client: TestClient) -> None:
    body = create(owner_client, not_a_limit=5).json()
    assert "not_a_limit" not in body["limits"]


def test_update_profile_records_changes(owner_client: TestClient, db: Session) -> None:
    profile = create(owner_client).json()
    response = owner_client.put(
        f"/api/v1/risk/profiles/{profile['id']}",
        json={"name": "Swing v2", "limits": {"max_open_positions": 5}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Swing v2"
    assert body["limits"]["max_open_positions"] == 5
    assert body["limits"]["max_trades_per_day"] == DEFAULT_LIMITS.max_trades_per_day  # kept
    row = db.scalars(select(AuditLog).where(AuditLog.action == "risk.settings_changed")).one()
    assert row.details == {"changes": {"max_open_positions": [3, 5]}}


def test_invalid_update_leaves_profile_unchanged(owner_client: TestClient) -> None:
    profile = create(owner_client, risk_per_trade_pct="1").json()
    response = owner_client.put(
        f"/api/v1/risk/profiles/{profile['id']}", json={"limits": {"risk_per_trade_pct": "9"}}
    )
    assert response.status_code == 400
    assert dec(profiles(owner_client)["Swing"]["limits"]["risk_per_trade_pct"]) == Decimal(1)


def test_rename_to_existing_name_conflicts(owner_client: TestClient) -> None:
    profile = create(owner_client).json()
    response = owner_client.put(
        f"/api/v1/risk/profiles/{profile['id']}", json={"name": DEFAULT_PROFILE_NAME}
    )
    assert response.status_code == 409
    assert set(profiles(owner_client)) == {"Swing", DEFAULT_PROFILE_NAME}


def test_rename_to_blank_is_rejected(owner_client: TestClient) -> None:
    profile = create(owner_client).json()
    response = owner_client.put(f"/api/v1/risk/profiles/{profile['id']}", json={"name": "  "})
    assert response.status_code == 400
    assert "Swing" in profiles(owner_client)


def test_allowed_sessions_must_be_a_list(owner_client: TestClient) -> None:
    response = create(owner_client, allowed_sessions="LONDON")
    assert response.status_code == 400
    assert "must be a list" in response.json()["error"]["message"]


def test_update_unknown_profile_is_404(owner_client: TestClient) -> None:
    response = owner_client.put(f"/api/v1/risk/profiles/{uuid.uuid4()}", json={"limits": {}})
    assert response.status_code == 404


def test_delete_profile(owner_client: TestClient, db: Session) -> None:
    profile = create(owner_client).json()
    assert owner_client.delete(f"/api/v1/risk/profiles/{profile['id']}").status_code == 204
    assert "Swing" not in profiles(owner_client)
    assert "risk.profile_deleted" in list(db.scalars(select(AuditLog.action)))
    assert owner_client.delete(f"/api/v1/risk/profiles/{profile['id']}").status_code == 404


def test_cannot_delete_profile_assigned_to_account(owner_client: TestClient) -> None:
    profile = create(owner_client).json()
    account = create_paper_account(owner_client)
    owner_client.patch(f"/api/v1/accounts/{account['id']}", json={"risk_profile_id": profile["id"]})
    response = owner_client.delete(f"/api/v1/risk/profiles/{profile['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "This profile is assigned to an account"
    assert "Swing" in profiles(owner_client)


def test_usage_without_profile(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get(f"/api/v1/risk/usage/{account['id']}").json()
    assert body == {
        "account_id": account["id"],
        "profile": None,
        "recent_violations": [],
        "live": False,
    }


def test_usage_with_profile_reports_real_zeros(owner_client: TestClient) -> None:
    profile = create(owner_client, max_trades_per_day=4).json()
    account = create_paper_account(owner_client)
    owner_client.patch(f"/api/v1/accounts/{account['id']}", json={"risk_profile_id": profile["id"]})
    body = owner_client.get(f"/api/v1/risk/usage/{account['id']}").json()
    assert body["live"] is True
    assert body["profile"]["id"] == profile["id"]
    assert Decimal(body["equity"]) == Decimal(10000)
    assert body["currency"] == "USD"
    assert Decimal(body["daily_loss"]["amount"]) == 0
    assert body["daily_loss"]["pct"] == 0.0
    assert dec(body["daily_loss"]["limit_pct"]) == DEFAULT_LIMITS.max_daily_loss_pct
    assert body["positions"]["open"] == 0
    assert body["positions"]["max"] == DEFAULT_LIMITS.max_open_positions
    assert body["trades_today"] == {"count": 0, "max": 4}
    assert body["open_risk"]["unknown"] is False
    assert Decimal(body["open_risk"]["amount"]) == 0
    assert body["consecutive_losses"]["count"] == 0


def test_usage_unknown_account_is_404(owner_client: TestClient) -> None:
    assert owner_client.get(f"/api/v1/risk/usage/{uuid.uuid4()}").status_code == 404


def test_profiles_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/risk/profiles").status_code == 401
