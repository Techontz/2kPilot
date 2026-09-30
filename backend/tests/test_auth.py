from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.models import AuditLog, User, UserRole, UserSession
from fxrobot.services import auth as auth_service
from tests.conftest import OWNER_EMAIL, OWNER_PASSWORD, login


def test_login_sets_secure_session_cookies(client: TestClient, owner: User) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL.upper(), "password": OWNER_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["user"]["email"] == OWNER_EMAIL
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("fx_session="))
    csrf_cookie = next(c for c in set_cookie if c.startswith("fx_csrf="))
    assert "HttpOnly" in session_cookie and "samesite=strict" in session_cookie.lower()
    assert "HttpOnly" not in csrf_cookie
    assert "password" not in response.text.lower()


def test_session_token_is_stored_hashed(client: TestClient, owner: User, db: Session) -> None:
    login(client)
    raw = client.cookies["fx_session"]
    stored = db.scalar(select(UserSession.token_hash))
    assert stored and stored != raw and len(stored) == 64


def test_wrong_password_and_unknown_email_look_identical(client: TestClient, owner: User) -> None:
    wrong = client.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": "nope"})
    unknown = client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_inactive_user_cannot_log_in(client: TestClient, owner: User, db: Session) -> None:
    owner.is_active = False
    db.merge(owner)
    db.commit()
    response = client.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert response.status_code == 401


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_me_returns_current_user(owner_client: TestClient) -> None:
    assert owner_client.get("/api/v1/auth/me").json()["user"]["role"] == "owner"


def test_mutation_without_csrf_token_is_rejected(owner_client: TestClient) -> None:
    del owner_client.headers["X-CSRF-Token"]
    response = owner_client.post("/api/v1/trading/stop", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_mutation_with_wrong_csrf_token_is_rejected(owner_client: TestClient) -> None:
    owner_client.headers["X-CSRF-Token"] = "forged"
    assert owner_client.post("/api/v1/trading/stop", json={}).status_code == 403


def test_logout_revokes_session(owner_client: TestClient) -> None:
    token = owner_client.cookies["fx_session"]
    assert owner_client.post("/api/v1/auth/logout").status_code == 204
    owner_client.cookies.set("fx_session", token)  # replaying the old token must fail
    assert owner_client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(owner_client: TestClient, db: Session) -> None:
    session = db.scalars(select(UserSession)).one()
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    response = owner_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"


def test_idle_session_is_rejected(owner_client: TestClient, db: Session) -> None:
    session = db.scalars(select(UserSession)).one()
    session.last_seen_at = datetime.now(UTC) - timedelta(hours=3)
    db.commit()
    assert owner_client.get("/api/v1/auth/me").status_code == 401


def test_login_rate_limit(app_factory, owner: User) -> None:  # type: ignore[no-untyped-def]
    client = app_factory(login_rate_limit_attempts=3)
    for _ in range(3):
        bad = client.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": "x"})
        assert bad.status_code == 401
    # Even the correct password is refused while limited.
    limited = client.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0


def test_login_attempts_are_audited_without_secrets(
    client: TestClient, owner: User, db: Session
) -> None:
    client.post("/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": "wrong-pass"})
    login(client)
    actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["user.created", "auth.login.failed", "auth.login.succeeded"]
    for entry in db.scalars(select(AuditLog)):
        assert "wrong-pass" not in str(entry.details)
        assert OWNER_PASSWORD not in str(entry.details)


def test_self_hosted_domain_can_log_in(client: TestClient, db: Session) -> None:
    auth_service.create_user(
        db, email="owner@2kfx.local", password=OWNER_PASSWORD, display_name="O", role=UserRole.OWNER
    )
    db.commit()
    assert login(client, email="owner@2kfx.local")


def test_create_user_rejects_malformed_email(db: Session) -> None:
    with pytest.raises(ValueError, match="Invalid email"):
        auth_service.create_user(
            db, email="not-an-email", password=OWNER_PASSWORD, display_name="x", role=UserRole.OWNER
        )


def test_validation_errors_do_not_echo_input(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": 12345})
    assert response.status_code == 422
    response = client.post(
        "/api/v1/auth/login", json={"email": "x" * 400, "password": "s3cret-value"}
    )
    assert response.status_code == 422
    assert "s3cret-value" not in response.text


def test_forwarded_ip_trusted_only_from_configured_proxies(
    app_factory,
    owner: User,
    db: Session,  # type: ignore[no-untyped-def]
) -> None:
    # TestClient's peer is "testclient": untrusted by default, so the header is ignored.
    client = app_factory()
    login_with_header = {"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    client.post(
        "/api/v1/auth/login", json=login_with_header, headers={"X-Forwarded-For": "1.2.3.4"}
    )
    trusted = app_factory(trusted_proxies=["testclient"])
    trusted.post(
        "/api/v1/auth/login", json=login_with_header, headers={"X-Forwarded-For": "1.2.3.4"}
    )
    ips = [
        e.ip_address
        for e in db.scalars(
            select(AuditLog).where(AuditLog.action == "auth.login.succeeded").order_by(AuditLog.id)
        )
    ]
    assert ips == ["testclient", "1.2.3.4"]
