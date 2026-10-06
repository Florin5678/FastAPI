# Gym tracker widget: log workouts and see this week's progress towards weekly goals
# (number of workouts and minutes), which days you trained, the last 8 weeks and a
# streak of weeks that met the workout goal. Weeks start on Monday (local dates).
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import User, Workout
from app.widgets.registry import REGISTRY, ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "gym"
# The starting list of workout types, used once to set up a user's list (config["types"]); after
# that the list lives only in the dashboard: edited on the Gym page, extended by "Other…"
DEFAULT_TYPES = ["Abs", "Legs", "Chest", "Biceps", "Triceps", "Back", "HEMA", "Run", "Shoulders"]
RECENT_DAYS = 14  # workouts listed in the Assistant's briefing
WEEKS_SHOWN = 8
COLOR_SLOTS = 12  # chart palette size (.gym-series-1..12 in gym.css)
SHOWN_TYPES = 9  # the first types in the list are the log form's buttons; the rest come up under "Other…"
MAX_TYPES = 100


def workout_types(db: Session, user: User) -> list[str]:
    """The user's workout types, in order, kept in the widget's row (config["types"]). The first
    time it's DEFAULT_TYPES plus any types already logged, in the order first logged."""
    row = widget_row(db, user, WIDGET_ID)
    saved = (row.config or {}).get("types")
    if saved:
        return list(saved)
    types = list(DEFAULT_TYPES)
    firsts = (db.query(Workout.kind, func.min(Workout.id)).filter(Workout.user_id == user.id)
              .group_by(Workout.kind).order_by(func.min(Workout.id)).all())
    types += [kind for kind, _ in firsts if kind.lower() not in {t.lower() for t in types}]
    row.config = {**(row.config or {}), "types": types}
    db.commit()
    return types


def save_workout_types(db: Session, user: User, types: list[str]) -> list[str]:
    cleaned: list[str] = []
    for name in types:
        name = " ".join(name.split())[:32]
        if name and name.lower() not in {t.lower() for t in cleaned}:
            cleaned.append(name)
    if not cleaned:
        raise HTTPException(status_code=422, detail="Keep at least one workout type")
    row = widget_row(db, user, WIDGET_ID)
    row.config = {**(row.config or {}), "types": cleaned[:MAX_TYPES]}
    db.commit()
    return cleaned[:MAX_TYPES]


def clean_kind(db: Session, user: User, kind: str) -> str:
    """A workout type from the list (matched in any case, spelled as in the list), or a new one
    ("Other…", e.g. Calisthenics), which is added to the end of the list."""
    name = " ".join(kind.split())
    if not name:
        raise HTTPException(status_code=422, detail="Give the workout a type")
    if len(name) > 32:
        raise HTTPException(status_code=422, detail="Workout types can be at most 32 characters")
    types = workout_types(db, user)
    existing = next((t for t in types if t.lower() == name.lower()), None)
    if existing:
        return existing
    save_workout_types(db, user, [*types, name])
    return name


