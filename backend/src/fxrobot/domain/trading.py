"""Lifecycle vocabularies shared by the engines, the database and the API."""

from __future__ import annotations

from enum import StrEnum


class ConnectorType(StrEnum):
    PAPER = "paper"  # internal simulator
    MT5_BRIDGE = "mt5_bridge"  # MetaTrader 5 via the Windows bridge service


class ConnectionStatus(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(StrEnum):
    PENDING_SUBMIT = "PENDING_SUBMIT"  # persisted, not yet sent (crash-safe intent)
    SUBMITTED = "SUBMITTED"  # sent; awaiting broker confirmation
    PENDING = "PENDING"  # resting order at the broker
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"  # broker definitely refused; nothing executed
    UNKNOWN = "UNKNOWN"  # outcome not confirmed — requires reconciliation
    FAILED = "FAILED"  # confirmed never reached the broker

    @property
    def is_terminal(self) -> bool:
        return self in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        )

    @property
    def needs_reconciliation(self) -> bool:
        return self in (OrderStatus.SUBMITTED, OrderStatus.UNKNOWN, OrderStatus.PENDING_SUBMIT)


class OrderPurpose(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class SignalStatus(StrEnum):
    NEW = "NEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"  # by the risk engine (reasons stored)
    SKIPPED = "SKIPPED"  # not evaluated for trading (kill switch, mode, account disabled)
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"  # approved but execution failed / was rejected by the broker


class TradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    STRATEGY = "STRATEGY"
    BROKER = "BROKER"  # closed at the broker for a reason we could not classify
    END_OF_TEST = "END_OF_TEST"  # backtests only


class AssignmentStatus(StrEnum):
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"


class BacktestStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BacktestKind(StrEnum):
    SINGLE = "SINGLE"
    SPLIT = "SPLIT"  # parent of an in-sample / out-of-sample pair
    IN_SAMPLE = "IN_SAMPLE"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    WALK_FORWARD = "WALK_FORWARD"
    WALK_FORWARD_WINDOW = "WALK_FORWARD_WINDOW"
    SENSITIVITY = "SENSITIVITY"
    SENSITIVITY_RUN = "SENSITIVITY_RUN"


class DataSource(StrEnum):
    BROKER = "broker"  # downloaded from a connected broker (e.g. MT5)
    CSV = "csv"  # imported by the user
    SYNTHETIC = "synthetic"  # generated for development/testing — NOT real market data


class NotificationSeverity(StrEnum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    CRITICAL = "critical"


class EngineState(StrEnum):
    OFFLINE = "offline"  # no engine heartbeat
    RUNNING = "running"
    DEGRADED = "degraded"  # running, but some account/broker is unhealthy
