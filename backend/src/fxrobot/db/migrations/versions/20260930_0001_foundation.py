"""foundation: users, sessions, audit log, system trading state

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# audit_logs is append-only. The only permitted UPDATE is the FK's
# ON DELETE SET NULL of actor_user_id when a user is removed.
AUDIT_APPEND_ONLY_FN = """
CREATE FUNCTION audit_logs_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_logs is append-only';
    END IF;
    IF NEW.actor_user_id IS NOT NULL
       OR (NEW.id, NEW.occurred_at, NEW.actor_label, NEW.action, NEW.outcome,
           NEW.target_type, NEW.target_id, NEW.ip_address, NEW.user_agent,
           NEW.correlation_id, NEW.details)
          IS DISTINCT FROM
          (OLD.id, OLD.occurred_at, OLD.actor_label, OLD.action, OLD.outcome,
           OLD.target_type, OLD.target_id, OLD.ip_address, OLD.user_agent,
           OLD.correlation_id, OLD.details)
    THEN
        RAISE EXCEPTION 'audit_logs is append-only';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("owner", "viewer", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=320), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column(
            "outcome", sa.Enum("success", "failure", "denied", name="audit_outcome"), nullable=False
        ),
        sa.Column("target_type", sa.String(length=60), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
    op.execute(AUDIT_APPEND_ONLY_FN)
    op.execute(
        "CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_append_only()"
    )

    op.create_table(
        "system_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "trading_mode",
            sa.Enum("BACKTEST", "DEMO", "LIVE", name="trading_mode"),
            server_default=sa.text("'DEMO'"),
            nullable=False,
        ),
        sa.Column("kill_switch_engaged", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("kill_switch_reason", sa.Text(), nullable=True),
        sa.Column("kill_switch_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kill_switch_changed_by", sa.Uuid(), nullable=True),
        sa.Column("mode_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mode_changed_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
    # Fresh installs start in DEMO with the kill switch ENGAGED.
    op.execute(
        "INSERT INTO system_state (id, trading_mode, kill_switch_engaged, kill_switch_reason) "
        "VALUES (1, 'DEMO', true, 'Initial state: trading has never been started')"
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id_active", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("system_state")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_append_only()")
    op.drop_index("ix_audit_logs_occurred_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action_occurred_at", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("users")
    for enum_name in ("trading_mode", "audit_outcome", "user_role"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
