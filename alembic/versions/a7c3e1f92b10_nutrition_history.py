"""nutrition history tables

Moves the Nutrition widget's food log out of the widget's integrations row
(config["log"], last 14 days only) into real tables so every day is kept.

Revision ID: a7c3e1f92b10
Revises: 30b4b082cde5
Create Date: 2026-09-27 21:00:00

"""
from datetime import date, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c3e1f92b10"
down_revision: Union[str, Sequence[str], None] = "30b4b082cde5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NUTRIENTS = ["calories", "protein", "carbs", "fat", "fiber", "sugar", "sat_fat"]
# Starting goals (same as app/widgets/nutrition.py), used when a user never changed them
DEFAULT_GOALS = {"calories": 2900, "protein": 130, "carbs": 400, "fat": 85, "fiber": 38, "sugar": 70, "sat_fat": 30}


def upgrade() -> None:
    op.create_table(
        "nutrition_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("grams", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("fdc_id", sa.Integer(), nullable=True),
        *[sa.Column(n, sa.Float(), nullable=False) for n in NUTRIENTS],
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_nutrition_entries_id"), "nutrition_entries", ["id"], unique=False)
    op.create_index(op.f("ix_nutrition_entries_day"), "nutrition_entries", ["day"], unique=False)
    op.create_index("ix_nutrition_entries_user_day", "nutrition_entries", ["user_id", "day"], unique=False)

    op.create_table(
        "nutrition_days",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("goals", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", name="uq_nutrition_days_user_day"),
    )
    op.create_index(op.f("ix_nutrition_days_id"), "nutrition_days", ["id"], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Supabase exposes public tables via its Data API unless RLS is on (see PROJECT_CONTEXT.md)
        op.execute("ALTER TABLE nutrition_entries ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE nutrition_days ENABLE ROW LEVEL SECURITY")

    # ---- Move existing logs out of the widget rows ----
    integrations = sa.table(
        "integrations",
        sa.column("id", sa.Integer), sa.column("user_id", sa.Integer),
        sa.column("app_name", sa.String), sa.column("config", sa.JSON),
    )
    entries = sa.table(
        "nutrition_entries",
        sa.column("user_id", sa.Integer), sa.column("day", sa.Date), sa.column("name", sa.String),
        sa.column("grams", sa.Float), sa.column("source", sa.String), sa.column("fdc_id", sa.Integer),
        *[sa.column(n, sa.Float) for n in NUTRIENTS], sa.column("created_at", sa.DateTime),
    )
    days = sa.table(
        "nutrition_days",
        sa.column("user_id", sa.Integer), sa.column("day", sa.Date),
        sa.column("goals", sa.JSON), sa.column("updated_at", sa.DateTime),
    )

    rows = bind.execute(
        sa.select(integrations.c.id, integrations.c.user_id, integrations.c.config)
        .where(integrations.c.app_name == "nutrition")
    ).fetchall()
    now = datetime.utcnow()
    for row_id, user_id, config in rows:
        config = dict(config or {})
        log = config.pop("log", None) or {}
        settings = config.get("settings") or {}
        goals = {n: settings.get(f"goal_{n}", DEFAULT_GOALS[n]) for n in NUTRIENTS}

        for day_str, day_entries in log.items():
            if not day_entries:
                continue
            day = date.fromisoformat(day_str)
            bind.execute(days.insert().values(user_id=user_id, day=day, goals=goals, updated_at=now))
            for e in day_entries:
                nutrients = e.get("nutrients") or {}
                added = e.get("added_at")
                bind.execute(entries.insert().values(
                    user_id=user_id, day=day, name=(e.get("name") or "Food")[:200],
                    grams=e.get("grams"), source=e.get("source") or "manual", fdc_id=e.get("fdc_id"),
                    **{n: float(nutrients.get(n, 0) or 0) for n in NUTRIENTS},
                    created_at=datetime.fromisoformat(added).replace(tzinfo=None) if added else now,
                ))

        bind.execute(integrations.update().where(integrations.c.id == row_id).values(config=config))


def downgrade() -> None:
    # History added after this migration can't fit back in the 14-day JSON log; tables are dropped.
    op.drop_index(op.f("ix_nutrition_days_id"), table_name="nutrition_days")
    op.drop_table("nutrition_days")
    op.drop_index("ix_nutrition_entries_user_day", table_name="nutrition_entries")
    op.drop_index(op.f("ix_nutrition_entries_day"), table_name="nutrition_entries")
    op.drop_index(op.f("ix_nutrition_entries_id"), table_name="nutrition_entries")
    op.drop_table("nutrition_entries")
