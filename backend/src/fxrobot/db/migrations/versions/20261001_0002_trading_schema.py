"""Trading schema: brokers, accounts, market data, strategies, risk, signals, orders, trades, journal, backtests, notifications

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Naive UTC DATETIME(6) on MySQL (see fxrobot.db.types.UTCDateTime).
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade() -> None:
    op.add_column("system_state", sa.Column("engine_owner", sa.String(length=100), nullable=True))
    op.add_column("system_state", sa.Column("engine_lease_until", DT, nullable=True))
    op.add_column("system_state", sa.Column("engine_heartbeat_at", DT, nullable=True))
    op.add_column("system_state", sa.Column("engine_detail", sa.String(length=500), nullable=True))
    op.add_column(
        "system_state",
        sa.Column("engine_degraded", sa.Boolean(), server_default=sa.text("0"), nullable=False),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "timeframe",
            sa.Enum(
                "M1",
                "M5",
                "M15",
                "M30",
                "H1",
                "H4",
                "D1",
                name="timeframe",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "broker",
                "csv",
                "synthetic",
                name="data_source",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("source_ref", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("first_bar", DT, nullable=True),
        sa.Column("last_bar", DT, nullable=True),
        sa.Column("bar_count", sa.Integer(), nullable=False),
        sa.Column("gap_count", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("source", "source_ref", "symbol", "timeframe", name="uq_datasets_key"),
    )
    op.create_table(
        "risk_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("risk_per_trade_pct", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("max_position_lots", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("max_open_positions", sa.Integer(), nullable=True),
        sa.Column("max_positions_per_symbol", sa.Integer(), nullable=True),
        sa.Column("max_total_exposure_lots", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("max_total_risk_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("max_daily_loss_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("max_weekly_loss_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("max_trades_per_day", sa.Integer(), nullable=True),
        sa.Column("max_spread_pips", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("max_slippage_pips", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("min_stop_pips", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("max_stop_pips", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("min_reward_risk", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("allowed_sessions", sa.JSON(), nullable=False),
        sa.Column("cooldown_after_losses", sa.Integer(), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=True),
        sa.Column("max_data_age_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_risk_profiles_name")),
    )
    op.create_table(
        "strategies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
        sa.UniqueConstraint("name", name=op.f("uq_strategies_name")),
    )
    op.create_table(
        "broker_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column(
            "connector_type",
            sa.Enum(
                "paper",
                "mt5_bridge",
                name="connector_type",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "expected_environment",
            sa.Enum(
                "PAPER",
                "DEMO",
                "LIVE",
                "UNKNOWN",
                name="expected_environment",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "CONNECTED",
                "DISCONNECTED",
                "RECONNECTING",
                "ERROR",
                name="connection_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'DISCONNECTED'"),
            nullable=False,
        ),
        sa.Column("status_detail", sa.String(length=500), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_connected_at", DT, nullable=True),
        sa.Column("last_error_at", DT, nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_broker_connections_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broker_connections")),
    )
    op.create_table(
        "candles",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("time", DT, nullable=False),
        sa.Column("open", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("high", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("low", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("tick_volume", sa.BigInteger(), nullable=False),
        sa.Column("spread_points", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_candles_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dataset_id", "time", name=op.f("pk_candles")),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("code_version", sa.String(length=20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_strategy_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_strategy_versions_strategy_id_strategies"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_versions")),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_versions_ver"),
    )
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_system_settings_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )
    op.create_table(
        "backtests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "SINGLE",
                "IN_SAMPLE",
                "OUT_OF_SAMPLE",
                "WALK_FORWARD",
                "WALK_FORWARD_WINDOW",
                "SENSITIVITY",
                "SENSITIVITY_RUN",
                name="backtest_kind",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="backtest_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("strategy_key", sa.String(length=60), nullable=False),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=True),
        sa.Column("code_version", sa.String(length=20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "timeframe",
            sa.Enum(
                "M1",
                "M5",
                "M15",
                "M30",
                "H1",
                "H4",
                "D1",
                name="backtest_timeframe",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("data_source", sa.String(length=16), nullable=False),
        sa.Column("data_checksum", sa.String(length=64), nullable=False),
        sa.Column("start", DT, nullable=False),
        sa.Column("end", DT, nullable=False),
        sa.Column("initial_capital", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("account_currency", sa.String(length=8), nullable=False),
        sa.Column("risk_settings", sa.JSON(), nullable=False),
        sa.Column("costs", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("started_at", DT, nullable=True),
        sa.Column("finished_at", DT, nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_backtests_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_backtests_dataset_id_datasets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["backtests.id"],
            name=op.f("fk_backtests_parent_id_backtests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_backtests_strategy_version_id_strategy_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtests")),
    )
    op.create_index("ix_backtests_created", "backtests", ["created_at"], unique=False)
    op.create_table(
        "broker_symbols",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("canonical", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("base_currency", sa.String(length=8), nullable=False),
        sa.Column("quote_currency", sa.String(length=8), nullable=False),
        sa.Column("digits", sa.Integer(), nullable=False),
        sa.Column("point", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("contract_size", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("volume_min", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("volume_max", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("volume_step", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("trade_allowed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["broker_connections.id"],
            name=op.f("fk_broker_symbols_connection_id_broker_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broker_symbols")),
        sa.UniqueConstraint("connection_id", "name", name="uq_broker_symbols_name"),
    )
    op.create_index(
        op.f("ix_broker_symbols_canonical"), "broker_symbols", ["canonical"], unique=False
    )
    op.create_table(
        "paper_states",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["broker_connections.id"],
            name=op.f("fk_paper_states_connection_id_broker_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("connection_id", name=op.f("pk_paper_states")),
    )
    op.create_table(
        "trading_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("broker_account_id", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("server", sa.String(length=200), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column(
            "environment",
            sa.Enum(
                "PAPER",
                "DEMO",
                "LIVE",
                "UNKNOWN",
                name="account_environment",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("leverage", sa.Integer(), nullable=True),
        sa.Column("trading_enabled", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("risk_profile_id", sa.Uuid(), nullable=True),
        sa.Column("balance", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("equity", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("margin", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("free_margin", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("margin_level", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("synced_at", DT, nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["broker_connections.id"],
            name=op.f("fk_trading_accounts_connection_id_broker_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["risk_profile_id"],
            ["risk_profiles.id"],
            name=op.f("fk_trading_accounts_risk_profile_id_risk_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trading_accounts")),
        sa.UniqueConstraint("connection_id", "broker_account_id", name="uq_trading_accounts_login"),
    )
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("taken_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("balance", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("equity", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("margin", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_account_snapshots_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_snapshots")),
    )
    op.create_index(
        "ix_account_snapshots_account_time",
        "account_snapshots",
        ["account_id", "taken_at"],
        unique=False,
    )
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("backtest_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column(
            "side",
            sa.Enum(
                "BUY", "SELL", name="bt_side", native_enum=False, create_constraint=True, length=8
            ),
            nullable=False,
        ),
        sa.Column("signal_time", DT, nullable=False),
        sa.Column("entry_time", DT, nullable=False),
        sa.Column("entry_price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("exit_time", DT, nullable=False),
        sa.Column("exit_price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column(
            "exit_reason",
            sa.Enum(
                "STOP_LOSS",
                "TAKE_PROFIT",
                "MANUAL",
                "EMERGENCY",
                "STRATEGY",
                "BROKER",
                "END_OF_TEST",
                name="bt_exit_reason",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("volume", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("stop_loss", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("take_profit", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("risk_amount", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("gross_pnl", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("costs", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("net_pnl", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("r_multiple", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("session", sa.String(length=20), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["backtest_id"],
            ["backtests.id"],
            name=op.f("fk_backtest_trades_backtest_id_backtests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_trades")),
    )
    op.create_index(
        "ix_backtest_trades_backtest",
        "backtest_trades",
        ["backtest_id", "entry_time"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "success",
                "warning",
                "critical",
                name="notification_severity",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("read_at", DT, nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_notifications_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index("ix_notifications_created", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_read", "notifications", ["read_at"], unique=False)
    op.create_table(
        "strategy_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ENABLED",
                "PAUSED",
                name="assignment_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'PAUSED'"),
            nullable=False,
        ),
        sa.Column("status_reason", sa.String(length=300), nullable=True),
        sa.Column("last_bar_evaluated", DT, nullable=True),
        sa.Column("last_signal_at", DT, nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_strategy_assignments_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_strategy_assignments_strategy_id_strategies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_strategy_assignments_strategy_version_id_strategy_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_assignments")),
        sa.UniqueConstraint("account_id", "strategy_id", "symbol", name="uq_assignments_target"),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=True),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column(
            "side",
            sa.Enum(
                "BUY", "SELL", name="side", native_enum=False, create_constraint=True, length=8
            ),
            nullable=False,
        ),
        sa.Column(
            "timeframe",
            sa.Enum(
                "M1",
                "M5",
                "M15",
                "M30",
                "H1",
                "H4",
                "D1",
                name="signal_timeframe",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column("bar_time", DT, nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "MARKET",
                "LIMIT",
                "STOP",
                name="signal_entry_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("entry_price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("stop_loss", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("take_profit", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "NEW",
                "APPROVED",
                "REJECTED",
                "SKIPPED",
                "EXECUTED",
                "FAILED",
                name="signal_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("risk_checks", sa.JSON(), nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("volume", sa.Numeric(precision=16, scale=4), nullable=True),
        sa.Column("risk_amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("decided_at", DT, nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_signals_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["strategy_assignments.id"],
            name=op.f("fk_signals_assignment_id_strategy_assignments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_signals_strategy_version_id_strategy_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
        sa.UniqueConstraint("assignment_id", "bar_time", "side", name="uq_signals_dedupe"),
    )
    op.create_index(
        "ix_signals_account_created", "signals", ["account_id", "created_at"], unique=False
    )
    op.create_table(
        "strategy_evaluations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("bar_time", DT, nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["strategy_assignments.id"],
            name=op.f("fk_strategy_evaluations_assignment_id_strategy_assignments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_evaluations")),
    )
    op.create_index(
        "ix_strategy_evaluations_assignment_bar",
        "strategy_evaluations",
        ["assignment_id", "bar_time"],
        unique=False,
    )
    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("strategy_version_id", sa.Uuid(), nullable=True),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column(
            "side",
            sa.Enum(
                "BUY",
                "SELL",
                name="trade_side",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "CLOSED",
                name="trade_status",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column("volume", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("requested_entry", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("entry_price", sa.Numeric(precision=24, scale=10), nullable=False),
        sa.Column("entry_time", DT, nullable=False),
        sa.Column("stop_loss", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("take_profit", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("initial_stop_loss", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("risk_amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("spread_at_entry", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("slippage_pips", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("session", sa.String(length=20), nullable=True),
        sa.Column("broker_position_id", sa.String(length=64), nullable=True),
        sa.Column("exit_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("exit_time", DT, nullable=True),
        sa.Column(
            "exit_reason",
            sa.Enum(
                "STOP_LOSS",
                "TAKE_PROFIT",
                "MANUAL",
                "EMERGENCY",
                "STRATEGY",
                "BROKER",
                "END_OF_TEST",
                name="exit_reason",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("gross_pnl", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("commission", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("swap", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("net_pnl", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("r_multiple", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_trades_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_trades_signal_id_signals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_version_id"],
            ["strategy_versions.id"],
            name=op.f("fk_trades_strategy_version_id_strategy_versions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
        sa.UniqueConstraint("account_id", "broker_position_id", name="uq_trades_broker_position"),
    )
    op.create_index("ix_trades_account_exit", "trades", ["account_id", "exit_time"], unique=False)
    op.create_index("ix_trades_account_status", "trades", ["account_id", "status"], unique=False)
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_order_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column(
            "purpose",
            sa.Enum(
                "ENTRY",
                "EXIT",
                name="order_purpose",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(length=40), nullable=False),
        sa.Column(
            "side",
            sa.Enum(
                "BUY",
                "SELL",
                name="order_side",
                native_enum=False,
                create_constraint=True,
                length=8,
            ),
            nullable=False,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "MARKET",
                "LIMIT",
                "STOP",
                name="order_type",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("volume", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("filled_volume", sa.Numeric(precision=16, scale=4), nullable=False),
        sa.Column("requested_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column("take_profit", sa.Numeric(precision=24, scale=10), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_SUBMIT",
                "SUBMITTED",
                "PENDING",
                "FILLED",
                "PARTIALLY_FILLED",
                "CANCELLED",
                "REJECTED",
                "UNKNOWN",
                "FAILED",
                name="order_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("broker_position_id", sa.String(length=64), nullable=True),
        sa.Column("broker_code", sa.String(length=64), nullable=True),
        sa.Column("broker_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("submitted_at", DT, nullable=True),
        sa.Column("filled_at", DT, nullable=True),
        sa.Column("last_reconciled_at", DT, nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_orders_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_orders_signal_id_signals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"], ["trades.id"], name=op.f("fk_orders_trade_id_trades"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("client_order_id", name=op.f("uq_orders_client_order_id")),
    )
    op.create_index(
        "ix_orders_account_created", "orders", ["account_id", "created_at"], unique=False
    )
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)
    op.create_table(
        "trade_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False
        ),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("trade_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["trading_accounts.id"],
            name=op.f("fk_trade_events_account_id_trading_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_trade_events_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_trade_events_signal_id_signals"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name=op.f("fk_trade_events_trade_id_trades"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_events")),
    )
    op.create_index(
        "ix_trade_events_account_time", "trade_events", ["account_id", "occurred_at"], unique=False
    )
    op.create_index("ix_trade_events_signal", "trade_events", ["signal_id"], unique=False)
    op.create_index("ix_trade_events_trade", "trade_events", ["trade_id"], unique=False)


def downgrade() -> None:
    op.drop_table("trade_events")
    op.drop_table("orders")
    op.drop_table("trades")
    op.drop_table("strategy_evaluations")
    op.drop_table("signals")
    op.drop_table("strategy_assignments")
    op.drop_table("notifications")
    op.drop_table("backtest_trades")
    op.drop_table("account_snapshots")
    op.drop_table("trading_accounts")
    op.drop_table("paper_states")
    op.drop_table("broker_symbols")
    op.drop_table("backtests")
    op.drop_table("system_settings")
    op.drop_table("strategy_versions")
    op.drop_table("candles")
    op.drop_table("broker_connections")
    op.drop_table("strategies")
    op.drop_table("risk_profiles")
    op.drop_table("datasets")
    op.drop_column("system_state", "engine_owner")
    op.drop_column("system_state", "engine_lease_until")
    op.drop_column("system_state", "engine_heartbeat_at")
    op.drop_column("system_state", "engine_detail")
    op.drop_column("system_state", "engine_degraded")
