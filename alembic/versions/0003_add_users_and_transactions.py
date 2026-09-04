"""add users, wallet ownership and transaction log

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("token_hash", name="uq_users_token_hash"),
    )

    # nullable ради безопасной миграции существующих строк.
    op.add_column(
        "wallets",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_wallets_owner_id_users",
        "wallets",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_wallets_owner_id", "wallets", ["owner_id"])

    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=8), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=2), nullable=False),
        sa.Column(
            "balance_after", sa.Numeric(precision=20, scale=2), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"], ["wallets.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("amount > 0", name="ck_tx_amount_positive"),
        sa.CheckConstraint(
            "type in ('DEPOSIT', 'WITHDRAW')", name="ck_tx_type_valid"
        ),
        sa.UniqueConstraint(
            "wallet_id", "idempotency_key", name="uq_tx_wallet_idempotency"
        ),
    )
    op.create_index(
        "ix_transactions_wallet_created",
        "transactions",
        ["wallet_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_wallet_created", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_wallets_owner_id", table_name="wallets")
    op.drop_constraint("fk_wallets_owner_id_users", "wallets", type_="foreignkey")
    op.drop_column("wallets", "owner_id")
    op.drop_table("users")
