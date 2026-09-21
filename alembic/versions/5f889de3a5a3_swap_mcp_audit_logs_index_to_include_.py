"""swap_mcp_audit_logs_index_to_include_tool

Revision ID: 5f889de3a5a3
Revises: 70b40799328f
Create Date: 2026-09-21 20:17:02.015078

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5f889de3a5a3'
down_revision: str | Sequence[str] | None = '70b40799328f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# NOTE: autogenerate again detected the same pre-existing, unrelated
# 'uq_transactions_request_id' drift already flagged (and deliberately left
# out) in migration 70b40799328f. Still not addressed here -- out of scope
# for the Phase 1.B rate-limiting index swap.
#
# Phase 1.B rate limiting (src/mcp_server/security/rate_limiter.py) filters
# mcp_audit_logs by client_id AND tool with a created_at range -- the old
# (client_id, created_at) index didn't cover tool, so Postgres had to filter
# it out of an unindexed column. (client_id, tool, created_at) matches the
# query shape exactly: equality, equality, range.


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index('ix_mcp_audit_logs_client_id_created_at', table_name='mcp_audit_logs')
    op.create_index(
        'ix_mcp_audit_logs_client_id_tool_created_at',
        'mcp_audit_logs',
        ['client_id', 'tool', 'created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mcp_audit_logs_client_id_tool_created_at', table_name='mcp_audit_logs')
    op.create_index(
        'ix_mcp_audit_logs_client_id_created_at', 'mcp_audit_logs', ['client_id', 'created_at']
    )
