# Google Calendar widget: upcoming events from the calendars selected in Google Calendar.
# Read-only (calendar.readonly scope). Needs the Google Calendar API enabled in Google
# Cloud Console and one sign-in after the scope was added; until then the widget shows
# what to do instead of an error.
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.timeutil import local_zone
from app.auth.google_tokens import get_valid_access_token
from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

API = "https://www.googleapis.com/calendar/v3"
MAX_EVENTS_PER_CALENDAR = 50


class _NeedsSetup(Exception):
    def __init__(self, reason: str):
        self.reason = reason  # "permission" (sign in again) | "api_disabled" (enable in Cloud Console)


def _get(path: str, token: str, params: Optional[dict] = None) -> dict:
    response = requests.get(f"{API}{path}", headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
    if response.status_code == 403:
        body = response.text
        if "accessNotConfigured" in body or "SERVICE_DISABLED" in body:
            raise _NeedsSetup("api_disabled")
        if "insufficient" in body.lower() or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body:
            raise _NeedsSetup("permission")
    if response.status_code == 401:
        raise _NeedsSetup("permission")
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Google Calendar returned an error ({response.status_code}). Try again later.")
    return response.json()


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
    except _NeedsSetup as setup:
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
        "events": events,
    }


def brief(data: dict, limit: int | None = None) -> str:
    if data["needs_setup"]:
        return "Calendar not connected yet."
    if not data["events"]:
        return f"No events in the next {data['days']} day(s)."
    lines = [f"Upcoming events (next {data['days']} days):"]
    for e in data["events"][:limit or 12]:
        when = f"{e['start']} (all day)" if e["all_day"] else e["start"]
        lines.append(f"- {when}: {e['title']}" + (f" at {e['location']}" if e["location"] else ""))
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
