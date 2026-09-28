# Gym tracker widget: log workouts and see this week's progress towards weekly goals
# (number of workouts and minutes), which days you trained, the last 8 weeks and a
# streak of weeks that met the workout goal. Weeks start on Monday (local dates).
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import User, Workout
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "gym"
# Edit the workout types in content/gym_routines.md (repo root)
ROUTINES_FILE = Path(__file__).resolve().parents[2] / "content" / "gym_routines.md"
_routines_cache: dict = {"mtime": None, "routines": []}
WEEKS_SHOWN = 8


def load_routines() -> list[str]:
    """Workout types ("- Name" lines) in file order, re-read when the file changes."""
    mtime = ROUTINES_FILE.stat().st_mtime
    if _routines_cache["mtime"] != mtime:
        names = [line[2:].strip() for line in ROUTINES_FILE.read_text(encoding="utf-8").splitlines()
                 if line.startswith("- ") and line[2:].strip()]
        _routines_cache.update(mtime=mtime, routines=names)
    return _routines_cache["routines"]


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _workout_dict(w: Workout) -> dict:
    return {"id": w.id, "day": w.day.isoformat(), "kind": w.kind, "minutes": w.minutes, "note": w.note}


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = local_today(ctx.tz)
    this_week = _week_start(today)
    first_week = this_week - timedelta(weeks=WEEKS_SHOWN - 1)

    per_day = (
        db.query(Workout.day, func.count(Workout.id))
        .filter(Workout.user_id == user.id, Workout.day >= first_week)
        .group_by(Workout.day)
        .all()
    )
    week_counts: dict[date, int] = {}
    for day, n in per_day:
        week_counts[_week_start(day)] = week_counts.get(_week_start(day), 0) + n

    workouts = (
        db.query(Workout)
        .filter(Workout.user_id == user.id, Workout.day >= this_week, Workout.day <= today)
        .order_by(Workout.day.desc(), Workout.created_at.desc())
        .all()
    )
    goal = settings["goal_workouts"]
    done_days = {w.day for w in workouts}

    def count(week: date) -> int:
        return week_counts.get(week, 0) if week >= first_week else _week_count(db, user, week)

    # Consecutive weeks that met the goal, counting back from last week. This week
    # counts once it's met, but an unfinished week doesn't break the streak.
    streak = 1 if count(this_week) >= goal else 0
    week = this_week - timedelta(weeks=1)
    while streak < 520 and count(week) >= goal:
        streak += 1
        week -= timedelta(weeks=1)

    return {
        "today": today.isoformat(),
        "week_start": this_week.isoformat(),
        "goal_workouts": goal,
        "goal_minutes": settings["goal_minutes"],
        "workouts_done": len(workouts),
        "minutes_done": sum(w.minutes for w in workouts),
        "days": [
            {"day": (this_week + timedelta(days=i)).isoformat(), "trained": (this_week + timedelta(days=i)) in done_days}
            for i in range(7)
        ],
        "weeks": [
            {"week_start": (first_week + timedelta(weeks=i)).isoformat(),
             "workouts": week_counts.get(first_week + timedelta(weeks=i), 0)}
            for i in range(WEEKS_SHOWN)
        ],
        "streak_weeks": streak,
        "workouts": [_workout_dict(w) for w in workouts],
        "kinds": load_routines(),
    }


def _week_count(db: Session, user: User, week: date) -> int:
    return (
        db.query(func.count(Workout.id))
        .filter(Workout.user_id == user.id, Workout.day >= week, Workout.day < week + timedelta(days=7))
        .scalar()
    )


def brief(data: dict, limit: int | None = None) -> str:
    line = (
        f"This week: {data['workouts_done']} of {data['goal_workouts']} workouts, "
        f"{data['minutes_done']} of {data['goal_minutes']} minutes."
    )
    if data["streak_weeks"]:
        line += f" Streak: {data['streak_weeks']} week(s) meeting the goal."
    return line


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Gym",
    description="Log workouts and see how close you are to this week's goals, plus your weekly streak.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 6),
    refresh_seconds=900,
    enabled_by_default=True,
    config_fields=(
        ConfigField("goal_workouts", "Workouts per week", "number", default=4, min=1, max=14),
        ConfigField("goal_minutes", "Minutes per week", "number", default=300, min=0, max=3000),
    ),
))


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class WorkoutIn(BaseModel):
    day: date  # the user's local date
    kind: str
    minutes: int = Field(ge=1, le=600)
    note: Optional[str] = Field(None, max_length=300)


@router.post("/workouts")
def log_workout(body: WorkoutIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    routines = load_routines()
    if body.kind not in routines:
        raise HTTPException(status_code=422, detail=f"Type must be one of: {', '.join(routines)}")
    if body.day > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(status_code=422, detail="Workouts can't be logged for a future day")
    workout = Workout(user_id=user.id, day=body.day, kind=body.kind, minutes=body.minutes, note=(body.note or "").strip() or None)
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return _workout_dict(workout)


@router.delete("/workouts/{workout_id}")
def delete_workout(workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == user.id).first()
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    db.delete(workout)
    db.commit()
    return {"deleted": workout_id}


@router.get("/month")
def month_report(
    month: str,  # "YYYY-MM"
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every workout in one month, by day, plus totals per routine."""
    widget_row(db, user, WIDGET_ID)
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(status_code=422, detail="month must look like 2026-09") from None
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)

    workouts = (
        db.query(Workout)
        .filter(Workout.user_id == user.id, Workout.day >= start, Workout.day < end)
        .order_by(Workout.day, Workout.created_at)
        .all()
    )
    days: dict[str, list[dict]] = {}
    totals: dict[str, dict] = {}
    for w in workouts:
        days.setdefault(w.day.isoformat(), []).append(_workout_dict(w))
        t = totals.setdefault(w.kind, {"kind": w.kind, "sessions": 0, "minutes": 0})
        t["sessions"] += 1
        t["minutes"] += w.minutes

    first = db.query(func.min(Workout.day)).filter(Workout.user_id == user.id).scalar()
    return {
        "month": month,
        "days": days,
        "totals": sorted(totals.values(), key=lambda t: -t["minutes"]),
        "sessions": len(workouts),
        "minutes": sum(w.minutes for w in workouts),
        "days_trained": len(days),
        "first_month": first.strftime("%Y-%m") if first else None,
    }
