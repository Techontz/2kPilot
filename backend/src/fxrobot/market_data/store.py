"""Persistence for candle datasets (MySQL)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from fxrobot.domain.market import Candle, Timeframe
from fxrobot.domain.trading import DataSource
from fxrobot.market_data.validation import validate_candles
from fxrobot.models import CandleRow, Dataset

BATCH = 2000


def get_or_create_dataset(
    db: Session,
    *,
    symbol: str,
    timeframe: Timeframe,
    source: DataSource,
    source_ref: str = "",
    description: str = "",
) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(
            Dataset.symbol == symbol,
            Dataset.timeframe == timeframe,
            Dataset.source == source,
            Dataset.source_ref == source_ref,
        )
    )
    if dataset is None:
        dataset = Dataset(
            symbol=symbol,
            timeframe=timeframe,
            source=source,
            source_ref=source_ref,
            description=description,
        )
        db.add(dataset)
        db.flush()
    return dataset


def upsert_candles(db: Session, dataset: Dataset, candles: Sequence[Candle]) -> int:
    """Insert or update bars (idempotent by (dataset, time)), then refresh metadata."""
    rows = [
        {
            "dataset_id": dataset.id,
            "time": c.time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "tick_volume": c.tick_volume,
            "spread_points": c.spread_points,
        }
        for c in candles
    ]
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        stmt = mysql_insert(CandleRow).values(chunk)
        stmt = stmt.on_duplicate_key_update(
            open=stmt.inserted.open,
            high=stmt.inserted.high,
            low=stmt.inserted.low,
            close=stmt.inserted.close,
            tick_volume=stmt.inserted.tick_volume,
            spread_points=stmt.inserted.spread_points,
        )
        db.execute(stmt)
    refresh_metadata(db, dataset)
    return len(rows)


def load_candles(
    db: Session, dataset_id: uuid.UUID, start: datetime | None = None, end: datetime | None = None
) -> list[Candle]:
    stmt = select(CandleRow).where(CandleRow.dataset_id == dataset_id).order_by(CandleRow.time)
    if start is not None:
        stmt = stmt.where(CandleRow.time >= start)
    if end is not None:
        stmt = stmt.where(CandleRow.time < end)
    return [
        Candle(r.time, r.open, r.high, r.low, r.close, r.tick_volume, r.spread_points)
        for r in db.scalars(stmt)
    ]


def checksum(candles: Sequence[Candle]) -> str:
    h = hashlib.sha256()
    for c in candles:
        # Normalised so "1.1" and "1.1000000000" (DB scale) hash identically.
        prices = "|".join(format(v.normalize(), "f") for v in (c.open, c.high, c.low, c.close))
        h.update(f"{c.time.isoformat()}|{prices}\n".encode())
    return h.hexdigest()


def refresh_metadata(db: Session, dataset: Dataset) -> None:
    candles = load_candles(db, dataset.id)
    first_last = db.execute(
        select(func.min(CandleRow.time), func.max(CandleRow.time), func.count()).where(
            CandleRow.dataset_id == dataset.id
        )
    ).one()
    report = validate_candles(candles, dataset.timeframe)
    dataset.first_bar = first_last[0]
    dataset.last_bar = first_last[1]
    dataset.bar_count = int(first_last[2])
    dataset.gap_count = len(report.gaps)
    dataset.checksum = checksum(candles)
    db.flush()


def delete_dataset(db: Session, dataset: Dataset) -> None:
    db.execute(delete(CandleRow).where(CandleRow.dataset_id == dataset.id))
    db.delete(dataset)
    db.flush()
