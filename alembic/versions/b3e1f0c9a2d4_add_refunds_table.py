"""add_refunds_table

Revision ID: b3e1f0c9a2d4
Revises: 622b710f2855
Create Date: 2026-09-22 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3e1f0c9a2d4'
down_revision: str | Sequence[str] | None = '622b710f2855'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ledger of refunds executed by the MCP execute_refund tool. The UNIQUE
    # constraint on request_id is the refund's idempotency guarantee.
    op.create_table(
        'refunds',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('request_id', name='uq_refunds_request_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('refunds')
