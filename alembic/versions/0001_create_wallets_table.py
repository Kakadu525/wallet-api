"""create wallets table

Revision ID: 0001
Revises:
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "balance",
            sa.Numeric(precision=20, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint("balance >= 0", name="ck_wallet_balance_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("wallets")
