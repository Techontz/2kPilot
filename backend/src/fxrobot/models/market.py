from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import Price, str_enum
from fxrobot.domain.market import Timeframe
from fxrobot.domain.trading import DataSource


class Dataset(TimestampMixin, Base):
    """A stored candle series: one symbol, one timeframe, one source."""

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("source", "source_ref", "symbol", "timeframe", name="uq_datasets_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(20))  # canonical, e.g. EURUSD
    timeframe: Mapped[Timeframe] = mapped_column(str_enum(Timeframe, "timeframe", 8))
    source: Mapped[DataSource] = mapped_column(str_enum(DataSource, "data_source", 16))
    # Connection id for broker data, file name for CSV, seed for synthetic.
    source_ref: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(String(300), default="")
    first_bar: Mapped[datetime | None]
    last_bar: Mapped[datetime | None]
    bar_count: Mapped[int] = mapped_column(default=0)
    gap_count: Mapped[int] = mapped_column(default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")


class CandleRow(Base):
    """OHLCV bar. Clustered by (dataset, time) for fast range scans."""

    __tablename__ = "candles"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), primary_key=True
    )
    time: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Decimal] = mapped_column(Price())
    high: Mapped[Decimal] = mapped_column(Price())
    low: Mapped[Decimal] = mapped_column(Price())
    close: Mapped[Decimal] = mapped_column(Price())
    tick_volume: Mapped[int] = mapped_column(BigInteger, default=0)
    spread_points: Mapped[int | None]
