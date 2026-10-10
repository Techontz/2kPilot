"""Create rows exactly as the Laravel backend does, for engine tests.

In production these rows are written by Laravel (sign-up, Add Broker wizard,
risk profiles, strategy assignments, STOP switches). Engine tests create them
directly so they can drive the engine without a PHP server. Rows belong to
the default test user (`ensure_user`) unless another owner is given.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from fxrobot.broker_engine.factory import normalize_paper_settings
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment, TradingMode
from fxrobot.domain.trading import AssignmentStatus, ConnectionStatus, ConnectorType
from fxrobot.models import (
    BrokerConnection,
    RiskProfile,
    Strategy,
    StrategyAssignment,
    StrategyVersion,
    SystemState,
    TradingAccount,
    UserTradingState,
)
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.services.risk_profiles import FIELDS
from fxrobot.services.strategies import ensure_builtin_strategies

DEFAULT_EMAIL = "owner@example.com"


def make_user(db: Session, email: str | None = None, role: str = "user") -> uuid.UUID:
    """A user as sign-up creates it: trading STOPPED in DEMO mode."""
    user_id = uuid.uuid4()
    db.execute(
        text(
            "INSERT INTO users (id, name, email, password, role) "
            "VALUES (:id, 'Test user', :email, 'x', :role)"
        ),
        {"id": str(user_id), "email": email or f"{user_id.hex[:10]}@example.com", "role": role},
    )
    db.add(UserTradingState(user_id=user_id, trading_mode=TradingMode.DEMO))
    db.commit()
    return user_id


def ensure_user(db: Session) -> uuid.UUID:
    """The default test user (created on first use)."""
    existing = db.scalar(text("SELECT id FROM users WHERE email = :e"), {"e": DEFAULT_EMAIL})
    return uuid.UUID(str(existing)) if existing else make_user(db, DEFAULT_EMAIL)


def paper_account(db: Session, owner: uuid.UUID | None = None, **settings: Any) -> TradingAccount:
    owner = owner or ensure_user(db)
    clean = normalize_paper_settings(
        {
            "price_source": "synthetic",
            "symbols": "EURUSD,USDJPY",
            "seconds_per_bar": 0,  # tests step the market manually
            "start_days_ago": 300,
            "seed": 3,
            **settings,
        }
    )
    connection = BrokerConnection(
        user_id=owner,
        label="Test paper",
        connector_type=ConnectorType.PAPER,
        expected_environment=AccountEnvironment.PAPER,
        settings=clean,
        status=ConnectionStatus.DISCONNECTED,
    )
    db.add(connection)
    db.flush()
    account = TradingAccount(
        connection_id=connection.id,
        user_id=owner,
        broker_account_id=f"PAPER-{str(connection.id)[:8].upper()}",
        label="Test paper",
        currency="USD",
        environment=AccountEnvironment.PAPER,
        trading_enabled=False,
        capabilities={},
        balance=Decimal(clean["initial_balance"]),
        equity=Decimal(clean["initial_balance"]),
    )
    db.add(account)
    db.commit()
    return account


def risk_profile(db: Session, owner: uuid.UUID | None = None, **limits: Any) -> RiskProfile:
    values = RiskLimits.from_mapping(limits).as_json()
    profile = RiskProfile(user_id=owner or ensure_user(db), name=f"test-{uuid.uuid4().hex[:6]}")
    for field in FIELDS:
        setattr(profile, field, values.get(field))
    db.add(profile)
    db.commit()
    return profile


def enable_account(db: Session, account: TradingAccount, profile: RiskProfile) -> None:
    account.risk_profile_id = profile.id
    account.trading_enabled = True
    db.commit()


def strategy_version(db: Session, **params: Any) -> StrategyVersion:
    ensure_builtin_strategies(db)
    strategy = db.scalars(
        select(Strategy).where(Strategy.key == "trend_pullback", Strategy.user_id.is_(None))
    ).first()
    assert strategy is not None
    base = db.scalars(
        select(StrategyVersion).where(StrategyVersion.strategy_id == strategy.id)
    ).first()
    assert base is not None
    version = StrategyVersion(
        strategy_id=strategy.id,
        version=base.version + 1,
        code_version=base.code_version,
        parameters={**base.parameters, **params},
        notes="test",
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    return version


def rules_version(
    db: Session, rules: dict[str, Any], owner: uuid.UUID | None = None
) -> StrategyVersion:
    """A user's own rule-based strategy (key "rules") with `rules` as version 1."""
    strategy = Strategy(
        user_id=owner or ensure_user(db),
        key="rules",
        name=f"rules-{uuid.uuid4().hex[:6]}",
        description="test",
        source="builder",
    )
    db.add(strategy)
    db.flush()
    version = StrategyVersion(
        strategy_id=strategy.id,
        version=1,
        code_version="1.0.0",
        parameters=rules,
        notes="test",
        created_at=utcnow(),
    )
    db.add(version)
    db.commit()
    return version


def assignment(
    db: Session,
    account: TradingAccount,
    version: StrategyVersion,
    symbol: str = "EURUSD",
    **contract: Any,
) -> StrategyAssignment:
    """`contract` = contract spec columns, e.g. contract_family=ContractFamily.RISE_FALL,
    duration=15, duration_unit="m"."""
    row = StrategyAssignment(
        strategy_id=version.strategy_id,
        strategy_version_id=version.id,
        account_id=account.id,
        symbol=symbol,
        status=AssignmentStatus.ENABLED,
        **contract,
    )
    db.add(row)
    db.commit()
    return row


def resume_trading(db: Session, user: uuid.UUID | None = None) -> None:
    """Release a user's own STOP switch (default: the default test user)."""
    _set_user_switch(db, user or ensure_user(db), engaged=False)


def stop_trading(db: Session, user: uuid.UUID | None = None) -> None:
    _set_user_switch(db, user or ensure_user(db), engaged=True)


def _set_user_switch(db: Session, user: uuid.UUID, *, engaged: bool) -> None:
    db.execute(
        update(UserTradingState)
        .where(UserTradingState.user_id == user)
        .values(kill_switch_engaged=engaged)
    )
    db.commit()


def set_mode(
    db: Session,
    mode: TradingMode,
    *,
    authorized: bool,
    user: uuid.UUID | None = None,
    account: TradingAccount | None = None,
) -> None:
    """Switch the owner's mode. A LIVE authorisation covers `account` (and its
    current risk profile) only — as Laravel records it."""
    db.execute(
        update(UserTradingState)
        .where(UserTradingState.user_id == (user or ensure_user(db)))
        .values(
            trading_mode=mode,
            live_authorized_at=utcnow() if authorized else None,
            live_authorized_account_id=account.id if authorized and account else None,
            live_authorized_profile_id=account.risk_profile_id if authorized and account else None,
        )
    )
    db.commit()


def halt_platform(db: Session, halted: bool = True) -> None:
    """The admin emergency halt (system_state)."""
    db.execute(update(SystemState).where(SystemState.id == 1).values(kill_switch_engaged=halted))
    db.commit()
