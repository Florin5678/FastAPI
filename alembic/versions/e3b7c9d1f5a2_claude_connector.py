"""Claude connector: OAuth clients, tokens and the change log

Revision ID: e3b7c9d1f5a2
Revises: d8f1b3c6e2a4
Create Date: 2026-09-28 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3b7c9d1f5a2"
down_revision: Union[str, Sequence[str], None] = "d8f1b3c6e2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connector_clients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("info", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_connector_clients_id"), "connector_clients", ["id"], unique=False)
    op.create_index(op.f("ix_connector_clients_client_id"), "connector_clients", ["client_id"], unique=True)

    op.create_table(
        "connector_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("grant_id", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_connector_tokens_id"), "connector_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_connector_tokens_token_hash"), "connector_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_connector_tokens_grant_id"), "connector_tokens", ["grant_id"], unique=False)
    op.create_index(op.f("ix_connector_tokens_client_id"), "connector_tokens", ["client_id"], unique=False)

    op.create_table(
        "connector_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("tool", sa.String(length=60), nullable=False),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("undo", sa.JSON(), nullable=True),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_connector_changes_id"), "connector_changes", ["id"], unique=False)
    op.create_index("ix_connector_changes_user_created", "connector_changes", ["user_id", "created_at"], unique=False)

    if op.get_bind().dialect.name == "postgresql":
        # Supabase exposes public tables via its Data API unless RLS is on
        for table in ("connector_clients", "connector_tokens", "connector_changes"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_connector_changes_user_created", table_name="connector_changes")
    op.drop_index(op.f("ix_connector_changes_id"), table_name="connector_changes")
    op.drop_table("connector_changes")
    op.drop_index(op.f("ix_connector_tokens_client_id"), table_name="connector_tokens")
    op.drop_index(op.f("ix_connector_tokens_grant_id"), table_name="connector_tokens")
    op.drop_index(op.f("ix_connector_tokens_token_hash"), table_name="connector_tokens")
    op.drop_index(op.f("ix_connector_tokens_id"), table_name="connector_tokens")
    op.drop_table("connector_tokens")
    op.drop_index(op.f("ix_connector_clients_client_id"), table_name="connector_clients")
    op.drop_index(op.f("ix_connector_clients_id"), table_name="connector_clients")
    op.drop_table("connector_clients")
