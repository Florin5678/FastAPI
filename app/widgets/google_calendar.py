# Google Calendar widget: upcoming events from the calendars selected in Google Calendar.
# The tile only reads; create_event / update_event / delete_event below are for Claude
# (connector tools) and need the calendar.events scope (one sign-in after it was added).
# Needs the Google Calendar API enabled in Google Cloud Console; until then the widget
# shows what to do instead of an error.
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy.orm import Session

from fastapi import HTTPException

from app.core.google_api import NeedsSetup, google_get, google_request
from app.core.timeutil import local_zone
from app.auth.google_tokens import get_valid_access_token
from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

API = "https://www.googleapis.com/calendar/v3"
MAX_EVENTS_PER_CALENDAR = 50


def _get(path: str, token: str, params: Optional[dict] = None) -> dict:
    return google_get(f"{API}{path}", token, params, service="Google Calendar")


def _event(e: dict, calendar: dict) -> Optional[dict]:
    if e.get("status") == "cancelled":
        return None
    start, end = e.get("start") or {}, e.get("end") or {}
    all_day = "date" in start
    return {
        "id": e.get("id"),
        "title": e.get("summary") or "(no title)",
        "all_day": all_day,
        # all-day: "YYYY-MM-DD" (end is exclusive); timed: ISO with offset
        "start": start.get("date") if all_day else start.get("dateTime"),
        "end": end.get("date") if all_day else end.get("dateTime"),
        "location": e.get("location"),
        "link": e.get("htmlLink"),
        "calendar": calendar.get("summaryOverride") or calendar.get("summary"),
        "calendar_id": calendar.get("id"),
        "color": calendar.get("backgroundColor"),
    }


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    zone = local_zone(ctx.tz)
    now = datetime.now(zone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=settings["days"])

    try:
        token = get_valid_access_token(db, user.id)
        calendars = [
            c for c in _get("/users/me/calendarList", token, {"minAccessRole": "reader"}).get("items", [])
            if c.get("selected", True) and not c.get("hidden")
        ]

        def events_for(calendar: dict) -> list[dict]:
            data = _get(f"/calendars/{quote(calendar['id'], safe='')}/events", token, {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",  # expand recurring events
                "orderBy": "startTime",
                "maxResults": MAX_EVENTS_PER_CALENDAR,
                "timeZone": str(zone),
            })
            return [ev for ev in (_event(e, calendar) for e in data.get("items", [])) if ev]

        with ThreadPoolExecutor(max_workers=max(1, min(8, len(calendars)))) as pool:
            events = [ev for chunk in pool.map(events_for, calendars) for ev in chunk]
    except NeedsSetup as setup:
        return {"needs_setup": setup.reason, "events": [], "days": settings["days"]}
    except ValueError:
        # No usable Google token (e.g. revoked): same fix as a missing permission
        return {"needs_setup": "permission", "events": [], "days": settings["days"]}

    def sort_key(ev: dict) -> tuple:
        if ev["all_day"]:
            return (ev["start"], 0, "")  # all-day events first within their day
        local = datetime.fromisoformat(ev["start"]).astimezone(zone)
        return (local.date().isoformat(), 1, local.isoformat())

    events.sort(key=sort_key)
    return {
        "needs_setup": None,
        "days": settings["days"],
        "today": start.date().isoformat(),
        "calendars": len(calendars),
        "calendar_list": [{"id": c["id"], "name": c.get("summaryOverride") or c.get("summary"),
                           "primary": bool(c.get("primary")), "can_edit": c.get("accessRole") in ("owner", "writer")}
                          for c in calendars],
        "events": events,
    }


def _duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} h" if hours else f"{mins} min"


def _when(e: dict) -> str:
    """"Mon 28 Sep 09:00–10:30 (1 h 30 min)" in the event's local time (the API returns
    times in the user's zone), so Claude can work out free time between events."""
    if e["all_day"]:
        first = datetime.fromisoformat(e["start"])
        days = (datetime.fromisoformat(e["end"]) - first).days if e["end"] else 1
        if days <= 1:
            return f"{first:%a %d %b}, all day"
        return f"{first:%a %d %b} – {first + timedelta(days=days - 1):%a %d %b}, all day ({days} days)"
    start = datetime.fromisoformat(e["start"])
    if not e["end"]:
        return f"{start:%a %d %b %H:%M}"
    end = datetime.fromisoformat(e["end"]).astimezone(start.tzinfo)
    minutes = int((end - start).total_seconds() // 60)
    end_text = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%a %d %b %H:%M}"
    return f"{start:%a %d %b %H:%M}–{end_text} ({_duration(minutes)})"


