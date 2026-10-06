"""The Alembic migrations run cleanly from an empty database to the latest version (the app
runs them at startup on Render, so a broken one would stop the deploy)."""
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core import database

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_to_head_and_back_one_step(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setattr(database, "DATABASE_URL", url)  # alembic/env.py reads it from there
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    tables = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert {"users", "nutrition_entries", "workouts", "budget_entries"} <= tables and "vocab_cards" not in tables
    columns = {c["name"] for c in sa.inspect(sa.create_engine(url)).get_columns("nutrition_entries")}
    assert "salt" in columns
    command.downgrade(config, "-1")
    command.upgrade(config, "head")
