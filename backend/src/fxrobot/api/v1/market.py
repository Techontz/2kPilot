from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.core.errors import AppError, NotFoundError
from fxrobot.domain.market import Timeframe
from fxrobot.market_data import store
from fxrobot.market_data.sessions import calendar_span, is_fx_market_open, session_at
from fxrobot.market_data.validation import validate_candles
from fxrobot.models import Dataset, StrategyAssignment, TradingAccount
from fxrobot.services import market_data as svc

router = APIRouter(prefix="/market", tags=["market data"])

MAX_CSV_CHARS = 40_000_000


class ImportBody(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
    timeframe: Timeframe
    utc_offset_hours: float = Field(default=0, ge=-14, le=14)
    filename: str = Field(default="upload.csv", max_length=200)
    content: str = Field(min_length=10, max_length=MAX_CSV_CHARS)


class SyntheticBody(BaseModel):
    symbol: str
    timeframe: Timeframe = Timeframe.H1
    days: int = Field(default=730, ge=30, le=3650)
    seed: int = Field(default=42, ge=0, le=2**31)


class DownloadBody(BaseModel):
    account_id: uuid.UUID
    symbol: str
    timeframe: Timeframe
    start: datetime
    end: datetime


def _dataset(ds: Dataset) -> dict[str, Any]:
    return {
        "id": str(ds.id),
        "symbol": ds.symbol,
        "timeframe": ds.timeframe.value,
        "source": ds.source.value,
        "source_ref": ds.source_ref,
        "description": ds.description,
        "first_bar": ser.t(ds.first_bar),
        "last_bar": ser.t(ds.last_bar),
        "bar_count": ds.bar_count,
        "gap_count": ds.gap_count,
        "checksum": ds.checksum,
        "updated_at": ser.t(ds.updated_at),
    }


def _candle(c: Any) -> dict[str, Any]:
    return {
        "time": c.time.isoformat(),
        "open": str(c.open),
        "high": str(c.high),
        "low": str(c.low),
        "close": str(c.close),
        "volume": c.tick_volume,
        "spread_points": c.spread_points,
    }


def _adapter(db: DbDep, manager: ManagerDep, account_id: uuid.UUID):  # type: ignore[no-untyped-def]
    account = db.get(TradingAccount, account_id)
    if account is None:
        raise NotFoundError("Account not found")
    try:
        return account, manager.get(account.connection_id)
    except BrokerError as exc:
        raise AppError(f"Broker unavailable: {exc}", code="broker_unavailable") from exc


@router.get("/session")
def session(_: CurrentUserDep) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "time": now.isoformat(),
        "session": session_at(now).value,
        "market_open": is_fx_market_open(now),
    }


@router.get("/quotes")
def quotes(
    account_id: uuid.UUID, _: CurrentUserDep, db: DbDep, manager: ManagerDep
) -> dict[str, Any]:
    account, adapter = _adapter(db, manager, account_id)
    watched = {a.symbol for a in db.query(StrategyAssignment).filter_by(account_id=account.id)}
    try:
        symbols = adapter.get_symbols()
    except BrokerError as exc:
        raise AppError(f"Broker unavailable: {exc}", code="broker_unavailable") from exc
    names = [s.name for s in symbols if s.name in watched] + [
        s.name for s in symbols if s.name not in watched
    ]
    specs = {s.name: s for s in symbols}
    out = []
    for name in names[:16]:
        try:
            q = adapter.get_quote(name)
        except BrokerError:
            continue
        spec = specs[name]
        out.append(
            {
                "symbol": name,
                "bid": str(q.bid),
                "ask": str(q.ask),
                "time": q.time.isoformat(),
                "spread_pips": str((q.spread / spec.pip_size).quantize(Decimal("0.1"))),
                "age_seconds": int((adapter.now() - q.time).total_seconds()),
                "digits": spec.digits,
                "watched": name in watched,
            }
        )
    return {
        "account_id": str(account.id),
        "simulated": adapter.is_simulated,
        "server_time": adapter.now().isoformat(),
        "market_open": is_fx_market_open(adapter.now()),
        "session": session_at(adapter.now()).value,
        "quotes": out,
    }


@router.get("/candles")
def candles(
    account_id: uuid.UUID,
    symbol: str,
    _: CurrentUserDep,
    db: DbDep,
    manager: ManagerDep,
    timeframe: Timeframe = Timeframe.H1,
    bars: int = Query(default=200, ge=10, le=2000),
) -> dict[str, Any]:
    _, adapter = _adapter(db, manager, account_id)
    now = adapter.now()
    start = now - calendar_span(timeframe.seconds, bars)
    try:
        data = adapter.get_candles(symbol, timeframe, start, now)[-bars:]
    except BrokerError as exc:
        raise AppError(f"Could not load candles: {exc}", code="broker_unavailable") from exc
    report = validate_candles(data, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe.value,
        "simulated": adapter.is_simulated,
        "candles": [_candle(c) for c in data],
        "validation": report.summary(),
    }


@router.get("/datasets")
def datasets(_: CurrentUserDep, db: DbDep) -> list[dict[str, Any]]:
    return [_dataset(ds) for ds in svc.list_datasets(db)]


@router.get("/datasets/{dataset_id}/candles")
def dataset_candles(
    dataset_id: uuid.UUID,
    _: CurrentUserDep,
    db: DbDep,
    limit: int = Query(default=300, ge=10, le=5000),
) -> dict[str, Any]:
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise NotFoundError("Dataset not found")
    start = ds.last_bar - ds.timeframe.delta * limit if ds.last_bar else None
    data = store.load_candles(db, ds.id, start)[-limit:]
    return {
        "dataset": _dataset(ds),
        "candles": [_candle(c) for c in data],
        "validation": validate_candles(store.load_candles(db, ds.id), ds.timeframe).summary(),
    }


@router.post("/datasets/import", status_code=status.HTTP_201_CREATED)
def import_csv(body: ImportBody, owner: OwnerDep, db: DbDep, meta: MetaDep) -> dict[str, Any]:
    ds, report = svc.import_csv(
        db,
        symbol=body.symbol,
        timeframe=body.timeframe,
        content=body.content,
        utc_offset_hours=body.utc_offset_hours,
        filename=body.filename,
        actor=owner,
        meta=meta,
    )
    return {"dataset": _dataset(ds), "report": report}


@router.post("/datasets/synthetic", status_code=status.HTTP_201_CREATED)
def synthetic(body: SyntheticBody, owner: OwnerDep, db: DbDep, meta: MetaDep) -> dict[str, Any]:
    ds = svc.generate_synthetic(
        db,
        symbol=body.symbol,
        timeframe=body.timeframe,
        days=body.days,
        seed=body.seed,
        actor=owner,
        meta=meta,
    )
    return _dataset(ds)


@router.post("/datasets/download", status_code=status.HTTP_201_CREATED)
def download(
    body: DownloadBody, owner: OwnerDep, db: DbDep, meta: MetaDep, manager: ManagerDep
) -> dict[str, Any]:
    account, adapter = _adapter(db, manager, body.account_id)
    ds = svc.download_from_broker(
        db,
        adapter,
        connection_id=account.connection_id,
        symbol=body.symbol,
        timeframe=body.timeframe,
        start=body.start,
        end=body.end,
        actor=owner,
        meta=meta,
    )
    return _dataset(ds)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(dataset_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep) -> None:
    svc.delete_dataset(db, dataset_id, actor=owner, meta=meta)
