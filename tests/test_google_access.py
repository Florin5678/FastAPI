from datetime import datetime, timedelta
from unittest.mock import patch

from app.auth import google_tokens
from app.core.crypto import encrypt
from app.models import Integration, Token
from app.widgets import assistant


class _Reply:
    def __init__(self, body, status=400):
        self._body, self.status_code = body, status

    def json(self):
        return self._body


def _expired_token(db, user):
    row = Token(user_id=user.id, provider="google", access_token=encrypt("old"), refresh_token=encrypt("dead"),
                expires_at=datetime.utcnow() - timedelta(hours=1))
    db.add(row)
    db.commit()
    return row


def _revoked():
    return patch.object(google_tokens.requests, "post", return_value=_Reply(
        {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))


def test_an_expired_google_sign_in_is_recorded_and_shown(client, db, user):
    _expired_token(db, user)
    with _revoked():
        assert client.get("/api/me").json()["google"]["ok"] is True  # not tried yet
        try:
            google_tokens.get_valid_access_token(db, user.id)
        except ValueError:
            pass
    google = client.get("/api/me").json()["google"]
    assert google["ok"] is False and "expired or was revoked" in google["problem"] and google["since"]
    # Renewing works again (e.g. after signing in): the problem is cleared
    with patch.object(google_tokens.requests, "post", return_value=_Reply({"access_token": "new", "expires_in": 3600}, 200)):
        assert google_tokens.get_valid_access_token(db, user.id) == "new"
    assert client.get("/api/me").json()["google"]["ok"] is True


def test_scheduled_sync_stays_ok_and_still_writes_the_morning_brief(client, db, user):
    _expired_token(db, user)
    with _revoked(), patch("app.widgets.assistant_chat.maybe_morning_brief") as brief:
        r = client.post("/gmail/sync/gmail", params={"email": user.email}, headers={"X-API-Key": "test-sync-key"})
    assert r.status_code == 200 and "expired or was revoked" in r.json()["google_problem"]
    brief.assert_called_once_with(user.id)
    with _revoked():
        assert client.post("/gmail/sync/gmail").status_code == 401  # "Sync now" shows the reason


def test_briefing_asks_claude_to_use_its_own_connectors_when_google_is_unreachable(db, user):
    db.add(Integration(user_id=user.id, app_name="email_summary", status="active", config={}))
    db.add(Integration(user_id=user.id, app_name="calendar", status="active", config={}))
    db.commit()
    _expired_token(db, user)
    with _revoked():
        sections = {s["widget"]: s["text"] for s in assistant.briefing_sections(db, user, assistant.default_ctx(), assistant.default_settings())}
    assert "can't reach Gmail right now (Your Google sign-in expired or was revoked" in sections["email_summary"]
    assert "use a Gmail connector" in sections["email_summary"]
    assert "use a Google Calendar connector" in sections["calendar"]
    assert "⚠" not in sections["projects"]


def test_the_projects_section_is_added_to_saved_settings_once(db, user):
    row = db.query(Integration).filter_by(user_id=user.id, app_name="assistant").one()
    saved = assistant.default_settings().model_dump()
    saved["extras"] = [e for e in saved["extras"] if e["name"] != "Projects"]
    saved["added_sections"] = []
    row.config = {"assistant": saved}
    db.commit()
    names = [e.name for e in assistant.load_settings(db, user).extras]
    assert names.index("Projects") == names.index("Urgent tasks") + 1
    # Removed by the user: it doesn't come back
    settings = assistant.load_settings(db, user)
    settings.extras = [e for e in settings.extras if e.name != "Projects"]
    row.config = {"assistant": settings.model_dump()}
    db.commit()
    assert "Projects" not in [e.name for e in assistant.load_settings(db, user).extras]
