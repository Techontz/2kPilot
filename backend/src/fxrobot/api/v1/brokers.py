from __future__ import annotations

from fastapi import APIRouter

from fxrobot.api.deps import CurrentUserDep
from fxrobot.broker_engine import list_connectors
from fxrobot.schemas.brokers import ConnectorOut

router = APIRouter(prefix="/brokers", tags=["brokers"])


@router.get("/connectors", response_model=list[ConnectorOut])
def connectors(_: CurrentUserDep) -> list[ConnectorOut]:
    """Connection types and whether each one actually works on this server."""
    return [ConnectorOut.from_descriptor(d) for d in list_connectors()]
