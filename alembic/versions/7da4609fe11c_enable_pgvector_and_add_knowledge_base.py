"""enable_pgvector_and_add_knowledge_base

Revision ID: 7da4609fe11c
Revises: 6223070eec00
Create Date: 2026-09-21 12:56:43.805286

"""
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7da4609fe11c'
down_revision: str | Sequence[str] | None = '6223070eec00'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match src/core/models.py's KnowledgeBase.embedding dimension (Gemini
# text-embedding-004 by default). See Phase 1.D in README.md/CLAUDE.md for
# why this is provider-agnostic rather than fixed to AWS Bedrock Titan.
EMBEDDING_DIM = 768


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table(
        'knowledge_base',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_tier', sa.String(), nullable=False, server_default='official'),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(EMBEDDING_DIM), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_base'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('knowledge_base')
    # Extension intentionally not dropped: other tables/columns may come to
    # depend on it later in Phase 1.D/Phase 2, and CLAUDE.md Section 8 flags
    # dropping pgvector as a destructive operation requiring confirmation.