# ---- Changing events (Claude, through the connector) ----

def _event_url(calendar_id: str, event_id: Optional[str] = None) -> str:
    return f"{API}/calendars/{quote(calendar_id, safe='')}/events" + (f"/{quote(event_id, safe='')}" if event_id else "")


def _call(db: Session, user: User, method: str, url: str, body: Optional[dict] = None):
    try:
        token = get_valid_access_token(db, user.id)
        return google_request(method, url, token, body=body, service="Google Calendar",
                              not_found="That calendar event wasn't found (it may have been deleted)")
    except (NeedsSetup, ValueError) as e:
        raise HTTPException(status_code=403, detail=(
            "The dashboard isn't allowed to change your Google Calendar yet: sign out of the dashboard and sign in "
            "again, and allow it to see and edit your calendar events.")) from e


def event_body(title: Optional[str], start: Optional[str], end: Optional[str], all_day: bool, tz: str,
               location: Optional[str] = None, description: Optional[str] = None) -> dict:
    """Google's event fields from simple values. Timed: start/end like 2026-10-07T18:00 (local
    time in `tz`) or with an offset; all-day: dates like 2026-10-07 (end inclusive)."""
    body: dict = {}
    if title is not None:
        body["summary"] = title
    if location is not None:
        body["location"] = location
    if description is not None:
        body["description"] = description
    if start is not None:
        if all_day:
            first = datetime.fromisoformat(start[:10]).date()
            last = datetime.fromisoformat((end or start)[:10]).date()
            body["start"], body["end"] = {"date": first.isoformat()}, {"date": (last + timedelta(days=1)).isoformat()}
        else:
            begin = datetime.fromisoformat(start)
            finish = datetime.fromisoformat(end) if end else begin + timedelta(hours=1)
            body["start"] = {"dateTime": begin.isoformat(timespec="minutes"), "timeZone": tz}
            body["end"] = {"dateTime": finish.isoformat(timespec="minutes"), "timeZone": tz}
    return body


def get_event(db: Session, user: User, calendar_id: str, event_id: str) -> dict:
    return _call(db, user, "GET", _event_url(calendar_id, event_id))


def create_event(db: Session, user: User, calendar_id: str, body: dict) -> dict:
    return _call(db, user, "POST", _event_url(calendar_id), body)


def update_event(db: Session, user: User, calendar_id: str, event_id: str, body: dict) -> dict:
    return _call(db, user, "PATCH", _event_url(calendar_id, event_id), body)


def delete_event(db: Session, user: User, calendar_id: str, event_id: str) -> None:
    _call(db, user, "DELETE", _event_url(calendar_id, event_id))


def brief(data: dict, limit: int | None = None) -> str:
    """The events grouped by day (multi-day events once, under their first day)."""
    if data["needs_setup"]:
        return "Calendar not connected yet."
    if not data["events"]:
        return f"No events in the next {data['days']} day(s)."
    by_day: dict = {}
    for e in data["events"]:
        by_day.setdefault(datetime.fromisoformat(e["start"]).date(), []).append(e)
    lines = [f"Events for the next {data['days']} days (local time, with duration), grouped by day:"]
    shown, budget = 0, limit or 25
    for day in sorted(by_day):
        if shown >= budget:
            lines.append(f"(events from {day:%a %d %b} on are not listed; don't assume that time is free)")
            break
        lines.append(f"{day:%a %d %b}:")
        for e in by_day[day]:
            when = _when(e)
            # The day is already the heading: keep "09:00–10:30 (1 h 30 min)" / "all day (4 days)" etc.
            when = when.split(" ", 3)[-1]
            if when.startswith("– "):
                when = "until " + when[2:]
            lines.append(f"- {when}: {e['title']}" + (f" at {e['location']}" if e["location"] else ""))
            shown += 1
    return "\n".join(lines)


register(WidgetDefinition(
    id="calendar",
    name="Calendar",
    description="Your upcoming Google Calendar events (read-only), from all calendars you have selected.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 5),
    refresh_seconds=600,
    enabled_by_default=True,
    config_fields=(
        ConfigField("days", "Days to show", "number", default=7, min=1, max=31),
    ),
))
