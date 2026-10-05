"""Datasets (import, synthetic generation, broker download) and live market views."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.interface import BrokerAdapter
from fxrobot.core.errors import UnprocessableError
from fxrobot.domain.market import Timeframe
from fxrobot.domain.trading import DataSource
from fxrobot.market_data import store
from fxrobot.market_data.csv_import import CsvFormatError, parse_csv
from fxrobot.market_data.resample import resample
from fxrobot.market_data.synthetic import DEFAULT_SPECS, SyntheticSeries
from fxrobot.market_data.validation import validate_candles
from fxrobot.models import Dataset

MAX_SYNTHETIC_DAYS = 3650
DOWNLOAD_CHUNK_BARS = 5000


class DatasetError(UnprocessableError):
    code = "dataset_error"


def list_datasets(db: Session) -> list[Dataset]:
    return list(db.scalars(select(Dataset).order_by(Dataset.symbol, Dataset.timeframe)))


def import_csv(
    db: Session,
    *,
    symbol: str,
    timeframe: Timeframe,
    content: str,
    utc_offset_hours: float,
    filename: str,
) -> tuple[Dataset, dict[str, object]]:
    symbol = symbol.strip().upper()
    if not symbol.isalnum() or not 3 <= len(symbol) <= 20:
        raise DatasetError("Symbol must be 3–20 letters/digits, e.g. EURUSD")
    try:
        parsed = parse_csv(content, utc_offset_hours=utc_offset_hours)
    except CsvFormatError as exc:
        raise DatasetError(f"Could not read the CSV: {exc}") from exc
    if not parsed.candles:
        raise DatasetError("The file contains no valid candles")
    report = validate_candles(parsed.candles, timeframe)
    if report.misaligned > len(parsed.candles) * 0.05:
        raise DatasetError(
            f"{report.misaligned} bars are not aligned to {timeframe} boundaries — check the "
            "timeframe and the UTC offset."
        )
    dataset = store.get_or_create_dataset(
        db,
        symbol=symbol,
        timeframe=timeframe,
        source=DataSource.CSV,
        source_ref=filename[:120],
        description=f"Imported from {filename[:80]} (UTC offset {utc_offset_hours:+g}h)",
    )
    count = store.upsert_candles(db, dataset, parsed.candles)
    db.commit()
    return dataset, {
        "rows_read": parsed.rows_read,
        "imported": count,
        "dropped": parsed.dropped[:50],
        "dropped_count": len(parsed.dropped),
        "format": parsed.detected_format,
        "validation": report.summary(),
    }


def generate_synthetic(
    db: Session,
    *,
    symbol: str,
    timeframe: Timeframe,
    days: int,
    seed: int,
    now: datetime | None = None,
) -> Dataset:
    spec = DEFAULT_SPECS.get(symbol.upper())
    if spec is None:
        raise DatasetError(f"Synthetic data available for: {', '.join(sorted(DEFAULT_SPECS))}")
    if not 30 <= days <= MAX_SYNTHETIC_DAYS:
        raise DatasetError("Days must be between 30 and 3650")
    if timeframe.seconds < Timeframe.M15.seconds:
        raise DatasetError("Synthetic data is generated at M15 or coarser")
    end = Timeframe.D1.floor(now or datetime.now(UTC))
    start = end - timedelta(days=days)
    series = SyntheticSeries(spec, seed, start, Timeframe.M15)
    base = series.bars(start, end)
    candles = base if timeframe is Timeframe.M15 else resample(base, timeframe, until=end)
    dataset = store.get_or_create_dataset(
        db,
        symbol=spec.symbol,
        timeframe=timeframe,
        source=DataSource.SYNTHETIC,
        source_ref=f"seed-{seed}",
        description="SYNTHETIC — generated for testing. NOT real market data.",
    )
    store.upsert_candles(db, dataset, candles)
    db.commit()
    return dataset


def download_from_broker(
    db: Session,
    adapter: BrokerAdapter,
    *,
    connection_id: uuid.UUID,
    symbol: str,
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
) -> Dataset:
    if adapter.is_simulated:
        raise DatasetError("Paper connections don't provide real history; import a CSV or use MT5.")
    if end <= start:
        raise DatasetError("End must be after start")
    info = adapter.get_symbol(symbol)
    dataset = store.get_or_create_dataset(
        db,
        symbol=info.canonical_name,
        timeframe=timeframe,
        source=DataSource.BROKER,
        source_ref=str(connection_id),
        description=f"Downloaded from broker ({symbol})",
    )
    cursor, total = start, 0
    chunk = timeframe.delta * DOWNLOAD_CHUNK_BARS
    while cursor < end:
        stop = min(cursor + chunk, end)
        try:
            candles = adapter.get_candles(symbol, timeframe, cursor, stop)
        except BrokerError as exc:
            raise DatasetError(f"Download failed at {cursor:%Y-%m-%d}: {exc}") from exc
        if candles:
            total += store.upsert_candles(db, dataset, candles)
            db.commit()
        cursor = stop
    db.commit()
    return dataset
