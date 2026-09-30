from fastapi.testclient import TestClient


def test_liveness(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_database_and_migrations(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "migrations": "ok"}}


def test_readiness_reports_unavailable_database(app_factory) -> None:  # type: ignore[no-untyped-def]
    client = app_factory(database_url="mysql+pymysql://root@127.0.0.1:1/nope")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_correlation_id_is_generated_and_echoed(client: TestClient) -> None:
    generated = client.get("/api/v1/health/live").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/api/v1/health/live", headers={"X-Request-ID": "trace-abc-12345"})
    assert echoed.headers["X-Request-ID"] == "trace-abc-12345"


def test_unsafe_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id\nwith newline"})
    assert response.headers["X-Request-ID"] != "bad id\nwith newline"


def test_security_headers(client: TestClient) -> None:
    headers = client.get("/api/v1/health/live").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    body = client.get("/api/v1/does-not-exist").json()
    assert body["error"]["code"] == "http_error"
    assert body["error"]["correlation_id"]
