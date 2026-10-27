"""Drop the unused pgvector column and extension.

Vectors live in Qdrant. This is idempotent: on a fresh database (whose baseline never
had the column) it does nothing; on a database created by V2's init scripts it removes
document_chunks.embedding and the vector extension, so the plain postgres image works.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    # Not restored: the column was never used and plain postgres has no vector type.
    pass
