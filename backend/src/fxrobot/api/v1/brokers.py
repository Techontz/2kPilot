from __future__ import annotations

import contextlib
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from fxrobot.api import serializers as ser
from fxrobot.api.deps import CurrentUserDep, DbDep, ManagerDep, MetaDep, OwnerDep, SettingsDep
from fxrobot.broker_engine.errors import BrokerError
from fxrobot.broker_engine.registry import list_connectors
from fxrobot.core.errors import NotFoundError
from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectorType
from fxrobot.models import BrokerConnection
from fxrobot.services import brokers as svc

router = APIRouter(prefix="/brokers", tags=["brokers"])


class ConnectionBody(BaseModel):
    connector_type: ConnectorType
    expected_environment: AccountEnvironment
    settings: dict[str, Any] = Field(default_factory=dict)
    # Write-only. Never echoed back, never logged.
    credentials: dict[str, str] = Field(default_factory=dict)
    label: str = Field(default="", max_length=120)

    def to_input(self) -> svc.ConnectionInput:
        return svc.ConnectionInput(
            self.connector_type,
            self.expected_environment,
            self.settings,
            self.credentials,
            self.label,
        )


class CreateConnectionBody(ConnectionBody):
    risk_profile_id: uuid.UUID | None = None
    acknowledge_live: bool = False


@router.get("/connectors")
def connectors(_: CurrentUserDep) -> list[dict[str, Any]]:
    """Connection types and whether each adapter is implemented."""
    return [
        {
            "id": c.id,
            "name": c.name,
            "status": c.status.value,
            "status_detail": c.status_detail,
            "environments": [e.value for e in c.environments],
            "fields": [asdict(f) | {"options": list(f.options)} for f in c.fields],
        }
        for c in list_connectors()
    ]


@router.get("/connections")
def connections(_: CurrentUserDep, db: DbDep, manager: ManagerDep) -> list[dict[str, Any]]:
    out = []
    for c in svc.list_connections(db):
        live = manager.status(c.id).value if manager.peek(c.id) else None
        out.append(ser.connection(c, live) | {"accounts": [ser.account(a) for a in c.accounts]})
    return out


@router.post("/connections/test")
def test_connection(body: ConnectionBody, _: OwnerDep, db: DbDep) -> dict[str, Any]:
    """Steps 3–5 of the wizard: connect, verify the account and its environment. Saves nothing."""
    outcome = svc.test_connection(db, body.to_input())
    a = outcome.account
    return {
        "account": {
            "account_id": a.account_id,
            "name": a.name,
            "server": a.server,
            "currency": a.currency,
            "environment": a.environment.value,
            "balance": ser.d(a.balance),
            "equity": ser.d(a.equity),
            "leverage": a.leverage,
            "trade_allowed": a.trade_allowed,
        },
        "symbol_count": outcome.symbol_count,
        "warnings": outcome.warnings,
    }


@router.post("/connections", status_code=status.HTTP_201_CREATED)
def create_connection(
    body: CreateConnectionBody,
    owner: OwnerDep,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    manager: ManagerDep,
) -> dict[str, Any]:
    account = svc.create_connection(
        db,
        body.to_input(),
        actor=owner,
        meta=meta,
        settings=settings,
        risk_profile_id=body.risk_profile_id,
        acknowledge_live=body.acknowledge_live,
    )
    try:
        adapter = manager.get(account.connection_id)
        svc.sync_symbols(db, account.connection, adapter)
    except BrokerError:
        pass  # status is tracked by the manager; the account is saved either way
    return ser.account(account)


@router.post("/connections/{connection_id}/reconnect")
def reconnect(
    connection_id: uuid.UUID, _: OwnerDep, db: DbDep, manager: ManagerDep
) -> dict[str, Any]:
    connection = db.get(BrokerConnection, connection_id)
    if connection is None:
        raise NotFoundError("Connection not found")
    manager.evict(connection_id)
    with contextlib.suppress(BrokerError):
        manager.get(connection_id)
    db.refresh(connection)
    return ser.connection(connection, manager.status(connection_id).value)


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(
    connection_id: uuid.UUID, owner: OwnerDep, db: DbDep, meta: MetaDep, manager: ManagerDep
) -> None:
    svc.delete_connection(db, connection_id, actor=owner, meta=meta, manager=manager)
