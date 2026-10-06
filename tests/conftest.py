"""Shared test setup: a throwaway SQLite database per test, a signed-in test user, the
FastAPI app with auth overridden, and a stand-in for the connector's per-call session (so
Claude's tools can be called directly). No network: Google, Claude and feeds are faked in
the tests that need them."""
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

_DB = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_DB}",
    "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "SESSION_HTTPS_ONLY": "false",
    "SKIP_MIGRATIONS": "1",
    "SYNC_API_KEY": "test-sync-key",
    "PUBLIC_URL": "http://localhost:8000",
    "DASHBOARD_TZ": "Europe/Copenhagen",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.connector import changes, tools  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Integration, User  # noqa: E402

LOCAL_WIDGETS = ("nutrition", "notes", "gym", "weight", "budget", "assistant")  # no network needed


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def user(db):
    u = User(email="test@example.com", name="Test")
    db.add(u)
    db.commit()
    for widget in LOCAL_WIDGETS:
        db.add(Integration(user_id=u.id, app_name=widget, status="active", config={}))
    db.commit()
    return u


@pytest.fixture()
def client(user):
    app.dependency_overrides[get_current_user] = lambda: user
    # No `with`: the app's startup (migrations, the connector's MCP server) isn't needed here
    yield TestClient(app)
    app.dependency_overrides.clear()


class ChangeLog(list):
    """What the connector tools recorded: (tool, summary, undo)."""

    def undo_last(self, db, user):
        undo = self[-1][2]
        changes.UNDO_ACTIONS[undo["action"]](db, user, undo["args"])


@pytest.fixture()
def claude(db, user, monkeypatch):
    """Call the connector tools as the test user; returns the change log they wrote."""
    log = ChangeLog()

    class FakeCall:
        def __enter__(self):
            self.db, self.user = db, user
            return self

        def __exit__(self, *exc):
            return False

        def record(self, tool, summary, undo):
            log.append((tool, summary, undo))

    monkeypatch.setattr(tools, "_Call", FakeCall)
    return log
