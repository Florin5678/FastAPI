# Reminders widget (id "notes" from when it also held notes; kept so layouts and saved
# data carry over). Everything is stored in the widget's integrations row:
#   config["reminders"] = [{id, text, due (UTC ISO or null), repeat (null | "daily" |
#                           "weekly" | "monthly"), done, created_at, done_at}]
# A repeating reminder is never "done": ticking it moves its due time to the next
# occurrence (monthly ones keep their day of the month, e.g. the 31st -> 30 Apr -> 31 May).
# Completed one-off reminders are dropped after DONE_KEEP_DAYS.
import calendar
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import DASHBOARD_TZ, local_zone
from app.models import Integration, User
from app.widgets.registry import WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "notes"
MAX_ITEMS = 500
DONE_KEEP_DAYS = 30
DONE_SHOWN_DAYS = 7
Repeat = Literal["daily", "weekly", "monthly"]
REPEAT_TEXT = {"daily": "every day", "weekly": "every week", "monthly": "every month"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _items(row: Integration) -> list[dict]:
    return [dict(i) for i in (row.config or {}).get("reminders", [])]


def _save(row: Integration, items: list[dict]) -> None:
    cutoff = (_now() - timedelta(days=DONE_KEEP_DAYS)).isoformat()
    items = [i for i in items if not i["done"] or (i.get("done_at") or "") >= cutoff]
    # JSON columns aren't mutation-tracked: assign a new dict
    row.config = {**(row.config or {}), "reminders": items}
    row.updated_at = datetime.utcnow()


def _utc(due: Optional[datetime]) -> Optional[str]:
    if due is None:
        return None
    if due.tzinfo is None:
        raise HTTPException(status_code=422, detail="Due time must include a timezone offset")
    return due.astimezone(timezone.utc).isoformat()


def _next_due(due: str, repeat: str, day_of_month: int, tz: Optional[str]) -> str:
    """The next occurrence after now, stepping in the user's local time (so 09:00 stays
    09:00 across daylight-saving changes)."""
    zone = local_zone(tz or DASHBOARD_TZ)
    moment = datetime.fromisoformat(due).astimezone(zone)
    now = _now()
    while True:
        if repeat == "daily":
            moment = (moment.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=zone)
        elif repeat == "weekly":
            moment = (moment.replace(tzinfo=None) + timedelta(weeks=1)).replace(tzinfo=zone)
        else:
            year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
            day = min(day_of_month, calendar.monthrange(year, month)[1])
            moment = moment.replace(year=year, month=month, day=day)
        if moment > now:
            return moment.astimezone(timezone.utc).isoformat()


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    reminders = _items(widget_row(db, user, WIDGET_ID))
    shown_cutoff = (_now() - timedelta(days=DONE_SHOWN_DAYS)).isoformat()
    open_ = sorted(
        (r for r in reminders if not r["done"]),
        key=lambda r: (r["due"] is None, r["due"] or "", r["created_at"]),
    )
    done = sorted(
        (r for r in reminders if r["done"] and (r.get("done_at") or "") >= shown_cutoff),
        key=lambda r: r.get("done_at") or "",
        reverse=True,
    )
    return {"reminders": open_, "done": done}


def _due_text(due: str, now: datetime) -> str:
    moment = datetime.fromisoformat(due)
    local = moment.astimezone(now.tzinfo)
    if moment < now:
        return f"OVERDUE since {local:%a %d %b %H:%M}"
    if local.date() == now.date():
        return f"due today {local:%H:%M}"
    return f"due {local:%a %d %b %H:%M}"


def brief(data: dict, limit: int | None = None) -> str:
    now = datetime.now(local_zone(DASHBOARD_TZ))
    count = limit or 15
    if not data["reminders"]:
        lines = ["No open reminders."]
    else:
        lines = [f"Open reminders ({len(data['reminders'])}, soonest due first):"]
        for r in data["reminders"][:count]:
            when = _due_text(r["due"], now) if r["due"] else "no due date"
            if r.get("repeat"):
                when += f", repeats {REPEAT_TEXT[r['repeat']]}"
            lines.append(f"- {r['text']} ({when})")
        if len(data["reminders"]) > count:
            lines.append(f"(+{len(data['reminders']) - count} more open reminders)")
    if data.get("done"):
        lines.append("Recently completed: " + "; ".join(r["text"] for r in data["done"][:5]))
    return "\n".join(lines)


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Reminders",
    description="Reminders with due dates, one-off or repeating every day, week or month; overdue and due-today ones are highlighted.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 5),
    refresh_seconds=300,
    enabled_by_default=True,
))


# ---- Routes used by the widget ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    due: Optional[datetime] = None  # with offset, e.g. 2026-09-28T09:00:00+02:00
    repeat: Optional[Repeat] = None  # needs a due time
    tz: Optional[str] = None  # the user's timezone (for the day of the month a monthly one keeps)


class ReminderPatch(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=300)
    due: Optional[datetime] = None  # send null to clear
    repeat: Optional[Repeat] = None  # send null to stop repeating
    done: Optional[bool] = None
    tz: Optional[str] = None  # the user's timezone (stepping a repeating reminder, day of the month)


def _find(items: list[dict], item_id: str) -> dict:
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Not found")


def _local_day(due: Optional[datetime], tz: Optional[str]) -> Optional[int]:
    """Day of the month of `due` in the user's timezone (what a monthly reminder keeps)."""
    return due.astimezone(local_zone(tz or DASHBOARD_TZ)).day if due and due.tzinfo else None


def _check_repeat(reminder: dict) -> None:
    if reminder.get("repeat") and not reminder["due"]:
        raise HTTPException(status_code=422, detail="A repeating reminder needs a date and time")


@router.post("/reminders")
def add_reminder(body: ReminderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row)
    if len(items) >= MAX_ITEMS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_ITEMS} reminders; delete some old ones first")
    reminder = {
        "id": uuid.uuid4().hex[:12], "text": body.text.strip(), "due": _utc(body.due), "repeat": body.repeat,
        # Monthly reminders keep this day of the month (in the user's time, as entered)
        "repeat_day": _local_day(body.due, body.tz),
        "done": False, "created_at": _now().isoformat(), "done_at": None,
    }
    _check_repeat(reminder)
    _save(row, [*items, reminder])
    db.commit()
    return reminder


@router.patch("/reminders/{item_id}")
def update_reminder(item_id: str, body: ReminderPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row)
    reminder = _find(items, item_id)
    if body.text is not None:
        reminder["text"] = body.text.strip()
    if "due" in body.model_fields_set:
        reminder["due"] = _utc(body.due)
        reminder["repeat_day"] = _local_day(body.due, body.tz)
    if "repeat" in body.model_fields_set:
        reminder["repeat"] = body.repeat
    _check_repeat(reminder)
    if body.done and reminder.get("repeat"):
        # Ticking a repeating reminder moves it to its next occurrence instead
        day = reminder.get("repeat_day") or _local_day(datetime.fromisoformat(reminder["due"]), body.tz)
        reminder["due"] = _next_due(reminder["due"], reminder["repeat"], day, body.tz)
    elif body.done is not None:
        reminder["done"] = body.done
        reminder["done_at"] = _now().isoformat() if body.done else None
    _save(row, items)
    db.commit()
    return reminder


@router.delete("/reminders/{item_id}")
def delete_reminder(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row)
    _find(items, item_id)
    _save(row, [i for i in items if i["id"] != item_id])
    db.commit()
    return {"deleted": item_id}
