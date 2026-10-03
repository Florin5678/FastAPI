# Weight widget: body weight logged now and then (one value per day), its trend and an
# optional goal weight. Stored in the widget's row: config["entries"] = [{day, kg}], newest
# first. Part of the briefing, and plan_meals uses the trend (e.g. more calories when a
# weight-gain goal stalls).
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import Integration, User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "weight"
CHART_DAYS = 90
MAX_ENTRIES = 2000


def _entries(row: Integration) -> list[dict]:
    return [dict(e) for e in (row.config or {}).get("entries", [])]


def _store(row: Integration, entries: list[dict]) -> None:
    entries.sort(key=lambda e: e["day"], reverse=True)
    row.config = {**(row.config or {}), "entries": entries[:MAX_ENTRIES]}  # JSON columns aren't mutation-tracked


def summary(entries: list[dict], today: date, goal: float) -> dict:
    """Latest weight; the change vs the newest entry at least a week and at least a month older
    ({"kg", "since"}: the difference and the day it's measured from); the goal."""
    latest = entries[0] if entries else None

    def change(days: int) -> Optional[dict]:
        if not latest:
            return None
        cutoff = (date.fromisoformat(latest["day"]) - timedelta(days=days)).isoformat()
        older = next((e for e in entries if e["day"] <= cutoff), None)
        return {"kg": round(latest["kg"] - older["kg"], 1), "since": older["day"]} if older else None

    return {
        "latest": latest,
        "change_week": change(7),
        "change_month": change(30),
        "goal_kg": goal or None,
        "to_goal": round(goal - latest["kg"], 1) if latest and goal else None,
        "days_since_last": (today - date.fromisoformat(latest["day"])).days if latest else None,
    }


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = local_today(ctx.tz)
    entries = _entries(widget_row(db, user, WIDGET_ID))
    since = (today - timedelta(days=CHART_DAYS)).isoformat()
    return {
        "today": today.isoformat(),
        **summary(entries, today, float(settings["goal_kg"] or 0)),
        "chart": [e for e in reversed(entries) if e["day"] >= since],  # oldest first
        "recent": entries[:5],
    }


def _signed(value: float) -> str:
    return f"{value:+.1f} kg"


def brief(data: dict, limit: int | None = None) -> str:
    if not data["latest"]:
        return "No weight logged yet."
    parts = [f"Latest weight {data['latest']['kg']} kg ({data['latest']['day']}, {data['days_since_last']} days ago)."]
    changes = [f"{_signed(c['kg'])} since {c['since']}" for c in (data["change_week"], data["change_month"]) if c]
    if changes:
        parts.append("Change: " + ", ".join(dict.fromkeys(changes)) + ".")
    if data["goal_kg"]:
        parts.append(f"Goal {data['goal_kg']} kg ({_signed(data['to_goal'])} to go).")
    return " ".join(parts)


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Weight",
    description="Log your body weight now and then and see the trend over the last 3 months, with an optional goal weight.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 6),
    refresh_seconds=1800,
    config_fields=(
        ConfigField("goal_kg", "Goal weight (kg, 0 = none)", "number", default=0, min=0, max=400),
    ),
))


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class WeightIn(BaseModel):
    day: date  # the user's local date
    kg: float = Field(gt=20, lt=400)


def log_weight(db: Session, user: User, day: date, kg: float) -> tuple[dict, Optional[dict]]:
    """Set the weight for `day` (replacing that day's value). Returns (entry, the replaced entry)."""
    if day > date.today() + timedelta(days=1):
        raise HTTPException(status_code=422, detail="Can't log a weight for a future day")
    row = widget_row(db, user, WIDGET_ID)
    entries = _entries(row)
    previous = next((e for e in entries if e["day"] == day.isoformat()), None)
    entry = {"day": day.isoformat(), "kg": round(kg, 1)}
    _store(row, [e for e in entries if e["day"] != entry["day"]] + [entry])
    db.commit()
    return entry, previous


def delete_weight(db: Session, user: User, day: str) -> dict:
    row = widget_row(db, user, WIDGET_ID)
    entries = _entries(row)
    entry = next((e for e in entries if e["day"] == day), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="No weight logged for that day")
    _store(row, [e for e in entries if e["day"] != day])
    db.commit()
    return entry


@router.post("/entries")
def add_entry(body: WeightIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return log_weight(db, user, body.day, body.kg)[0]


@router.delete("/entries/{day}")
def delete_entry(day: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return delete_weight(db, user, day.isoformat())
