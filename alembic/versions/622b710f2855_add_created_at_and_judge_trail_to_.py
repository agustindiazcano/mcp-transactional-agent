"""add_created_at_and_judge_trail_to_transactions

Revision ID: 622b710f2855
Revises: 5f889de3a5a3
Create Date: 2026-09-22 00:26:39.425603

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '622b710f2855'
down_revision: Union[str, Sequence[str], None] = '5f889de3a5a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Scoped to Phase 4's two additive columns only. Autogenerate also
    # proposed a 'uq_transactions_request_id' unique constraint, which is
    # pre-existing drift unrelated to this change (request_id is already the
    # primary key) -- left out here to keep this migration narrowly scoped.
    op.add_column('transactions', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('transactions', sa.Column('judge_trail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transactions', 'judge_trail')
    op.drop_column('transactions', 'created_at')
