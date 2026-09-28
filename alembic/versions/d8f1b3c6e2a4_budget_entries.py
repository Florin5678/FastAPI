"""budget entries (Budget widget)

Revision ID: d8f1b3c6e2a4
Revises: c5e8a2d17f43
Create Date: 2026-09-28 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8f1b3c6e2a4"
down_revision: Union[str, Sequence[str], None] = "c5e8a2d17f43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("sub1", sa.String(length=120), nullable=True),
        sa.Column("sub2", sa.String(length=120), nullable=True),
        sa.Column("sub3", sa.String(length=120), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_budget_entries_id"), "budget_entries", ["id"], unique=False)
    op.create_index("ix_budget_entries_user_month", "budget_entries", ["user_id", "month"], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        # Supabase exposes public tables via its Data API unless RLS is on
        op.execute("ALTER TABLE budget_entries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_budget_entries_user_month", table_name="budget_entries")
    op.drop_index(op.f("ix_budget_entries_id"), table_name="budget_entries")
    op.drop_table("budget_entries")
