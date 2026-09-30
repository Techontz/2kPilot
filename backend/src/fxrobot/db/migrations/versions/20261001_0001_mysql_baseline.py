"""MySQL baseline: users, sessions, append-only audit log, system trading state

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Naive UTC DATETIME(6) on MySQL (see fxrobot.db.types.UTCDateTime).
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


# audit_logs is append-only. MySQL does not fire triggers for FK cascade
# actions, so ON DELETE SET NULL of actor_user_id still works.
AUDIT_TRIGGERS = (
    "CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW "
    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'",
    "CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW "
    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "viewer",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", DT, nullable=True),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.CheckConstraint(
            "CAST(email AS BINARY) = CAST(LOWER(email) AS BINARY)",
            name=op.f("ck_users_email_lowercase"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "success",
                "failure",
                "denied",
                name="audit_outcome",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=60), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(
        "ix_audit_logs_action_occurred_at", "audit_logs", ["action", "occurred_at"], unique=False
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"], unique=False)
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"], unique=False)
    op.create_table(
        "system_state",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column(
            "trading_mode",
            sa.Enum(
                "BACKTEST",
                "DEMO",
                "LIVE",
                name="trading_mode",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default=sa.text("'DEMO'"),
            nullable=False,
        ),
        sa.Column(
            "kill_switch_engaged", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("kill_switch_reason", sa.Text(), nullable=True),
        sa.Column("kill_switch_changed_at", DT, nullable=True),
        sa.Column("kill_switch_changed_by", sa.Uuid(), nullable=True),
        sa.Column("mode_changed_at", DT, nullable=True),
        sa.Column("mode_changed_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_system_state_singleton")),
        sa.ForeignKeyConstraint(
            ["kill_switch_changed_by"],
            ["users.id"],
            name=op.f("fk_system_state_kill_switch_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["mode_changed_by"],
            ["users.id"],
            name=op.f("fk_system_state_mode_changed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_state")),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column(
            "last_seen_at", DT, server_default=sa.text("CURRENT_TIMESTAMP(6)"), nullable=False
        ),
        sa.Column("expires_at", DT, nullable=False),
        sa.Column("revoked_at", DT, nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(
        "ix_user_sessions_user_id_active", "user_sessions", ["user_id", "revoked_at"], unique=False
    )
    for statement in AUDIT_TRIGGERS:
        op.execute(statement)
    # Fresh installs start in DEMO with the kill switch ENGAGED.
    op.execute(
        "INSERT INTO system_state (id, trading_mode, kill_switch_engaged, kill_switch_reason) "
        "VALUES (1, 'DEMO', true, 'Initial state: trading has never been started')"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update")
    op.drop_table("user_sessions")
    op.drop_table("system_state")
    op.drop_table("audit_logs")
    op.drop_table("users")
