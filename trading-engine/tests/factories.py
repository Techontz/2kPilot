"""Create rows exactly as the Laravel backend does, for engine tests.

In production these rows are written by Laravel (Add Broker wizard, risk
profiles, strategy assignments, kill switch). Engine tests create them
directly so they can drive the engine without a PHP server.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fxrobot.broker_engine.factory import normalize_paper_settings
from fxrobot.db.types import utcnow
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import AssignmentStatus, ConnectionStatus, ConnectorType
from fxrobot.models import (
    BrokerConnection,
    RiskProfile,
    Strategy,
    StrategyAssignment,
    StrategyVersion,
    SystemState,
    TradingAccount,
)
from fxrobot.risk_engine.limits import RiskLimits
from fxrobot.services.risk_profiles import FIELDS
from fxrobot.services.strategies import ensure_builtin_strategies


def paper_account(db: Session, **settings: Any) -> TradingAccount:
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


def risk_profile(db: Session, **limits: Any) -> RiskProfile:
    values = RiskLimits.from_mapping(limits).as_json()
    profile = RiskProfile(name=f"test-{uuid.uuid4().hex[:6]}")
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
    strategy = db.scalars(select(Strategy)).first()
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


def assignment(
    db: Session, account: TradingAccount, version: StrategyVersion, symbol: str = "EURUSD"
) -> StrategyAssignment:
    row = StrategyAssignment(
        strategy_id=version.strategy_id,
        strategy_version_id=version.id,
        account_id=account.id,
        symbol=symbol,
        status=AssignmentStatus.ENABLED,
    )
    db.add(row)
    db.commit()
    return row


def resume_trading(db: Session) -> None:
    db.execute(update(SystemState).where(SystemState.id == 1).values(kill_switch_engaged=False))
    db.commit()


def stop_trading(db: Session) -> None:
    db.execute(update(SystemState).where(SystemState.id == 1).values(kill_switch_engaged=True))
    db.commit()
