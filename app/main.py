import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.account import router as account_router
from app.auth.google_oauth import router as google_router
from app.connector.oauth import router as connector_consent_router
from app.connector.server import MCPDispatch, connector_lifespan
from app.connector.server import router as connector_router
from app.mail.gmail_routes import router as gmail_router
from app.mail.routes import router as mail_router
from app.widgets.assistant import router as assistant_router
from app.widgets.assistant_chat import router as assistant_chat_router
from app.widgets.budget import router as budget_router
from app.widgets.gym import router as gym_router
from app.widgets.journal import router as journal_router
from app.widgets.notes import router as notes_router
from app.widgets.nutrition import router as nutrition_router
from app.widgets.routes import router as widget_router

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
    async with connector_lifespan():  # the Claude connector (/mcp)
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
# Claude connector: /mcp and its OAuth endpoints are served by the MCP SDK (see app/connector)
app.add_middleware(MCPDispatch)


@app.get("/health")
def health():
    return {"status": "ok"}

# ---- Routes ----
# Sign-in (public: Google redirects the browser here) and account info
app.include_router(google_router, prefix="/auth/google")
app.include_router(account_router, tags=["account"])
app.include_router(connector_consent_router)  # "Allow Claude?" page of the Claude connector sign-in

# Everything below needs a signed-in session or X-API-Key (see app/core/security.py)
app.include_router(gmail_router, prefix="/gmail", tags=["gmail"])  # Gmail sync (Sync now + cron-job.org)
app.include_router(mail_router, tags=["mail"])  # stored emails, summaries, digest
app.include_router(widget_router, tags=["widgets"])  # generic widget registry, layout, settings, data
app.include_router(nutrition_router)  # Nutrition widget: food log, history, food search (USDA + Open Food Facts)
app.include_router(notes_router)  # Reminders widget
app.include_router(journal_router)  # Journal widget: entries, prompts, locked history
app.include_router(gym_router)  # Gym widget: log / delete workouts
app.include_router(assistant_router)  # Assistant widget: prompt & briefing settings
app.include_router(assistant_chat_router)  # Assistant widget: AI chat (Claude API, monthly budget)
app.include_router(budget_router)  # Budget widget: entries, monthly report, CSV import/export
app.include_router(connector_router)  # Claude connector: status, undo Claude's changes, disconnect

# The React frontend (built into frontend/dist) is served from everything else
FRONTEND_DIST = ROOT / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