def type_colors(db: Session, user: User) -> dict[str, int]:
    """Workout type -> colour slot (1-12) by its place in the list (shown and hidden types alike),
    so a type has the same colour in every month and chart. Logged types no longer in the list
    (renamed or removed) come after."""
    order = workout_types(db, user)
    logged = [k for (k,) in db.query(Workout.kind).filter(Workout.user_id == user.id).distinct().order_by(Workout.kind)]
    order += [k for k in logged if k not in order]
    return {kind: i % COLOR_SLOTS + 1 for i, kind in enumerate(order)}


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _workout_dict(w: Workout) -> dict:
    return {"id": w.id, "day": w.day.isoformat(), "kind": w.kind, "minutes": w.minutes, "note": w.note}


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = local_today(ctx.tz)
    this_week = _week_start(today)
    first_week = this_week - timedelta(weeks=WEEKS_SHOWN - 1)

    # The weekly goal counts active days (days with at least one workout), not workouts
    trained_days = (
        db.query(Workout.day)
        .filter(Workout.user_id == user.id, Workout.day >= first_week)
        .distinct()
        .all()
    )
    week_counts: dict[date, int] = {}
    for (day,) in trained_days:
        week_counts[_week_start(day)] = week_counts.get(_week_start(day), 0) + 1

    workouts = (
        db.query(Workout)
        .filter(Workout.user_id == user.id, Workout.day >= this_week, Workout.day <= today)
        .order_by(Workout.day.desc(), Workout.created_at.desc())
        .all()
    )
    goal = settings["goal_workouts"]  # (key kept from when the goal counted workouts) active days per week
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
        "goal_active_days": goal,
        "goal_minutes": settings["goal_minutes"],
        "active_days": len(done_days),
        "workouts_done": len(workouts),
        "minutes_done": sum(w.minutes for w in workouts),
        "days": [
            {"day": (this_week + timedelta(days=i)).isoformat(), "trained": (this_week + timedelta(days=i)) in done_days}
            for i in range(7)
        ],
        "streak_weeks": streak,
        "workouts": [_workout_dict(w) for w in workouts],
        "kinds": (types := workout_types(db, user))[:SHOWN_TYPES],  # the log form's buttons
        "other_kinds": types[SHOWN_TYPES:],  # suggested under "Other…"
        # For the Assistant's briefing
        "recent": [
            _workout_dict(w) for w in db.query(Workout)
            .filter(Workout.user_id == user.id, Workout.day >= today - timedelta(days=RECENT_DAYS - 1), Workout.day <= today)
            .order_by(Workout.day.desc(), Workout.created_at.desc())
        ],
    }


def _week_count(db: Session, user: User, week: date) -> int:
    """Active days in the week starting `week`."""
    return (
        db.query(func.count(func.distinct(Workout.day)))
        .filter(Workout.user_id == user.id, Workout.day >= week, Workout.day < week + timedelta(days=7))
        .scalar()
    )


def brief(data: dict, limit: int | None = None) -> str:
    line = (
        f"This week: {data['active_days']} of {data['goal_active_days']} active days (days with a workout; "
        f"{data['workouts_done']} workouts in total), {data['minutes_done']} of {data['goal_minutes']} minutes."
    )
    if data["streak_weeks"]:
        line += f" Streak: {data['streak_weeks']} week(s) meeting the goal."
    lines = [line]
    recent = data.get("recent", [])
    today = date.fromisoformat(data["today"])
    if recent:
        lines.append(f"Workouts in the last {RECENT_DAYS} days (newest first):")
        lines += [f"- {date.fromisoformat(w['day']):%a %d %b}: {w['kind']}, {w['minutes']} min" + (f" ({w['note']})" if w["note"] else "")
                  for w in recent]
    else:
        lines.append(f"No workouts in the last {RECENT_DAYS} days.")
    last: dict[str, int] = {}
    for w in recent:
        last.setdefault(w["kind"], (today - date.fromisoformat(w["day"])).days)
    lines.append("Days since each workout type was last trained: " + ", ".join(
        f"{k} {last[k]}" if k in last else f"{k} {RECENT_DAYS}+" for k in data["kinds"]))
    return "\n".join(lines)


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
        ConfigField("goal_workouts", "Active days per week", "number", default=4, min=1, max=7),
        ConfigField("goal_minutes", "Minutes per week", "number", default=300, min=0, max=3000),
    ),
))


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class TypesIn(BaseModel):
    types: list[str] = Field(min_length=1, max_length=MAX_TYPES)


