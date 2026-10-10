"""ORM mappings of the MySQL schema (created by Laravel migrations in backend/)."""

from fxrobot.models.audit import AuditLog, AuditOutcome
from fxrobot.models.backtest import Backtest, BacktestTrade
from fxrobot.models.broker import (
    AccountSnapshot,
    BrokerConnection,
    BrokerSymbol,
    PaperState,
    TradingAccount,
)
from fxrobot.models.market import CandleRow, Dataset
from fxrobot.models.notification import Notification
from fxrobot.models.risk import RiskProfile
from fxrobot.models.strategy import (
    Strategy,
    StrategyAssignment,
    StrategyEvaluation,
    StrategyVersion,
)
from fxrobot.models.system import SystemSetting, SystemState
from fxrobot.models.trading import Order, Signal, Trade, TradeEvent
from fxrobot.models.user import User, UserTradingState

__all__ = [
    "AccountSnapshot",
    "AuditLog",
    "AuditOutcome",
    "Backtest",
    "BacktestTrade",
    "BrokerConnection",
    "BrokerSymbol",
    "CandleRow",
    "Dataset",
    "Notification",
    "Order",
    "PaperState",
    "RiskProfile",
    "Signal",
    "Strategy",
    "StrategyAssignment",
    "StrategyEvaluation",
    "StrategyVersion",
    "SystemSetting",
    "SystemState",
    "Trade",
    "TradeEvent",
    "TradingAccount",
    "User",
    "UserTradingState",
]
