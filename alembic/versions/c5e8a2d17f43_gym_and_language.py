"""workouts and vocab cards (Gym and Language widgets)

Revision ID: c5e8a2d17f43
Revises: b41d9e0c5a77
Create Date: 2026-09-28 01:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5e8a2d17f43"
down_revision: Union[str, Sequence[str], None] = "b41d9e0c5a77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workouts_id"), "workouts", ["id"], unique=False)
    op.create_index("ix_workouts_user_day", "workouts", ["user_id", "day"], unique=False)

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
        # Supabase exposes public tables via its Data API unless RLS is on
        op.execute("ALTER TABLE workouts ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE vocab_cards ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_vocab_cards_user_language_due", table_name="vocab_cards")
    op.drop_index(op.f("ix_vocab_cards_id"), table_name="vocab_cards")
    op.drop_table("vocab_cards")
    op.drop_index("ix_workouts_user_day", table_name="workouts")
    op.drop_index(op.f("ix_workouts_id"), table_name="workouts")
    op.drop_table("workouts")
