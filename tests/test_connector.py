import base64
import dataclasses
from datetime import datetime
from email import message_from_bytes
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.connector import tools
from app.mail import gmail_actions
from app.models import Email
from app.widgets import google_calendar
from app.widgets.registry import REGISTRY

CPH = ZoneInfo("Europe/Copenhagen")


def test_claude_has_the_tools_and_the_overview_names_them():
    names = {t.name for t in tools.mcp._tool_manager.list_tools()}
    expected = {"get_briefing", "plan_meals", "log_food", "update_food", "get_nutrition_history", "add_pantry_items",
                "add_shopping_items", "move_to_pantry", "set_pantry_priority", "add_calendar_event", "update_calendar_event",
                "delete_calendar_event", "log_weight", "add_saved_food", "update_saved_food", "draft_email", "send_email",
                "archive_email", "mark_email_read", "trash_email", "add_budget_entry", "update_workout", "update_reminder"}
    assert expected <= names
    for tool in ("get_weight", "add_saved_food", "draft_email", "send_email", "plan_meals", "add_calendar_event"):
        assert tool in tools.INSTRUCTIONS, tool


def test_plan_meals_sees_the_free_time_between_events(claude):
    events = {"needs_setup": None, "days": 1, "events": [
        dict(all_day=False, start="2026-10-06T13:00:00+02:00", end="2026-10-06T16:30:00+02:00", title="Class", location=None),
        dict(all_day=True, start="2026-10-06", end="2026-10-07", title="Birthday", location=None)]}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 6, 12, 10, tzinfo=CPH)

    fake_calendar = dataclasses.replace(REGISTRY["calendar"], fetch=lambda *a, **k: events)
    with patch.dict(REGISTRY, {"calendar": fake_calendar}), patch.object(tools, "datetime", Clock), \
            patch.object(tools, "_widget", lambda call, widget_id, **o: events if widget_id == "calendar" else None):
        plan = tools.plan_meals()
    assert plan["upcoming_meals"][0] == "lunch"
    assert plan["schedule"]["free_time"][0] == {"from": "12:10", "to": "13:00", "minutes": 50}
    assert plan["schedule"]["all_day"] == ["Birthday"]
    assert "free_time" in plan["how_to_plan"] and "priority=true" in plan["how_to_plan"]


@pytest.fixture()
def fake_google(monkeypatch):
    """A tiny in-memory Google Calendar + Gmail; returns what was sent."""
    store = {"e1": {"id": "e1", "summary": "Dentist", "start": {"dateTime": "2026-10-08T09:00:00+02:00"},
                    "end": {"dateTime": "2026-10-08T09:30:00+02:00"}}}
    sent = []

    def request(method, url, token, params=None, body=None, **kwargs):
        sent.append((method, url, body))
        if "gmail" in url:
            if url.endswith("/messages/m1") and method == "GET":
                return {"id": "m1", "threadId": "t1", "payload": {"headers": [
                    {"name": "From", "value": "Prof <prof@au.dk>"}, {"name": "Subject", "value": "Assignment 2"},
                    {"name": "Message-ID", "value": "<abc@au.dk>"}]}}
            return {"id": "d1"} if url.endswith("/drafts") else {"id": "sent1"}
        event_id = url.rsplit("/events", 1)[1].strip("/") or None
        if method == "POST":
            new = {"id": f"e{len(store) + 1}", **body}
            store[new["id"]] = new
            return new
        if method == "GET":
            return store[event_id]
        if method == "PATCH":
            store[event_id] = {**store[event_id], **body}
            return store[event_id]
        store.pop(event_id)
        return None

    for module in (google_calendar, gmail_actions):
        monkeypatch.setattr(module, "google_request", request)
        monkeypatch.setattr(module, "get_valid_access_token", lambda db, user_id: "token")
    return store, sent


def test_calendar_add_move_delete_and_undo(db, user, claude, fake_google):
    store, sent = fake_google
    event = tools.add_calendar_event("Cook", "2026-10-06T19:15", "2026-10-06T20:00")
    assert event["title"] == "Cook" and sent[-1][2]["start"] == {"dateTime": "2026-10-06T19:15", "timeZone": "Europe/Copenhagen"}
    tools.add_calendar_event("Trip", "2026-10-11", all_day=True)
    assert sent[-1][2]["end"] == {"date": "2026-10-12"}  # Google's all-day end is exclusive
    tools.update_calendar_event("e1", start="2026-10-08T10:00", end="2026-10-08T10:30")
    claude.undo_last(db, user)
    assert store["e1"]["start"] == {"dateTime": "2026-10-08T09:00:00+02:00"}
    tools.delete_calendar_event("e1")
    claude.undo_last(db, user)
    assert "Dentist" in [e["summary"] for e in store.values()]


def test_email_reply_draft_and_send(db, user, claude, fake_google):
    _, sent = fake_google
    db.add(Email(user_id=user.id, gmail_id="m1", subject="Assignment 2", sender="Prof <prof@au.dk>"))
    db.commit()
    email_id = db.query(Email).first().id
    draft = tools.draft_email("Thanks, I'll send it Friday.", email_id=email_id)
    assert draft["to"] == "Prof <prof@au.dk>" and draft["subject"] == "Re: Assignment 2"
    method, url, body = sent[-1]
    assert url.endswith("/drafts") and body["message"]["threadId"] == "t1"
    mime = message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]))
    assert mime["In-Reply-To"] == "<abc@au.dk>" and "Friday" in mime.get_payload()
    assert claude[-1][2]["action"] == "delete_email_draft"
    tools.send_email("Done!", to="friend@example.com", subject="Hi")
    assert sent[-1][1].endswith("/messages/send") and claude[-1][2] is None  # sending can't be undone
    tools.archive_email(email_id)
    assert sent[-1][2] == {"addLabelIds": [], "removeLabelIds": ["INBOX"]}
    claude.undo_last(db, user)
    assert sent[-1][2] == {"addLabelIds": ["INBOX"], "removeLabelIds": []}


def test_new_email_needs_a_recipient_and_subject(claude, fake_google):
    with pytest.raises(Exception, match="needs `to` and `subject`"):
        tools.draft_email("Hello")
