"""salt on food log entries (Nutrition)

Revision ID: a1c5e7f9b2d4
Revises: f4a6c2e8b1d3
Create Date: 2026-10-06 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c5e7f9b2d4"
down_revision: Union[str, Sequence[str], None] = "f4a6c2e8b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing entries start at 0 g; their values are estimated afterwards
    op.add_column("nutrition_entries", sa.Column("salt", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("nutrition_entries", "salt")