@router.put("/types")
def put_workout_types(body: TypesIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Replace the list of workout types (order = colours; the first SHOWN_TYPES are the log
    form's buttons). Workouts already logged keep their type name."""
    return {"types": save_workout_types(db, user, body.types)}


class WorkoutIn(BaseModel):
    day: date  # the user's local date
    kind: str = Field(min_length=1, max_length=60)  # a routine or any other type (see clean_kind)
    minutes: int = Field(ge=1, le=600)
    note: Optional[str] = Field(None, max_length=300)


@router.post("/workouts")
def log_workout(body: WorkoutIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    if body.day > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(status_code=422, detail="Workouts can't be logged for a future day")
    workout = Workout(user_id=user.id, day=body.day, kind=clean_kind(db, user, body.kind), minutes=body.minutes,
                      note=(body.note or "").strip() or None)
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return _workout_dict(workout)


class WorkoutPatch(BaseModel):
    day: Optional[date] = None
    kind: Optional[str] = None
    minutes: Optional[int] = Field(None, ge=1, le=600)
    note: Optional[str] = Field(None, max_length=300)  # "" clears it


@router.patch("/workouts/{workout_id}")
def update_workout(workout_id: int, body: WorkoutPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workout = db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == user.id).first()
    if workout is None:
        raise HTTPException(status_code=404, detail="Workout not found")
    if body.kind is not None:
        workout.kind = clean_kind(db, user, body.kind)
    if body.day is not None:
        if body.day > datetime.now(timezone.utc).date() + timedelta(days=1):
            raise HTTPException(status_code=422, detail="Workouts can't be logged for a future day")
        workout.day = body.day
    if body.minutes is not None:
        workout.minutes = body.minutes
    if body.note is not None:
        workout.note = body.note.strip() or None
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


@router.get("/stats")
def stats(
    level: str,  # "week" | "month" | "year"
    anchor: date,  # any day in the period
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Minutes and sessions per workout type for one week, month or year (the Gym page's chart)."""
    widget_row(db, user, WIDGET_ID)
    if level == "week":
        start = _week_start(anchor)
        end = start + timedelta(days=7)
        label = f"Week {start.isocalendar().week} · {start:%d %b} – {end - timedelta(days=1):%d %b %Y}"
    elif level == "month":
        start = anchor.replace(day=1)
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        label = f"{start:%B %Y}"
    elif level == "year":
        start, end = date(anchor.year, 1, 1), date(anchor.year + 1, 1, 1)
        label = str(anchor.year)
    else:
        raise HTTPException(status_code=422, detail="level must be week, month or year")

    workouts = db.query(Workout).filter(Workout.user_id == user.id, Workout.day >= start, Workout.day < end).all()
    totals: dict[str, dict] = {}
    for w in workouts:
        t = totals.setdefault(w.kind, {"kind": w.kind, "sessions": 0, "minutes": 0})
        t["sessions"] += 1
        t["minutes"] += w.minutes
    return {
        "level": level,
        "label": label,
        "start": start.isoformat(),
        "end": (end - timedelta(days=1)).isoformat(),
        "totals": sorted(totals.values(), key=lambda t: -t["minutes"]),  # only types done in the period
        "active_days": len({w.day for w in workouts}),
        "colors": type_colors(db, user),  # type -> colour slot, the same everywhere
    }


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

    # Every Monday-Sunday week that touches the month, counted in full (also the days in the
    # neighbouring months), so each one compares with the weekly goals
    weeks_from, weeks_to = _week_start(start), _week_start(end - timedelta(days=1)) + timedelta(days=7)
    weeks: dict[date, dict] = {}
    week = weeks_from
    while week < weeks_to:
        weeks[week] = {"week_start": week.isoformat(), "week": week.isocalendar().week, "active_days": 0,
                       "sessions": 0, "minutes": 0, "kinds": {}}
        week += timedelta(weeks=1)
    active: set[date] = set()
    for w in db.query(Workout).filter(Workout.user_id == user.id, Workout.day >= weeks_from, Workout.day < weeks_to):
        t = weeks[_week_start(w.day)]
        if w.day not in active:
            active.add(w.day)
            t["active_days"] += 1
        t["sessions"] += 1
        t["minutes"] += w.minutes
        t["kinds"][w.kind] = t["kinds"].get(w.kind, 0) + 1
    goals = REGISTRY[WIDGET_ID].settings_for(widget_row(db, user, WIDGET_ID))

    first = db.query(func.min(Workout.day)).filter(Workout.user_id == user.id).scalar()
    return {
        "month": month,
        "days": days,
        "weeks": list(weeks.values()),
        "goal_active_days": goals["goal_workouts"],
        "goal_minutes": goals["goal_minutes"],
        "totals": sorted(totals.values(), key=lambda t: -t["minutes"]),
        "sessions": len(workouts),
        "minutes": sum(w.minutes for w in workouts),
        "days_trained": len(days),
        "first_month": first.strftime("%Y-%m") if first else None,
        "kinds": workout_types(db, user),  # the whole list, in order (first SHOWN_TYPES are the buttons)
        "shown_types": SHOWN_TYPES,
        "colors": type_colors(db, user),  # type -> colour slot, the same everywhere
    }
