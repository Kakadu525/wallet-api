"""add created_at / updated_at to wallets

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wallets",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "wallets",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Список кошельков сортируется по created_at.
    op.create_index("ix_wallets_created_at", "wallets", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_wallets_created_at", table_name="wallets")
    op.drop_column("wallets", "updated_at")
    op.drop_column("wallets", "created_at")
