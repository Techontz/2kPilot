"""Model → JSON helpers. Secrets are never included."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fxrobot.models import (
    Backtest,
    BacktestTrade,
    BrokerConnection,
    Order,
    Signal,
    Trade,
    TradeEvent,
    TradingAccount,
)


def d(value: Decimal | None) -> str | None:
    """Decimal as a plain string without trailing zeros (DB columns carry fixed scale)."""
    return None if value is None else format(value.normalize(), "f")


def t(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def connection(c: BrokerConnection, live_status: str | None = None) -> dict[str, Any]:
    safe_settings = {
        k: v for k, v in (c.settings or {}).items() if k not in ("password", "bridge_secret")
    }
    return {
        "id": str(c.id),
        "label": c.label,
        "connector_type": c.connector_type.value,
        "expected_environment": c.expected_environment.value,
        "settings": safe_settings,
        "has_credentials": bool(c.credentials_encrypted),
        "status": live_status or c.status.value,
        "status_detail": c.status_detail,
        "is_enabled": c.is_enabled,
        "last_connected_at": t(c.last_connected_at),
        "last_error_at": t(c.last_error_at),
        "created_at": t(c.created_at),
    }


def account(a: TradingAccount, **extra: Any) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "connection_id": str(a.connection_id),
        "label": a.label,
        "broker_account_id": a.broker_account_id,
        "name": a.name,
        "server": a.server,
        "currency": a.currency,
        "environment": a.environment.value,
        "leverage": a.leverage,
        "trading_enabled": a.trading_enabled,
        "risk_profile_id": str(a.risk_profile_id) if a.risk_profile_id else None,
        "balance": d(a.balance),
        "equity": d(a.equity),
        "margin": d(a.margin),
        "free_margin": d(a.free_margin),
        "margin_level": d(a.margin_level),
        "synced_at": t(a.synced_at),
        **extra,
    }


def trade(x: Trade, **extra: Any) -> dict[str, Any]:
    return {
        "id": str(x.id),
        "account_id": str(x.account_id),
        "symbol": x.symbol,
        "side": x.side.value,
        "status": x.status.value,
        "volume": d(x.volume),
        "requested_entry": d(x.requested_entry),
        "entry_price": d(x.entry_price),
        "entry_time": t(x.entry_time),
        "stop_loss": d(x.stop_loss),
        "take_profit": d(x.take_profit),
        "initial_stop_loss": d(x.initial_stop_loss),
        "risk_amount": d(x.risk_amount),
        "spread_at_entry": d(x.spread_at_entry),
        "slippage_pips": d(x.slippage_pips),
        "session": x.session,
        "broker_position_id": x.broker_position_id,
        "exit_price": d(x.exit_price),
        "exit_time": t(x.exit_time),
        "exit_reason": x.exit_reason.value if x.exit_reason else None,
        "gross_pnl": d(x.gross_pnl),
        "commission": d(x.commission),
        "swap": d(x.swap),
        "net_pnl": d(x.net_pnl),
        "unrealized_pnl": d(x.unrealized_pnl),
        "r_multiple": d(x.r_multiple),
        "is_simulated": x.is_simulated,
        "signal_id": str(x.signal_id) if x.signal_id else None,
        "strategy_version_id": str(x.strategy_version_id) if x.strategy_version_id else None,
        **extra,
    }


def order(o: Order) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "client_order_id": o.client_order_id,
        "account_id": str(o.account_id),
        "signal_id": str(o.signal_id) if o.signal_id else None,
        "trade_id": str(o.trade_id) if o.trade_id else None,
        "purpose": o.purpose.value,
        "symbol": o.symbol,
        "side": o.side.value,
        "order_type": o.order_type.value,
        "volume": d(o.volume),
        "filled_volume": d(o.filled_volume),
        "requested_price": d(o.requested_price),
        "fill_price": d(o.fill_price),
        "stop_loss": d(o.stop_loss),
        "take_profit": d(o.take_profit),
        "status": o.status.value,
        "broker_order_id": o.broker_order_id,
        "broker_code": o.broker_code,
        "broker_message": o.broker_message,
        "attempts": o.attempts,
        "is_simulated": o.is_simulated,
        "created_at": t(o.created_at),
        "submitted_at": t(o.submitted_at),
        "filled_at": t(o.filled_at),
    }


def signal(s: Signal) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "account_id": str(s.account_id),
        "assignment_id": str(s.assignment_id) if s.assignment_id else None,
        "strategy_version_id": str(s.strategy_version_id),
        "symbol": s.symbol,
        "side": s.side.value,
        "timeframe": s.timeframe.value,
        "bar_time": t(s.bar_time),
        "entry_price": d(s.entry_price),
        "stop_loss": d(s.stop_loss),
        "take_profit": d(s.take_profit),
        "reasons": s.reasons,
        "status": s.status.value,
        "risk_checks": s.risk_checks,
        "rejection_reason": s.rejection_reason,
        "volume": d(s.volume),
        "risk_amount": d(s.risk_amount),
        "correlation_id": s.correlation_id,
        "created_at": t(s.created_at),
        "decided_at": t(s.decided_at),
    }


def event(e: TradeEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "occurred_at": t(e.occurred_at),
        "account_id": str(e.account_id) if e.account_id else None,
        "signal_id": str(e.signal_id) if e.signal_id else None,
        "order_id": str(e.order_id) if e.order_id else None,
        "trade_id": str(e.trade_id) if e.trade_id else None,
        "event_type": e.event_type,
        "message": e.message,
        "data": e.data,
        "correlation_id": e.correlation_id,
    }


def backtest(b: Backtest, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(b.id),
        "parent_id": str(b.parent_id) if b.parent_id else None,
        "kind": b.kind.value,
        "name": b.name,
        "status": b.status.value,
        "progress": b.progress,
        "strategy_key": b.strategy_key,
        "code_version": b.code_version,
        "symbol": b.symbol,
        "timeframe": b.timeframe.value,
        "data_source": b.data_source,
        "start": t(b.start),
        "end": t(b.end),
        "initial_capital": d(b.initial_capital),
        "error": b.error,
        "created_at": t(b.created_at),
        "finished_at": t(b.finished_at),
        "summary": {
            k: (b.metrics or {}).get(k)
            for k in (
                "net_pnl",
                "return_pct",
                "trades",
                "win_rate",
                "profit_factor",
                "max_drawdown_pct",
                "expectancy_r",
            )
        }
        if b.metrics
        else None,
        "warnings": (b.report or {}).get("warnings", []),
    }
    if full:
        out.update(
            {
                "parameters": b.parameters,
                "risk_settings": b.risk_settings,
                "costs": b.costs,
                "config": b.config,
                "metrics": b.metrics,
                "report": b.report,
                "data_checksum": b.data_checksum,
                "strategy_version_id": str(b.strategy_version_id)
                if b.strategy_version_id
                else None,
                "dataset_id": str(b.dataset_id) if b.dataset_id else None,
            }
        )
    return out


def backtest_trade(x: BacktestTrade) -> dict[str, Any]:
    return {
        "id": x.id,
        "side": x.side.value,
        "signal_time": t(x.signal_time),
        "entry_time": t(x.entry_time),
        "entry_price": d(x.entry_price),
        "exit_time": t(x.exit_time),
        "exit_price": d(x.exit_price),
        "exit_reason": x.exit_reason.value,
        "volume": d(x.volume),
        "stop_loss": d(x.stop_loss),
        "take_profit": d(x.take_profit),
        "risk_amount": d(x.risk_amount),
        "gross_pnl": d(x.gross_pnl),
        "costs": d(x.costs),
        "net_pnl": d(x.net_pnl),
        "r_multiple": d(x.r_multiple),
        "session": x.session,
        "reasons": x.reasons,
    }
