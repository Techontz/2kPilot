"""Catalog of broker connection types.

A connector is listed as AVAILABLE only when its adapter is implemented.
Whether a specific connection actually works is proven by the connection
test — the UI never shows a broker as connected without one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from fxrobot.domain.modes import AccountEnvironment
from fxrobot.domain.trading import ConnectorType


class ConnectorStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class ConnectorField:
    name: str
    label: str
    secret: bool = False
    help: str = ""
    kind: str = "text"  # text | password | number | select | boolean | url
    required: bool = True
    default: str | None = None
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConnectorDescriptor:
    id: str
    name: str
    status: ConnectorStatus
    status_detail: str
    environments: tuple[AccountEnvironment, ...]
    fields: tuple[ConnectorField, ...] = field(default_factory=tuple)


PAPER = ConnectorDescriptor(
    id=ConnectorType.PAPER.value,
    name="Paper / Simulation (internal)",
    status=ConnectorStatus.AVAILABLE,
    status_detail=(
        "Built-in simulator. No broker, no real money. Uses SYNTHETIC prices or replays "
        "stored historical data. Every order is labelled PAPER."
    ),
    environments=(AccountEnvironment.PAPER,),
    fields=(
        ConnectorField(
            "price_source",
            "Price source",
            kind="select",
            default="synthetic",
            options=("synthetic", "replay"),
            help="Synthetic = generated prices for testing. Replay = a stored dataset.",
        ),
        ConnectorField(
            "symbols",
            "Symbols",
            default="EURUSD,GBPUSD,USDJPY",
            help="Comma-separated. Synthetic supports EURUSD, GBPUSD, USDJPY, AUDUSD, "
            "USDCHF, USDCAD.",
        ),
        ConnectorField("initial_balance", "Starting balance", kind="number", default="10000"),
        ConnectorField(
            "currency", "Account currency", kind="select", default="USD", options=("USD",)
        ),
        ConnectorField("leverage", "Leverage", kind="number", default="100"),
        ConnectorField(
            "seconds_per_bar",
            "Simulation speed (seconds per 15-min bar)",
            kind="number",
            default="2",
            help="Lower = faster. The simulation never runs ahead of real time.",
        ),
        ConnectorField(
            "start_days_ago",
            "Start the simulation N days ago",
            kind="number",
            default="30",
            required=False,
        ),
        ConnectorField(
            "dataset_symbol_map",
            "Replay datasets",
            required=False,
            help="Replay only: chosen in the wizard from your stored datasets.",
        ),
    ),
)

MT5 = ConnectorDescriptor(
    id=ConnectorType.MT5_BRIDGE.value,
    name="MetaTrader 5 (via 2kFX MT5 Bridge)",
    status=ConnectorStatus.AVAILABLE,
    status_detail=(
        "Requires the 2kFX MT5 Bridge running on a Windows PC/VPS next to a logged-in "
        "MetaTrader 5 terminal. See docs/MT5_BRIDGE_SETUP.md."
    ),
    environments=(AccountEnvironment.DEMO, AccountEnvironment.LIVE),
    fields=(
        ConnectorField(
            "bridge_url",
            "Bridge URL",
            kind="url",
            help="e.g. https://10.0.0.5:8710 (use HTTPS or a private tunnel).",
        ),
        ConnectorField(
            "bridge_secret",
            "Bridge secret",
            secret=True,
            kind="password",
            help="The BRIDGE_SECRET configured on the bridge (≥32 characters).",
        ),
        ConnectorField("login", "MT5 account number"),
        ConnectorField(
            "password",
            "MT5 password",
            secret=True,
            kind="password",
            help="Stored encrypted; never shown again.",
        ),
        ConnectorField(
            "server", "MT5 server", help="Exactly as shown in MT5, e.g. 'ICMarketsSC-Demo'."
        ),
        ConnectorField(
            "verify_tls", "Verify TLS certificate", kind="boolean", default="true", required=False
        ),
    ),
)


def list_connectors() -> list[ConnectorDescriptor]:
    return [PAPER, MT5]


def get_connector(connector_id: str) -> ConnectorDescriptor | None:
    return next((c for c in list_connectors() if c.id == connector_id), None)
