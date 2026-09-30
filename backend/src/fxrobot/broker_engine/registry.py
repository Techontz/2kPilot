"""Catalog of broker connection types.

A connector is only reported AVAILABLE when a working adapter exists and
its runtime requirements are met. Nothing is shown as supported before it
actually works.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from enum import StrEnum


class ConnectorStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"  # adapter exists, but this host cannot run it
    PLANNED = "planned"  # adapter not implemented yet


@dataclass(frozen=True, slots=True)
class ConnectorField:
    name: str
    label: str
    secret: bool = False
    help: str = ""


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor:
    id: str
    name: str
    status: ConnectorStatus
    status_detail: str
    fields: tuple[ConnectorField, ...]


def _mt5_descriptor() -> ConnectorDescriptor:
    fields = (
        ConnectorField("login", "Account number", help="Your MT5 login (a number)."),
        ConnectorField("password", "Password", secret=True, help="Stored encrypted."),
        ConnectorField("server", "Server", help="e.g. 'ICMarketsSC-Demo' — shown in MT5."),
    )
    # The adapter itself ships in Phase 2. Report the honest reason it is not usable.
    if sys.platform != "win32" or importlib.util.find_spec("MetaTrader5") is None:
        detail = (
            "Adapter planned for Phase 2. Requires a Windows host running the "
            "MetaTrader 5 terminal and the MetaTrader5 Python package."
        )
    else:
        detail = "Adapter planned for Phase 2."
    return ConnectorDescriptor(
        id="mt5",
        name="MetaTrader 5",
        status=ConnectorStatus.PLANNED,
        status_detail=detail,
        fields=fields,
    )


def list_connectors() -> list[ConnectorDescriptor]:
    return [_mt5_descriptor()]
