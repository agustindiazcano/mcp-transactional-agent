"""add_orders_table

Revision ID: c4d2a7e81f35
Revises: b3e1f0c9a2d4
Create Date: 2026-09-22 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4d2a7e81f35'
down_revision: str | Sequence[str] | None = 'b3e1f0c9a2d4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Purchases the MCP read tools serve as evidence. Schema only: sample rows
    # come from scripts/seed_orders.py, so these migrations can run against a
    # real (cloud) database without planting fake orders in it.
    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id', name='uq_orders_order_id'),
    )
    op.create_index('ix_orders_user_id', 'orders', ['user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_orders_user_id', table_name='orders')
    op.drop_table('orders')
