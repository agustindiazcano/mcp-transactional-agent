"""add_mcp_audit_logs_table

Revision ID: 70b40799328f
Revises: 7da4609fe11c
Create Date: 2026-09-21 19:09:18.332518

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '70b40799328f'
down_revision: str | Sequence[str] | None = '7da4609fe11c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: autogenerate also detected a missing 'uq_transactions_request_id'
# unique constraint on this local DB -- pre-existing drift unrelated to the
# Phase 1.B audit table, deliberately left out of this migration. Not
# addressed here; flag separately if it needs its own migration.


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'mcp_audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('client_id', sa.String(), nullable=False),
        sa.Column('tool', sa.String(), nullable=True),
        sa.Column('arguments', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('decision', sa.String(), nullable=False),
        sa.Column('result', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_mcp_audit_logs'),
    )
    op.create_index(
        'ix_mcp_audit_logs_client_id_created_at', 'mcp_audit_logs', ['client_id', 'created_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mcp_audit_logs_client_id_created_at', table_name='mcp_audit_logs')
    op.drop_table('mcp_audit_logs')
