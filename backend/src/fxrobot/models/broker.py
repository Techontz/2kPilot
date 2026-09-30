from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fxrobot.db.base import Base, TimestampMixin
from fxrobot.db.types import NOW_DEFAULT, Money, Price, Volume, str_enum, utcnow
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectionStatus, ConnectorType


class BrokerConnection(TimestampMixin, Base):
    """A configured way of reaching a broker (or the internal paper simulator).

    Secrets are stored only as Fernet ciphertext in `credentials_encrypted`
    and are never returned by the API.
    """

    __tablename__ = "broker_connections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(120))
    connector_type: Mapped[ConnectorType] = mapped_column(
        str_enum(ConnectorType, "connector_type", 24)
    )
    # What the user said this is. Verified against the broker-reported environment.
    expected_environment: Mapped[AccountEnvironment] = mapped_column(
        str_enum(AccountEnvironment, "expected_environment", 16)
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # non-secret config
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ConnectionStatus] = mapped_column(
        str_enum(ConnectionStatus, "connection_status", 16),
        default=ConnectionStatus.DISCONNECTED,
        server_default=text("'DISCONNECTED'"),
    )
    status_detail: Mapped[str | None] = mapped_column(String(500))
    is_enabled: Mapped[bool] = mapped_column(default=True, server_default=true())
    last_connected_at: Mapped[datetime | None]
    last_error_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    accounts: Mapped[list[TradingAccount]] = relationship(back_populates="connection")


class TradingAccount(TimestampMixin, Base):
    """A broker account reached through a connection. Environment is broker-reported."""

    __tablename__ = "trading_accounts"
    __table_args__ = (
        UniqueConstraint("connection_id", "broker_account_id", name="uq_trading_accounts_login"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE")
    )
    broker_account_id: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200), default="")
    server: Mapped[str] = mapped_column(String(200), default="")
    currency: Mapped[str] = mapped_column(String(8))
    environment: Mapped[AccountEnvironment] = mapped_column(
        str_enum(AccountEnvironment, "account_environment", 16)
    )
    leverage: Mapped[int | None]
    # Off by default: an account never trades merely because it was added.
    trading_enabled: Mapped[bool] = mapped_column(default=False, server_default=text("0"))
    risk_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_profiles.id", ondelete="SET NULL")
    )
    balance: Mapped[Decimal | None] = mapped_column(Money())
    equity: Mapped[Decimal | None] = mapped_column(Money())
    margin: Mapped[Decimal | None] = mapped_column(Money())
    free_margin: Mapped[Decimal | None] = mapped_column(Money())
    margin_level: Mapped[Decimal | None] = mapped_column(Money())
    synced_at: Mapped[datetime | None]

    connection: Mapped[BrokerConnection] = relationship(back_populates="accounts")


class AccountSnapshot(Base):
    """Balance/equity history — the source for equity curves and drawdown."""

    __tablename__ = "account_snapshots"
    __table_args__ = (Index("ix_account_snapshots_account_time", "account_id", "taken_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE")
    )
    taken_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=NOW_DEFAULT)
    balance: Mapped[Decimal] = mapped_column(Money())
    equity: Mapped[Decimal] = mapped_column(Money())
    margin: Mapped[Decimal | None] = mapped_column(Money())
    open_positions: Mapped[int] = mapped_column(default=0)


class BrokerSymbol(Base):
    """Symbol specification as reported by a connection's broker."""

    __tablename__ = "broker_symbols"
    __table_args__ = (UniqueConstraint("connection_id", "name", name="uq_broker_symbols_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(40))
    canonical: Mapped[str] = mapped_column(String(20), index=True)
    description: Mapped[str] = mapped_column(String(200), default="")
    base_currency: Mapped[str] = mapped_column(String(8))
    quote_currency: Mapped[str] = mapped_column(String(8))
    digits: Mapped[int]
    point: Mapped[Decimal] = mapped_column(Price())
    contract_size: Mapped[Decimal] = mapped_column(Money())
    volume_min: Mapped[Decimal] = mapped_column(Volume())
    volume_max: Mapped[Decimal] = mapped_column(Volume())
    volume_step: Mapped[Decimal] = mapped_column(Volume())
    trade_allowed: Mapped[bool]
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=NOW_DEFAULT
    )


class PaperState(Base):
    """Persisted internal state of a PAPER simulator connection (survives restarts)."""

    __tablename__ = "paper_states"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, server_default=NOW_DEFAULT
    )
