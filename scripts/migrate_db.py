"""
One-off: copy all data from the old Postgres database to a new one.

Usage (PowerShell, from the repo root, with the venv active):
    $env:OLD_DATABASE_URL = "<Render External Database URL>"
    $env:NEW_DATABASE_URL = "<Supabase Session pooler connection string>"
    python scripts/migrate_db.py

It creates the schema on the new database with Alembic, copies every row
(ids preserved), fixes the id sequences, and verifies row counts. It refuses
to run if the new database already has data, so it's safe to re-run after a failure
only once the new tables are empty. The old database is only read, never changed.
"""
import os
import subprocess
import sys

from sqlalchemy import MetaData, create_engine, func, select, text

# Parents before children, so foreign keys are satisfied
TABLES = ["users", "tokens", "integrations", "emails"]


def normalize(url: str) -> str:
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url.replace("postgresql://", "postgresql+psycopg2://", 1)


def main() -> None:
    old_url = os.environ.get("OLD_DATABASE_URL")
    new_url = os.environ.get("NEW_DATABASE_URL")
    if not old_url or not new_url:
        sys.exit("Set OLD_DATABASE_URL and NEW_DATABASE_URL first (see the top of this file).")
    if old_url == new_url:
        sys.exit("OLD_DATABASE_URL and NEW_DATABASE_URL are the same - nothing to do.")

    old = create_engine(normalize(old_url))
    new = create_engine(normalize(new_url))

    print("1/4 Creating tables on the new database (alembic upgrade head)...")
    env = {**os.environ, "DATABASE_URL": new_url}
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=repo_root, env=env, check=True)

    old_meta = MetaData()
    old_meta.reflect(bind=old, only=TABLES)
    new_meta = MetaData()
    new_meta.reflect(bind=new, only=TABLES)

    with new.connect() as conn:
        existing = {t: conn.execute(select(func.count()).select_from(new_meta.tables[t])).scalar() for t in TABLES}
    if any(existing.values()):
        sys.exit(f"The new database already has data {existing} - refusing to copy over it.")

    print("2/4 Copying rows...")
    with old.connect() as src, new.begin() as dst:
        for name in TABLES:
            rows = [dict(r._mapping) for r in src.execute(select(old_meta.tables[name]))]
            if rows:
                dst.execute(new_meta.tables[name].insert(), rows)
            print(f"    {name}: {len(rows)} rows")

    print("3/4 Resetting id sequences + locking down the Data API...")
    with new.begin() as dst:
        for name in TABLES:
            dst.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {name}), 0) + 1, false)"
            ))

    # Supabase exposes tables in the public schema through its REST "Data API" unless
    # Row Level Security is on. With RLS enabled and no policies, that API sees nothing,
    # while the app (connecting as the table owner) is unaffected. Harmless elsewhere.
    print("    enabling Row Level Security...")
    with new.begin() as dst:
        for name in TABLES + ["alembic_version"]:
            dst.execute(text(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY"))

    print("4/4 Verifying row counts...")
    ok = True
    with old.connect() as src, new.connect() as dst:
        for name in TABLES:
            a = src.execute(select(func.count()).select_from(old_meta.tables[name])).scalar()
            b = dst.execute(select(func.count()).select_from(new_meta.tables[name])).scalar()
            print(f"    {name}: old={a} new={b} {'OK' if a == b else 'MISMATCH'}")
            ok = ok and a == b

    if not ok:
        sys.exit("Row counts don't match - don't switch DATABASE_URL yet.")
    print("\nDone. Now set DATABASE_URL on Render to the new connection string.")


if __name__ == "__main__":
    main()
