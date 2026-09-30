"""Datasets (synthetic, CSV import, preview, delete) and live market views (api/v1/market)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fxrobot.models import AuditLog, Dataset
from fxrobot.models.market import CandleRow as Candle
from tests.test_engine_pipeline import create_paper_account

START = datetime(2024, 1, 2, 0, 0, tzinfo=UTC)  # a Tuesday


def generic_csv(rows: int = 30, start: datetime = START, step_hours: int = 1) -> str:
    lines = ["time,open,high,low,close,volume"]
    price = 1.1000
    for i in range(rows):
        moment = start + timedelta(hours=i * step_hours)
        o, c = price, price + 0.0005
        high, low = c + 0.0003, o - 0.0003
        lines.append(f"{moment:%Y-%m-%d %H:%M:%S},{o:.5f},{high:.5f},{low:.5f},{c:.5f},{100 + i}")
        price = c
    return "\n".join(lines) + "\n"


def import_csv(client: TestClient, content: str, **extra: Any) -> Any:
    body = {"symbol": "EURUSD", "timeframe": "H1", "filename": "eur.csv", "content": content}
    return client.post("/api/v1/market/datasets/import", json={**body, **extra})


def synthetic(client: TestClient, **extra: Any) -> Any:
    body = {"symbol": "EURUSD", "timeframe": "H4", "days": 30, "seed": 1}
    return client.post("/api/v1/market/datasets/synthetic", json={**body, **extra})


def dataset_count(db: Session) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Dataset)) or 0


# ── synthetic ────────────────────────────────────────────────────────────


def test_generate_synthetic_dataset(owner_client: TestClient, db: Session) -> None:
    response = synthetic(owner_client)
    assert response.status_code == 201, response.text
    ds = response.json()
    assert ds["symbol"] == "EURUSD"
    assert ds["timeframe"] == "H4"
    assert ds["source"] == "synthetic"
    assert ds["source_ref"] == "seed-1"
    assert "NOT real market data" in ds["description"]
    assert 100 <= ds["bar_count"] <= 30 * 6  # weekends are closed
    assert ds["first_bar"] < ds["last_bar"]
    assert len(ds["checksum"]) > 0
    assert [d["id"] for d in owner_client.get("/api/v1/market/datasets").json()] == [ds["id"]]
    assert "data.synthetic_generated" in list(db.scalars(select(AuditLog.action)))


def test_synthetic_is_deterministic_per_seed(owner_client: TestClient) -> None:
    first = synthetic(owner_client).json()
    again = synthetic(owner_client).json()
    assert again["id"] == first["id"]  # same key → same dataset, upserted
    assert again["checksum"] == first["checksum"]
    assert again["bar_count"] == first["bar_count"]
    other = synthetic(owner_client, seed=2).json()
    assert other["id"] != first["id"]
    assert other["checksum"] != first["checksum"]


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({"symbol": "XAUUSD"}, 400),
        ({"timeframe": "M5"}, 400),
        ({"days": 10}, 422),
        ({"days": 4000}, 422),
        ({"seed": -1}, 422),
        ({"timeframe": "W9"}, 422),
    ],
)
def test_invalid_synthetic_requests(
    owner_client: TestClient, db: Session, extra: dict[str, Any], status: int
) -> None:
    response = synthetic(owner_client, **extra)
    assert response.status_code == status, response.text
    if status == 400:
        assert response.json()["error"]["code"] == "dataset_error"
    assert dataset_count(db) == 0


# ── CSV import ───────────────────────────────────────────────────────────


def test_import_generic_csv(owner_client: TestClient, db: Session) -> None:
    response = import_csv(owner_client, generic_csv(30))
    assert response.status_code == 201, response.text
    body = response.json()
    report = body["report"]
    assert report["rows_read"] == 30
    assert report["imported"] == 30
    assert report["dropped_count"] == 0
    assert report["format"] == "generic"
    assert report["validation"]["bars"] == 30
    assert report["validation"]["misaligned"] == 0
    ds = body["dataset"]
    assert ds["source"] == "csv"
    assert ds["bar_count"] == 30
    assert ds["first_bar"] == "2024-01-02T00:00:00+00:00"
    assert ds["last_bar"] == "2024-01-03T05:00:00+00:00"
    assert "UTC offset +0h" in ds["description"]
    row = db.scalars(select(AuditLog).where(AuditLog.action == "data.imported")).one()
    assert row.details == {"symbol": "EURUSD", "timeframe": "H1", "bars": 30}


def test_import_applies_utc_offset(owner_client: TestClient) -> None:
    body = import_csv(owner_client, generic_csv(12), utc_offset_hours=2).json()
    assert body["dataset"]["first_bar"] == "2024-01-01T22:00:00+00:00"
    assert "UTC offset +2h" in body["dataset"]["description"]


def test_import_mt5_tab_separated_export(owner_client: TestClient) -> None:
    lines = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for i in range(10):
        lines.append(f"2024.01.02\t{i:02d}:00:00\t1.1\t1.1010\t1.0990\t1.1005\t50\t0\t12")
    body = import_csv(owner_client, "\n".join(lines)).json()
    assert body["report"]["format"] == "mt5"
    assert body["report"]["imported"] == 10
    candles = owner_client.get(f"/api/v1/market/datasets/{body['dataset']['id']}/candles").json()
    assert candles["candles"][0]["spread_points"] == 12
    assert candles["candles"][0]["volume"] == 50


def test_reimport_upserts_without_duplicates(owner_client: TestClient, db: Session) -> None:
    first = import_csv(owner_client, generic_csv(20)).json()["dataset"]
    second = import_csv(owner_client, generic_csv(25)).json()["dataset"]
    assert second["id"] == first["id"]
    assert second["bar_count"] == 25
    assert db.scalar(select(func.count()).select_from(Candle)) == 25


def test_bad_rows_are_dropped_and_reported(owner_client: TestClient) -> None:
    content = generic_csv(20) + "2024-01-05 00:00:00,abc,1,1,1,1\nnot-a-date,1,1,1,1,1\n"
    report = import_csv(owner_client, content).json()["report"]
    assert report["rows_read"] == 22
    assert report["imported"] == 20
    assert report["dropped_count"] == 2
    assert report["dropped"][0].startswith("line 22")


@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("date,price\n2024-01-01,1.1\n", "expected columns"),
        ("time,open,high,low,close\n", "no valid candles"),
        ("time,open,high,low,close\nxx,1,1,1,1\nyy,2,2,2,2\n", "no valid candles"),
    ],
)
def test_bad_csv_is_rejected(
    owner_client: TestClient, db: Session, content: str, fragment: str
) -> None:
    response = import_csv(owner_client, content)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "dataset_error"
    assert fragment in response.json()["error"]["message"]
    assert dataset_count(db) == 0


def test_non_finite_prices_are_rejected_not_crashing(owner_client: TestClient, db: Session) -> None:
    content = (
        "time,open,high,low,close\n2024-01-02 00:00,NaN,NaN,NaN,NaN\n2024-01-02 01:00,inf,inf,1,1\n"
    )
    response = import_csv(owner_client, content)
    assert response.status_code == 400, response.text
    assert dataset_count(db) == 0


def test_overflowing_volume_row_is_dropped(owner_client: TestClient) -> None:
    content = generic_csv(20) + "2024-01-05 00:00:00,1.1,1.2,1.0,1.1,inf\n"
    response = import_csv(owner_client, content)
    assert response.status_code == 201, response.text
    assert response.json()["report"]["imported"] == 20
    assert response.json()["report"]["dropped_count"] == 1


def test_misaligned_timeframe_is_rejected(owner_client: TestClient, db: Session) -> None:
    response = import_csv(owner_client, generic_csv(30), timeframe="D1")
    assert response.status_code == 400
    assert "not aligned to D1" in response.json()["error"]["message"]
    assert dataset_count(db) == 0


def test_import_request_validation(owner_client: TestClient, db: Session) -> None:
    assert import_csv(owner_client, "short").status_code == 422
    assert import_csv(owner_client, generic_csv(), utc_offset_hours=20).status_code == 422
    bad_symbol = import_csv(owner_client, generic_csv(), symbol="EUR/USD")
    assert bad_symbol.status_code == 400
    assert "Symbol must be" in bad_symbol.json()["error"]["message"]
    assert dataset_count(db) == 0


# ── preview & delete ─────────────────────────────────────────────────────


def test_dataset_preview(owner_client: TestClient) -> None:
    ds = import_csv(owner_client, generic_csv(40)).json()["dataset"]
    body = owner_client.get(f"/api/v1/market/datasets/{ds['id']}/candles?limit=10").json()
    assert body["dataset"]["id"] == ds["id"]
    assert len(body["candles"]) == 10
    assert body["candles"][-1]["time"] == ds["last_bar"]
    assert body["candles"][0] == {
        "time": "2024-01-03T06:00:00+00:00",
        "open": body["candles"][0]["open"],
        "high": body["candles"][0]["high"],
        "low": body["candles"][0]["low"],
        "close": body["candles"][0]["close"],
        "volume": 130,
        "spread_points": None,
    }
    assert body["validation"]["bars"] == 40  # validated over the whole dataset
    too_small = owner_client.get(f"/api/v1/market/datasets/{ds['id']}/candles?limit=5")
    assert too_small.status_code == 422


def test_delete_dataset(owner_client: TestClient, db: Session) -> None:
    ds = import_csv(owner_client, generic_csv(20)).json()["dataset"]
    assert owner_client.delete(f"/api/v1/market/datasets/{ds['id']}").status_code == 204
    assert owner_client.get("/api/v1/market/datasets").json() == []
    assert db.scalar(select(func.count()).select_from(Candle)) == 0
    assert "data.deleted" in list(db.scalars(select(AuditLog.action)))
    assert owner_client.delete(f"/api/v1/market/datasets/{ds['id']}").status_code == 404
    assert owner_client.get(f"/api/v1/market/datasets/{ds['id']}/candles").status_code == 404


def test_datasets_require_login(client: TestClient) -> None:
    assert client.get("/api/v1/market/datasets").status_code == 401


# ── live market views ───────────────────────────────────────────────────


def test_session_endpoint(owner_client: TestClient) -> None:
    body = owner_client.get("/api/v1/market/session").json()
    assert body["session"] in {"ASIA", "LONDON", "OVERLAP", "NEW_YORK", "CLOSED"}
    assert isinstance(body["market_open"], bool)
    datetime.fromisoformat(body["time"])


def test_quotes_from_paper_account(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get(f"/api/v1/market/quotes?account_id={account['id']}").json()
    assert body["simulated"] is True
    assert body["account_id"] == account["id"]
    quotes = {q["symbol"]: q for q in body["quotes"]}
    assert set(quotes) == {"EURUSD", "USDJPY"}
    eur = quotes["EURUSD"]
    assert float(eur["ask"]) > float(eur["bid"]) > 0
    assert eur["digits"] == 5
    assert eur["watched"] is False
    assert float(eur["spread_pips"]) > 0


def test_candles_from_paper_account(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    body = owner_client.get(
        f"/api/v1/market/candles?account_id={account['id']}&symbol=EURUSD&timeframe=H1&bars=50"
    ).json()
    assert body["simulated"] is True
    assert body["timeframe"] == "H1"
    assert len(body["candles"]) == 50
    times = [c["time"] for c in body["candles"]]
    assert times == sorted(times)
    assert body["validation"]["bars"] == 50


def test_market_views_unknown_account_is_404(owner_client: TestClient) -> None:
    missing = uuid.uuid4()
    assert owner_client.get(f"/api/v1/market/quotes?account_id={missing}").status_code == 404
    candles = owner_client.get(f"/api/v1/market/candles?account_id={missing}&symbol=EURUSD")
    assert candles.status_code == 404


def test_unknown_symbol_candles_is_reported(owner_client: TestClient) -> None:
    account = create_paper_account(owner_client)
    response = owner_client.get(f"/api/v1/market/candles?account_id={account['id']}&symbol=GBPJPY")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "broker_unavailable"


def test_paper_accounts_cannot_download_history(owner_client: TestClient, db: Session) -> None:
    account = create_paper_account(owner_client)
    response = owner_client.post(
        "/api/v1/market/datasets/download",
        json={
            "account_id": account["id"],
            "symbol": "EURUSD",
            "timeframe": "H1",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-02-01T00:00:00Z",
        },
    )
    assert response.status_code == 400
    assert "Paper connections don't provide real history" in response.json()["error"]["message"]
    assert dataset_count(db) == 0
