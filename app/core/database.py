import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Render gives you DATABASE_URL like postgresql://... when using an ORM
# some providers give postgres:// - SQLAlchemy needs postgresql://
DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

# Supabase's pooler drops idle connections: test each one before use (pre_ping) and
# replace connections older than 5 minutes, instead of failing a request on a dead one
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency - yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
