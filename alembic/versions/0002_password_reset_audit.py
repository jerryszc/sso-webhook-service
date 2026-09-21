"""password reset tokens + audit logs"""

revision = "0002_password_reset_audit"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(length=512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pwd_reset_user_id", "password_reset_tokens", ["user_id"])
    op.create_index("ix_pwd_reset_expires_at", "password_reset_tokens", ["expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    from alembic import op

    op.drop_table("audit_logs")
    op.drop_table("password_reset_tokens")