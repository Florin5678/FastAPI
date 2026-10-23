"""why Google access stopped (tokens.last_error)

Revision ID: b2d4f6a8c1e3
Revises: a1c5e7f9b2d4
Create Date: 2026-10-23 15:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d4f6a8c1e3"
down_revision: Union[str, Sequence[str], None] = "a1c5e7f9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Set when renewing the Google sign-in fails (e.g. it expired or was revoked); cleared on sign-in
    op.add_column("tokens", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("tokens", sa.Column("last_error_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "last_error_at")
    op.drop_column("tokens", "last_error")
