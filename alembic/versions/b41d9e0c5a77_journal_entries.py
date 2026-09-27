"""journal entries

Revision ID: b41d9e0c5a77
Revises: a7c3e1f92b10
Create Date: 2026-09-27 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b41d9e0c5a77"
down_revision: Union[str, Sequence[str], None] = "a7c3e1f92b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("mood", sa.String(length=32), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_journal_entries_id"), "journal_entries", ["id"], unique=False)
    op.create_index("ix_journal_entries_user_day", "journal_entries", ["user_id", "day"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        # Supabase exposes public tables via its Data API unless RLS is on
        op.execute("ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_journal_entries_user_day", table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_id"), table_name="journal_entries")
    op.drop_table("journal_entries")
