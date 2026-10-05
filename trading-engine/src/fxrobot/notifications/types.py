"""Catalogue of notification types (stable identifiers used by UI filters)."""

from __future__ import annotations

from fxrobot.domain.trading import NotificationSeverity as Sev

TYPES: dict[str, tuple[Sev, str]] = {
    "broker.connected": (Sev.SUCCESS, "Broker connected"),
    "broker.disconnected": (Sev.WARNING, "Broker disconnected"),
    "broker.reconnected": (Sev.SUCCESS, "Broker reconnected"),
    "broker.error": (Sev.CRITICAL, "Broker error"),
    "signal.generated": (Sev.INFO, "Signal generated"),
    "risk.rejected": (Sev.WARNING, "Trade rejected by risk"),
    "risk.limit_reached": (Sev.CRITICAL, "Risk limit reached"),
    "order.submitted": (Sev.INFO, "Order submitted"),
    "order.rejected": (Sev.WARNING, "Order rejected"),
    "order.unknown": (Sev.CRITICAL, "Order outcome uncertain"),
    "position.opened": (Sev.SUCCESS, "Position opened"),
    "position.closed": (Sev.INFO, "Position closed"),
    "position.stop_loss": (Sev.WARNING, "Stop loss hit"),
    "position.take_profit": (Sev.SUCCESS, "Take profit reached"),
    "strategy.paused": (Sev.WARNING, "Strategy paused"),
    "trading.emergency_stop": (Sev.CRITICAL, "Emergency stop"),
    "trading.stopped": (Sev.WARNING, "Trading stopped"),
    "trading.resumed": (Sev.INFO, "Trading resumed"),
    "reconciliation.mismatch": (Sev.CRITICAL, "Reconciliation mismatch"),
    "data.stale": (Sev.WARNING, "Market data stale"),
    "system.error": (Sev.CRITICAL, "System error"),
    "backtest.completed": (Sev.INFO, "Backtest completed"),
    "backtest.failed": (Sev.WARNING, "Backtest failed"),
}
