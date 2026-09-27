import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.gmail_routes import router as gmail_router
from app.summary_routes import router as summary_router
from app.widget_routes import router as widget_router
from app.widgets.nutrition import router as nutrition_router
from app.widgets.notes import router as notes_router
from app.widgets.journal import router as journal_router
from app.auth.google_oauth import router as google_router

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def run_migrations() -> None:
    """Bring the database schema up to date (alembic upgrade head). Runs on every
    startup, so a deploy that adds a migration applies it by itself; if it fails,
    the app doesn't start and Render keeps serving the previous deploy."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("SKIP_MIGRATIONS") != "1":  # set in tests / local setups that manage the schema themselves
        run_migrations()
        logger.info("Database migrations are up to date")
    yield


app = FastAPI(lifespan=lifespan)

# Signed session cookie for the browser frontend. The signing secret is derived from
# ENCRYPTION_KEY so there's no extra env var to manage (SESSION_SECRET overrides it).
session_secret = os.getenv("SESSION_SECRET") or hmac.new(
    os.environ["ENCRYPTION_KEY"].encode(), b"session-cookie", hashlib.sha256
).hexdigest()
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    same_site="lax",
    https_only=os.getenv("SESSION_HTTPS_ONLY", "true") == "true",
    max_age=30 * 24 * 3600,
)


@app.get("/health")
def health():
    return {"status": "ok"}

# Include Google OAuth routes (public - Google redirects the browser here)
app.include_router(google_router, prefix="/auth/google")

# Include Gmail routes (signed-in session or X-API-Key)
app.include_router(gmail_router, prefix="/gmail", tags=["gmail"])

# Include email list, summary + digest routes (signed-in session or X-API-Key)
app.include_router(summary_router, tags=["summaries"])

# Dashboard widgets: registry, per-user layout/settings, data (signed-in session or X-API-Key)
app.include_router(widget_router, tags=["widgets"])
app.include_router(nutrition_router)  # food log + USDA food search for the Nutrition widget
app.include_router(notes_router)  # notes + reminders CRUD for the Notes widget
app.include_router(journal_router)  # journal entries + prompts for the Journal widget

# The React frontend (built into frontend/dist) is served from everything else
FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
