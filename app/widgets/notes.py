# Notes & reminders widget. Everything is stored in the widget's integrations row:
#   config["reminders"] = [{id, text, due (UTC ISO or null), done, created_at, done_at}]
#   config["notes"]     = [{id, text, pinned, created_at, updated_at}]
# Reminders show on the dashboard (due today / overdue highlighted); phone notifications
# come later with Web Push. Completed reminders are dropped after DONE_KEEP_DAYS.
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Integration, User
from app.core.security import get_current_user
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "notes"
MAX_ITEMS = 500
DONE_KEEP_DAYS = 30
DONE_SHOWN_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _items(row: Integration, kind: str) -> list[dict]:
    return [dict(i) for i in (row.config or {}).get(kind, [])]


def _save(row: Integration, kind: str, items: list[dict]) -> None:
    if kind == "reminders":
        cutoff = (_now() - timedelta(days=DONE_KEEP_DAYS)).isoformat()
        items = [i for i in items if not i["done"] or (i.get("done_at") or "") >= cutoff]
    # JSON columns aren't mutation-tracked: assign a new dict
    row.config = {**(row.config or {}), kind: items}
    row.updated_at = datetime.utcnow()


def _utc(due: Optional[datetime]) -> Optional[str]:
    if due is None:
        return None
    if due.tzinfo is None:
        raise HTTPException(status_code=422, detail="Due time must include a timezone offset")
    return due.astimezone(timezone.utc).isoformat()


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    row = widget_row(db, user, WIDGET_ID)
    reminders = _items(row, "reminders")
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
    # Pinned first, then most recently edited first
    notes = sorted(_items(row, "notes"), key=lambda n: n["updated_at"], reverse=True)
    notes.sort(key=lambda n: not n.get("pinned"))  # stable: keeps recency order within each group
    return {"reminders": open_, "done": done, "notes": notes}


def _due_text(due: str, now: datetime) -> str:
    moment = datetime.fromisoformat(due)
    local = moment.astimezone(now.tzinfo)
    if moment < now:
        return f"OVERDUE since {local:%a %d %b %H:%M}"
    if local.date() == now.date():
        return f"due today {local:%H:%M}"
    return f"due {local:%a %d %b %H:%M}"


def brief(data: dict, limit: int | None = None) -> str:
    now = datetime.now(timezone.utc).astimezone()
    count = limit or 15
    if not data["reminders"]:
        lines = ["No open reminders."]
    else:
        lines = [f"Open reminders ({len(data['reminders'])}, soonest due first):"]
        for r in data["reminders"][:count]:
            lines.append(f"- {r['text']}" + (f" ({_due_text(r['due'], now)})" if r["due"] else " (no due date)"))
        if len(data["reminders"]) > count:
            lines.append(f"(+{len(data['reminders']) - count} more open reminders)")
    if data.get("done"):
        lines.append("Recently completed: " + "; ".join(r["text"] for r in data["done"][:5]))
    if data["notes"]:
        lines.append(f"Notes ({len(data['notes'])}, pinned first):")
        for n in data["notes"][:count]:
            text = " ".join((n.get("text") or "").split())
            lines.append(f"- {'[pinned] ' if n.get('pinned') else ''}{text[:300]}")
    else:
        lines.append("No notes.")
    return "\n".join(lines)


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Notes & reminders",
    description="Quick notes and reminders with due dates; overdue and due-today reminders are highlighted.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 5),
    refresh_seconds=300,
    enabled_by_default=True,
    config_fields=(
        ConfigField("start_tab", "Open on", "select", default="Reminders", options=["Reminders", "Notes"]),
    ),
))


# ---- Routes used by the widget ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class ReminderIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    due: Optional[datetime] = None  # with offset, e.g. 2026-09-28T09:00:00+02:00


class ReminderPatch(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=300)
    due: Optional[datetime] = None  # send null to clear
    done: Optional[bool] = None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NotePatch(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=2000)
    pinned: Optional[bool] = None


def _find(items: list[dict], item_id: str) -> dict:
    for item in items:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Not found")


def _check_room(items: list[dict]) -> None:
    if len(items) >= MAX_ITEMS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_ITEMS} of these; delete some old ones first")


@router.post("/reminders")
def add_reminder(body: ReminderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "reminders")
    _check_room(items)
    reminder = {
        "id": uuid.uuid4().hex[:12], "text": body.text.strip(), "due": _utc(body.due),
        "done": False, "created_at": _now().isoformat(), "done_at": None,
    }
    _save(row, "reminders", [*items, reminder])
    db.commit()
    return reminder


@router.patch("/reminders/{item_id}")
def update_reminder(item_id: str, body: ReminderPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "reminders")
    reminder = _find(items, item_id)
    if body.text is not None:
        reminder["text"] = body.text.strip()
    if "due" in body.model_fields_set:
        reminder["due"] = _utc(body.due)
    if body.done is not None:
        reminder["done"] = body.done
        reminder["done_at"] = _now().isoformat() if body.done else None
    _save(row, "reminders", items)
    db.commit()
    return reminder


@router.delete("/reminders/{item_id}")
def delete_reminder(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "reminders")
    _find(items, item_id)
    _save(row, "reminders", [i for i in items if i["id"] != item_id])
    db.commit()
    return {"deleted": item_id}


@router.post("/notes")
def add_note(body: NoteIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "notes")
    _check_room(items)
    now = _now().isoformat()
    note = {"id": uuid.uuid4().hex[:12], "text": body.text.strip(), "pinned": False, "created_at": now, "updated_at": now}
    _save(row, "notes", [*items, note])
    db.commit()
    return note


@router.patch("/notes/{item_id}")
def update_note(item_id: str, body: NotePatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "notes")
    note = _find(items, item_id)
    if body.text is not None:
        note["text"] = body.text.strip()
        note["updated_at"] = _now().isoformat()
    if body.pinned is not None:
        note["pinned"] = body.pinned
    _save(row, "notes", items)
    db.commit()
    return note


@router.delete("/notes/{item_id}")
def delete_note(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, "notes")
    _find(items, item_id)
    _save(row, "notes", [i for i in items if i["id"] != item_id])
    db.commit()
    return {"deleted": item_id}
