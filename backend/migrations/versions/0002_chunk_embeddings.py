"""Add nullable vectors; existing documents can be indexed without re-uploading."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("embedding", Vector(), nullable=True))
    op.add_column("chunks", sa.Column("embedding_model", sa.String(255), nullable=True))
    op.create_check_constraint(
        "ck_chunks_embedding_pair",
        "chunks",
        "(embedding IS NULL) = (embedding_model IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chunks_embedding_pair", "chunks", type_="check")
    op.drop_column("chunks", "embedding_model")
    op.drop_column("chunks", "embedding")
