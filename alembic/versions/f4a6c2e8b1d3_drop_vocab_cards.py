"""drop vocab_cards (the Language widget was removed on 2026-09-30)

Revision ID: f4a6c2e8b1d3
Revises: e3b7c9d1f5a2
Create Date: 2026-10-01 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4a6c2e8b1d3"
down_revision: Union[str, Sequence[str], None] = "e3b7c9d1f5a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_vocab_cards_user_language_due", table_name="vocab_cards")
    op.drop_index(op.f("ix_vocab_cards_id"), table_name="vocab_cards")
    op.drop_table("vocab_cards")


def downgrade() -> None:
    # Recreates the (empty) table; the dropped rows are gone
    op.create_table(
        "vocab_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("word", sa.String(length=120), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("due", sa.Date(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("introduced_on", sa.Date(), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "language", "word", name="uq_vocab_cards_user_language_word"),
    )
    op.create_index(op.f("ix_vocab_cards_id"), "vocab_cards", ["id"], unique=False)
    op.create_index("ix_vocab_cards_user_language_due", "vocab_cards", ["user_id", "language", "due"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE vocab_cards ENABLE ROW LEVEL SECURITY")
