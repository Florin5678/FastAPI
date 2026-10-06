# Nutrition widget: daily intake vs goals, filled from a food log.
#
# Goals are widget settings (they persist). Every logged food is a row in
# nutrition_entries (keyed by the user's local day), kept indefinitely; each day
# starts at zero. nutrition_days snapshots the goals that applied on a day when
# food is logged, so past days are judged against the goals of that time.
# The widget opens into a full view (frontend: NutritionPage) to browse any day.
# Entries can be edited (amount, values, name, day). Foods entered by hand can be
# saved to "My foods" (widget row config["saved_foods"], values per 100 g) and
# picked again later.
#
# Pantry: the food the user has at home (config["pantry"]: name, amount as free text,
# optional best-before date). Shown from the tile's 🥫 Pantry button and used by Claude for
# meal suggestions; deliberately not part of fetch(), so it stays out of the briefing.
#
# Food lookup, both free and searched together:
# - USDA FoodData Central: generic foods and dishes (needs a free key from
#   https://fdc.nal.usda.gov/api-key-signup.html in USDA_API_KEY - the shared
#   DEMO_KEY only allows ~10 lookups/hour. With a key: 1,000 requests/hour).
# - Open Food Facts (https://world.openfoodfacts.org, ODbL): branded packaged products
#   worldwide, incl. Danish/Romanian supermarkets; values from the labels. No key;
#   asks for an identifying User-Agent.
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from typing import Optional
from urllib.parse import quote, urlencode

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.timeutil import local_today
from app.core.database import get_db
from app.models import NutritionDay, NutritionEntry, User
from app.core.security import get_current_user
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "nutrition"
HISTORY_MAX_DAYS = 366
FDC_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFF_SEARCH_URL = "https://search.openfoodfacts.org/search"
OFF_USER_AGENT = "PersonalDashboard/1.0 (https://github.com/Florin5678/FastAPI; personal non-commercial dashboard)"
# Open Food Facts nutriment keys (per 100 g) for our nutrients
OFF_KEYS = {
    "calories": "energy-kcal_100g", "protein": "proteins_100g", "carbs": "carbohydrates_100g", "fat": "fat_100g",
    "fiber": "fiber_100g", "sugar": "sugars_100g", "sat_fat": "saturated-fat_100g", "salt": "salt_100g",
}
SEARCH_CACHE_SECONDS = 24 * 3600

# key, label, unit, kind ("goal" = reach it, "limit" = stay under it), FDC nutrient numbers
NUTRIENTS = [
    ("calories", "Calories", "kcal", "goal", ("208", "958", "957")),
    ("protein", "Protein", "g", "goal", ("203",)),
    ("carbs", "Carbs", "g", "goal", ("205",)),
    ("fat", "Fat", "g", "goal", ("204",)),
    ("fiber", "Fiber", "g", "goal", ("291",)),
    ("sugar", "Sugar", "g", "limit", ("269", "269.3")),
    ("sat_fat", "Sat. fat", "g", "limit", ("606",)),
    ("salt", "Salt", "g", "limit", ("307",)),  # USDA lists sodium (mg): see SODIUM_TO_SALT
]

# Starting goals, from the user's profile: male, 27 y, 173 cm, 66 kg, 3-4 workouts/week,
# pescatarian, wants to gain weight/muscle with a balanced diet.
#   BMR (Mifflin-St Jeor) = 10*66 + 6.25*173 - 5*27 + 5 = 1,611 kcal
#   Maintenance = BMR * 1.55 = ~2,500 kcal; lean-bulk surplus +400 -> 2,900 kcal
#   Protein 2.0 g/kg = 130 g · Fat ~27% of kcal = 85 g · Carbs = the rest = 400 g
#   Fiber 14 g/1,000 kcal ~ 38 g · Sugar < 10% of kcal = 70 g · Sat. fat < 10% = 30 g
# (Also hardcoded in the a7c3e1f92b10 migration, which moved the old JSON log.)
DEFAULT_GOALS = {
    "calories": 2900, "protein": 130, "carbs": 400, "fat": 85,
    "fiber": 38, "sugar": 70, "sat_fat": 30, "salt": 6,  # salt: the Danish limit for men
}
GOAL_MAX = {"calories": 10000}
MAX_SAVED_FOODS = 300
MAX_PANTRY_ITEMS = 300

_search_cache: dict[str, tuple[float, list]] = {}


def _latest_allowed_day() -> date:
    # The client sends its local date; anywhere on Earth that's at most UTC + 1 day
    return datetime.now(timezone.utc).date() + timedelta(days=1)


def _current_goals(db: Session, user: User) -> dict:
    """Goals from the widget's settings (defaults for any never changed)."""
    settings = (widget_row(db, user, WIDGET_ID).config or {}).get("settings") or {}
    return {key: settings.get(f"goal_{key}", DEFAULT_GOALS[key]) for key, *_ in NUTRIENTS}


def _goals_for(db: Session, user: User, day: date) -> dict:
    snapshot = db.query(NutritionDay).filter(NutritionDay.user_id == user.id, NutritionDay.day == day).first()
    return {**_current_goals(db, user), **(snapshot.goals if snapshot else {})}


def _entry_dict(e: NutritionEntry) -> dict:
    return {
        "id": e.id,
        "day": e.day.isoformat(),
        "name": e.name,
        "grams": e.grams,
        "source": e.source,
        "nutrients": {key: getattr(e, key) for key, *_ in NUTRIENTS},
        "added_at": (e.created_at.isoformat() + "Z") if e.created_at else None,
    }


def _nutrient_rows(goals: dict, totals: dict) -> list[dict]:
    return [
        {"key": key, "label": label, "unit": unit, "kind": kind, "goal": goals[key], "actual": round(totals.get(key, 0), 1)}
        for key, label, unit, kind, _ in NUTRIENTS
    ]


def day_summary(db: Session, user: User, day: date) -> dict:
    entries = (
        db.query(NutritionEntry)
        .filter(NutritionEntry.user_id == user.id, NutritionEntry.day == day)
        .order_by(NutritionEntry.created_at.desc(), NutritionEntry.id.desc())
        .all()
    )
    totals = {key: sum(getattr(e, key) for e in entries) for key, *_ in NUTRIENTS}
    return {
        "day": day.isoformat(),
        "nutrients": _nutrient_rows(_goals_for(db, user, day), totals),
        "entries": [_entry_dict(e) for e in entries],
        "personal_food_key": bool(os.getenv("USDA_API_KEY")),  # else the shared, very limited DEMO_KEY
    }


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = local_today(ctx.tz)
    yesterday = day_summary(db, user, today - timedelta(days=1))
    # Yesterday is only for the Assistant briefing (see brief())
    return {**day_summary(db, user, today), "yesterday": {"nutrients": yesterday["nutrients"], "entries": yesterday["entries"]}}


def _brief_day(day: dict, limit: int | None) -> tuple[str, str]:
    """("Calories 1450/2900 kcal; ...", "food, food, ...") for one day."""
    parts = [f"{n['label']} {round(n['actual'])}/{round(n['goal'])} {n['unit']}" + (" (limit)" if n["kind"] == "limit" else "")
             for n in day["nutrients"]]
    return "; ".join(parts), ", ".join(e["name"] for e in day["entries"][:limit or 8])


def brief(data: dict, limit: int | None = None) -> str:
    totals, foods = _brief_day(data, limit)
    text = f"Today's intake vs goals: {totals}. Foods: {foods or 'nothing logged yet'}."
    yesterday = data.get("yesterday")
    if yesterday and yesterday["entries"]:
        totals, foods = _brief_day(yesterday, limit)
        text += f"\nYesterday's intake vs goals: {totals}. Foods: {foods}."
    elif yesterday is not None:
        text += "\nYesterday: nothing logged."
    return text


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Nutrition",
    description="Daily intake vs your goals (calories, protein, carbs, fat, fiber, sugar). Log meals from the USDA and Open Food Facts databases or by hand; every day is kept in your history.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 9),
    min_size=(3, 6),
    refresh_seconds=600,
    enabled_by_default=True,
    config_fields=tuple(
        ConfigField(
            f"goal_{key}",
            f"{label} {'limit' if kind == 'limit' else 'goal'} ({unit})",
            "number",
            default=DEFAULT_GOALS[key],
            min=0,
            max=GOAL_MAX.get(key, 1000),
        )
        for key, label, unit, kind, _ in NUTRIENTS
    ),
))


# ---- Food log, history and food search routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class Nutrients(BaseModel):
    calories: float = Field(0, ge=0, le=20000)
    protein: float = Field(0, ge=0, le=2000)
    carbs: float = Field(0, ge=0, le=2000)
    fat: float = Field(0, ge=0, le=2000)
    fiber: float = Field(0, ge=0, le=2000)
    sugar: float = Field(0, ge=0, le=2000)
    sat_fat: float = Field(0, ge=0, le=2000)
    salt: float = Field(0, ge=0, le=500)


class EntryIn(BaseModel):
    day: date  # the viewer's local date (today, or a past day being filled in)
    name: str = Field(min_length=1, max_length=200)
    grams: Optional[float] = Field(None, gt=0, le=5000)
    nutrients: Nutrients  # for the amount eaten
    source: str = Field("manual", pattern="^(manual|usda|off)$")
    fdc_id: Optional[int] = None
    per_100g: Optional[Nutrients] = None  # with save=True: store the food in "My foods"
    save: bool = False
    saved_food_id: Optional[str] = Field(None, max_length=40)  # picked from "My foods" (moves it to the top)


class EntryPatch(BaseModel):
    day: Optional[date] = None
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    grams: Optional[float] = Field(None, gt=0, le=5000)
    nutrients: Optional[Nutrients] = None  # new totals; if only grams changes, totals are rescaled


def _ensure_day_snapshot(db: Session, user: User, day: date) -> None:
    """Snapshot the goals for a day the first time food is logged on it. For today,
    later logs refresh the snapshot (so a goal change today applies today); past days
    keep theirs."""
    snapshot = db.query(NutritionDay).filter(NutritionDay.user_id == user.id, NutritionDay.day == day).first()
    is_recent = day >= datetime.now(timezone.utc).date() - timedelta(days=1)
    if snapshot is None:
        db.add(NutritionDay(user_id=user.id, day=day, goals=_current_goals(db, user)))
    elif is_recent:
        snapshot.goals = _current_goals(db, user)


# ---- "My foods": foods entered by hand, kept to pick again (values per 100 g) ----

def _saved_foods(row) -> list[dict]:
    return [dict(f) for f in (row.config or {}).get("saved_foods", [])]


def _store_saved_foods(row, foods: list[dict]) -> None:
    foods.sort(key=lambda f: f.get("used_at") or "", reverse=True)
    # JSON columns aren't mutation-tracked: assign a new dict
    row.config = {**(row.config or {}), "saved_foods": foods[:MAX_SAVED_FOODS]}


def save_food(db: Session, user: User, name: str, per_100g: dict, grams: Optional[float]) -> dict:
    """Add a food to "My foods", or update the one with the same name."""
    row = widget_row(db, user, WIDGET_ID)
    foods = _saved_foods(row)
    now = datetime.now(timezone.utc).isoformat()
    existing = next((f for f in foods if f["name"].lower() == name.strip().lower()), None)
    food = existing or {"id": uuid.uuid4().hex[:12], "uses": 0}
    food.update(name=name.strip(), per_100g={k: round(float(v), 2) for k, v in per_100g.items()},
                grams=grams, used_at=now, uses=food.get("uses", 0) + 1)
    if existing is None:
        foods.append(food)
    _store_saved_foods(row, foods)
    return food


def _mark_used(db: Session, user: User, food_id: str, grams: Optional[float]) -> None:
    row = widget_row(db, user, WIDGET_ID)
    foods = _saved_foods(row)
    food = next((f for f in foods if f["id"] == food_id), None)
    if food is not None:
        food.update(used_at=datetime.now(timezone.utc).isoformat(), uses=food.get("uses", 0) + 1, grams=grams or food.get("grams"))
        _store_saved_foods(row, foods)


@router.get("/days/{day}")
def get_day(day: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """One day's totals vs that day's goals, plus its food log."""
    widget_row(db, user, WIDGET_ID)
    if day > _latest_allowed_day():
        raise HTTPException(status_code=422, detail="That day hasn't happened yet")
    return day_summary(db, user, day)


@router.get("/history")
def history(
    end: date = Query(..., description="Last day (inclusive), usually the viewer's today"),
    days: int = Query(14, ge=1, le=HISTORY_MAX_DAYS),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Daily totals for `days` days ending on `end`, newest first (days without food have zeros)."""
    widget_row(db, user, WIDGET_ID)
    start = end - timedelta(days=days - 1)
    sums = (
        db.query(
            NutritionEntry.day,
            func.count(NutritionEntry.id),
            *[func.sum(getattr(NutritionEntry, key)) for key, *_ in NUTRIENTS],
        )
        .filter(NutritionEntry.user_id == user.id, NutritionEntry.day >= start, NutritionEntry.day <= end)
        .group_by(NutritionEntry.day)
        .all()
    )
    by_day = {row[0]: row for row in sums}
    snapshots = {
        d.day: d.goals
        for d in db.query(NutritionDay).filter(
            NutritionDay.user_id == user.id, NutritionDay.day >= start, NutritionDay.day <= end
        )
    }
    current = _current_goals(db, user)

    result = []
    for offset in range(days):
        day = end - timedelta(days=offset)
        row = by_day.get(day)
        totals = {key: float(row[2 + i] or 0) if row else 0.0 for i, (key, *_) in enumerate(NUTRIENTS)}
        result.append({
            "day": day.isoformat(),
            "entries": row[1] if row else 0,
            "nutrients": _nutrient_rows({**current, **snapshots.get(day, {})}, totals),
        })
    first = db.query(func.min(NutritionEntry.day)).filter(NutritionEntry.user_id == user.id).scalar()
    return {"days": result, "first_logged_day": first.isoformat() if first else None}


def history_detail(db: Session, user: User, end: date, days: int) -> dict:
    """For each of `days` days ending on `end` (newest first): the goals, what was eaten, the
    share of each goal reached and the foods logged (with ids, to edit them)."""
    summary = history(end=end, days=days, user=user, db=db)
    entries = (
        db.query(NutritionEntry)
        .filter(NutritionEntry.user_id == user.id, NutritionEntry.day >= end - timedelta(days=days - 1),
                NutritionEntry.day <= end)
        .order_by(NutritionEntry.created_at, NutritionEntry.id)
        .all()
    )
    foods: dict[str, list[dict]] = {}
    for e in entries:
        foods.setdefault(e.day.isoformat(), []).append(
            {"id": e.id, "name": e.name, "grams": e.grams, "calories": round(e.calories), "protein": round(e.protein, 1)})
    return {
        "days": [
            {
                "day": d["day"],
                "logged": bool(d["entries"]),
                "nutrients": [
                    {"nutrient": n["label"], "unit": n["unit"], "kind": n["kind"], "goal": n["goal"], "eaten": n["actual"],
                     "percent_of_goal": round(100 * n["actual"] / n["goal"]) if n["goal"] else None}
                    for n in d["nutrients"]
                ],
                "foods": foods.get(d["day"], []),
            }
            for d in summary["days"]
        ],
        "first_logged_day": summary["first_logged_day"],
    }


@router.post("/entries")
def add_entry(body: EntryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    if body.day > _latest_allowed_day():
        raise HTTPException(status_code=422, detail="You can't log food for a future day")

    entry = NutritionEntry(
        user_id=user.id,
        day=body.day,
        name=body.name.strip(),
        grams=body.grams,
        source=body.source,
        fdc_id=body.fdc_id,
        **{k: round(v, 1) for k, v in body.nutrients.model_dump().items()},
    )
    db.add(entry)
    _ensure_day_snapshot(db, user, body.day)
    if body.save and body.per_100g is not None:
        save_food(db, user, body.name, body.per_100g.model_dump(), body.grams)
    elif body.saved_food_id:
        _mark_used(db, user, body.saved_food_id, body.grams)

    db.commit()
    db.refresh(entry)
    return _entry_dict(entry)


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Edit a logged food: name, day, amount and/or values. Changing only the amount
    rescales the values (when the entry has an amount)."""
    entry = db.query(NutritionEntry).filter(NutritionEntry.id == entry_id, NutritionEntry.user_id == user.id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if body.day is not None:
        if body.day > _latest_allowed_day():
            raise HTTPException(status_code=422, detail="You can't log food for a future day")
        entry.day = body.day
        _ensure_day_snapshot(db, user, body.day)
    if body.name is not None:
        entry.name = body.name.strip()
    if body.nutrients is not None:
        for key, value in body.nutrients.model_dump().items():
            setattr(entry, key, round(value, 1))
    elif body.grams is not None and entry.grams:
        factor = body.grams / entry.grams
        for key, *_ in NUTRIENTS:
            setattr(entry, key, round(getattr(entry, key) * factor, 1))
    if body.grams is not None:
        entry.grams = body.grams
    db.commit()
    db.refresh(entry)
    return _entry_dict(entry)


@router.get("/saved-foods")
def list_saved_foods(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """ "My foods", most recently used first (values per 100 g)."""
    return {"foods": _saved_foods(widget_row(db, user, WIDGET_ID))}


@router.delete("/saved-foods/{food_id}")
def delete_saved_food(food_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    foods = _saved_foods(row)
    remaining = [f for f in foods if f["id"] != food_id]
    if len(remaining) == len(foods):
        raise HTTPException(status_code=404, detail="Saved food not found")
    _store_saved_foods(row, remaining)
    db.commit()
    return {"deleted": food_id}


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.query(NutritionEntry).filter(NutritionEntry.id == entry_id, NutritionEntry.user_id == user.id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}


# ---- Meal planning (the connector's plan_meals) ----

# Meals of the day and when each one is over (local time); only the ones still ahead get planned
MEALS = [("breakfast", clock(10, 30)), ("lunch", clock(14, 30)), ("afternoon snack", clock(17, 0)),
         ("dinner", clock(21, 0)), ("evening snack", clock(23, 30))]
HISTORY_DAYS = 7
RECENT_FOOD_DAYS = 3


def meal_plan_context(db: Session, user: User, now: datetime) -> dict:
    """Everything needed to plan the rest of today's meals: the meals still ahead, today's goals
    vs what's eaten, the last week's pattern, recent foods (for variety) and the pantry."""
    today = now.date()
    summary = day_summary(db, user, today)
    nutrients = [
        {"nutrient": n["label"], "unit": n["unit"], "kind": n["kind"], "goal": n["goal"], "eaten": n["actual"],
         # goals: how much is still missing; limits: how much is left before going over (negative = over)
         "remaining": round(max(n["goal"] - n["actual"], 0) if n["kind"] == "goal" else n["goal"] - n["actual"], 1)}
        for n in summary["nutrients"]
    ]

    past = history(end=today - timedelta(days=1), days=HISTORY_DAYS, user=user, db=db)["days"]
    logged = [d for d in past if d["entries"]]
    averages, often_short, often_over = [], [], []
    for i, (_key, label, unit, kind, _) in enumerate(NUTRIENTS):
        if not logged:
            break
        avg = sum(d["nutrients"][i]["actual"] for d in logged) / len(logged)
        goal = sum(d["nutrients"][i]["goal"] for d in logged) / len(logged)
        averages.append({"nutrient": label, "unit": unit, "daily_average": round(avg, 1), "goal": round(goal, 1)})
        if kind == "goal" and goal and avg < 0.85 * goal:
            often_short.append(label)
        if kind == "limit" and goal and avg > goal:
            often_over.append(label)

    recent = (
        db.query(NutritionEntry.name)
        .filter(NutritionEntry.user_id == user.id, NutritionEntry.day >= today - timedelta(days=RECENT_FOOD_DAYS),
                NutritionEntry.day < today)
        .distinct()
        .all()
    )
    pantry = []
    for item in _pantry(widget_row(db, user, WIDGET_ID)):
        days_left = (date.fromisoformat(item["expires"]) - today).days if item.get("expires") else None
        pantry.append({"name": item["name"], "amount": item["amount"], "priority": bool(item.get("priority")),
                       "best_before": item.get("expires"), "days_left": days_left})
    # Starred first, then the soonest best-before
    pantry.sort(key=lambda i: (not i["priority"], i["days_left"] is None, i["days_left"] if i["days_left"] is not None else 0))

    # When food was last logged (roughly when they last ate), local time
    logged = [datetime.fromisoformat(e["added_at"].replace("Z", "+00:00")) for e in summary["entries"] if e["added_at"]]
    last_logged = f"{max(logged).astimezone(now.tzinfo):%H:%M}" if logged else None

    return {
        "local_time": now.strftime("%A %d %B %Y, %H:%M"),
        "upcoming_meals": [name for name, ends in MEALS if now.time() < ends],
        "today": {"nutrients": nutrients, "eaten": [f"{e['name']}" + (f" ({e['grams']:g} g)" if e["grams"] else "")
                                                    for e in reversed(summary["entries"])],
                  "last_logged_at": last_logged},
        "last_7_days": {"days_logged": len(logged), "averages": averages, "often_short": often_short,
                        "often_over_limit": often_over},
        "recent_foods": sorted(name for (name,) in recent),
        "pantry": pantry,  # ★ priority first, then soonest best-before
        "shopping_list": [i["name"] for i in _items(widget_row(db, user, WIDGET_ID), "shopping")],
    }


# ---- Pantry & shopping list ----
# Two lists in the widget's row, alphabetical: config["pantry"] (food at home: name, amount,
# best-before, priority star) and config["shopping"] (name, amount, note). Every change
# returns `undo`: per list, the ids it added and the previous versions of the items it
# changed or removed, so the connector's undo can put back exactly those.

LISTS = {"pantry": "Pantry item", "shopping": "Shopping list item"}


class PantryItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: str = Field("", max_length=60)  # free text: "500 g", "6", "half a bag"
    expires: Optional[date] = None  # best before
    priority: Optional[bool] = None  # ★: use first (close to expiring, opened cans...)


class PantryItemPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    amount: Optional[str] = Field(None, max_length=60)
    expires: Optional[date] = None  # send null to clear
    priority: Optional[bool] = None


class ShoppingItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: str = Field("", max_length=60)
    note: str = Field("", max_length=200)


class ShoppingItemPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    amount: Optional[str] = Field(None, max_length=60)
    note: Optional[str] = Field(None, max_length=200)


def _items(row, kind: str) -> list[dict]:
    return [dict(i) for i in (row.config or {}).get(kind, [])]


def _store(row, kind: str, items: list[dict]) -> list[dict]:
    if len(items) > MAX_PANTRY_ITEMS:
        raise HTTPException(status_code=422, detail=f"A list holds up to {MAX_PANTRY_ITEMS} items")
    items.sort(key=lambda i: i["name"].lower())  # alphabetical
    row.config = {**(row.config or {}), kind: items}  # JSON columns aren't mutation-tracked
    return items


# (kept for the change log's older undo actions)
def _pantry(row) -> list[dict]:
    return _items(row, "pantry")


def _store_pantry(row, items: list[dict]) -> list[dict]:
    return _store(row, "pantry", items)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge(items: list[dict], kind: str, new: list[dict], undo: dict) -> tuple[list[dict], list[dict]]:
    """Add `new` items ({name, amount, ...}) to `items`; one already there (same name, any case)
    is updated with the non-empty fields instead of duplicated. Returns (added, updated)."""
    by_name = {i["name"].lower(): i for i in items}
    added, updated = [], []
    for fields in new:
        name = fields["name"].strip()
        existing = by_name.get(name.lower())
        if existing:
            undo[kind]["before"].append(dict(existing))
            for key, value in fields.items():
                if key != "name" and value not in (None, ""):
                    existing[key] = value.strip() if isinstance(value, str) else value
            existing["updated_at"] = _now_iso()
            updated.append(existing)
        else:
            item = {"id": uuid.uuid4().hex[:12], "name": name, "amount": "", "added_at": _now_iso(), "updated_at": _now_iso()}
            item.update({"expires": None, "priority": False} if kind == "pantry" else {"note": ""})
            item.update({k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items() if k != "name" and v is not None})
            items.append(item)
            by_name[name.lower()] = item
            undo[kind]["added"].append(item["id"])
            added.append(item)
    return added, updated


def _new_undo() -> dict:
    return {kind: {"added": [], "before": []} for kind in LISTS}


def _pantry_fields(body: PantryItemIn) -> dict:
    return {"name": body.name, "amount": body.amount, "expires": body.expires.isoformat() if body.expires else None,
            "priority": body.priority}


def add_pantry_items(db: Session, user: User, new: list[PantryItemIn]) -> dict:
    """Add items to the pantry (merging ones already there) and take the same names off the
    shopping list (they've been bought)."""
    row = widget_row(db, user, WIDGET_ID)
    undo = _new_undo()
    pantry, shopping = _items(row, "pantry"), _items(row, "shopping")
    added, updated = _merge(pantry, "pantry", [_pantry_fields(b) for b in new], undo)
    names = {b.name.strip().lower() for b in new}
    bought = [i for i in shopping if i["name"].lower() in names]
    undo["shopping"]["before"] += bought
    _store(row, "pantry", pantry)
    _store(row, "shopping", [i for i in shopping if i not in bought])
    db.commit()
    return {"added": added, "updated": updated, "removed_from_shopping_list": [i["name"] for i in bought], "undo": undo}


def add_shopping_items(db: Session, user: User, new: list[ShoppingItemIn]) -> dict:
    row = widget_row(db, user, WIDGET_ID)
    undo = _new_undo()
    shopping = _items(row, "shopping")
    added, updated = _merge(shopping, "shopping", [b.model_dump() for b in new], undo)
    _store(row, "shopping", shopping)
    db.commit()
    return {"added": added, "updated": updated, "undo": undo}


def update_item(db: Session, user: User, kind: str, item_id: str, changes: dict) -> tuple[dict, dict]:
    """Change one item (`changes`: only the fields to set; expires None clears it)."""
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, kind)
    item = next((i for i in items if i["id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{LISTS[kind]} not found")
    undo = _new_undo()
    undo[kind]["before"].append(dict(item))
    for key, value in changes.items():
        item[key] = value.strip() if isinstance(value, str) else value
    item["updated_at"] = _now_iso()
    _store(row, kind, items)
    db.commit()
    return item, undo


def delete_items(db: Session, user: User, kind: str, item_ids: list[str]) -> tuple[list[dict], dict]:
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, kind)
    gone = [i for i in items if i["id"] in item_ids]
    if len(gone) != len(set(item_ids)):
        raise HTTPException(status_code=404, detail=f"{LISTS[kind]} not found")
    undo = _new_undo()
    undo[kind]["before"] += gone
    _store(row, kind, [i for i in items if i["id"] not in item_ids])
    db.commit()
    return gone, undo


def move_items(db: Session, user: User, source: str, item_ids: list[str]) -> dict:
    """Move items from one list to the other: shopping -> pantry (bought) or pantry ->
    shopping (used up, buy again). Names already on the other list are merged."""
    target = "pantry" if source == "shopping" else "shopping"
    row = widget_row(db, user, WIDGET_ID)
    items = _items(row, source)
    moving = [i for i in items if i["id"] in item_ids]
    if len(moving) != len(set(item_ids)):
        raise HTTPException(status_code=404, detail=f"{LISTS[source]} not found")
    undo = _new_undo()
    undo[source]["before"] += moving
    others = _items(row, target)
    keep = ("name", "amount", "expires", "priority") if target == "pantry" else ("name", "amount", "note")
    added, updated = _merge(others, target, [{k: v for k, v in i.items() if k in keep} for i in moving], undo)
    _store(row, source, [i for i in items if i["id"] not in item_ids])
    _store(row, target, others)
    db.commit()
    return {"moved_to": target, "added": added, "updated": updated, "undo": undo}


def restore_lists(db: Session, user: User, undo: dict) -> None:
    """Reverse a change: drop the items it added, put back the previous versions of the rest."""
    row = widget_row(db, user, WIDGET_ID)
    for kind, change in undo.items():
        before = {i["id"]: i for i in change.get("before", [])}
        items = [i for i in _items(row, kind) if i["id"] not in change.get("added", []) and i["id"] not in before]
        _store(row, kind, items + list(before.values()))
    db.commit()


@router.get("/pantry")
def list_pantry(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    return {"items": _items(row, "pantry"), "shopping": _items(row, "shopping")}


@router.post("/pantry")
def add_pantry_item(body: PantryItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = widget_row(db, user, WIDGET_ID)
    pantry = _items(row, "pantry")
    added, updated = _merge(pantry, "pantry", [_pantry_fields(body)], _new_undo())
    _store(row, "pantry", pantry)
    db.commit()
    return (added or updated)[0]


@router.patch("/pantry/{item_id}")
def update_pantry_item(item_id: str, body: PantryItemPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_unset=True)
    if "expires" in changes:
        changes["expires"] = body.expires.isoformat() if body.expires else None
    return update_item(db, user, "pantry", item_id, changes)[0]


@router.delete("/pantry/{item_id}")
def delete_pantry_item(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_items(db, user, "pantry", [item_id])
    return {"deleted": item_id}


@router.post("/pantry/{item_id}/to-shopping")
def pantry_to_shopping(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Used up: move it to the shopping list."""
    return {k: v for k, v in move_items(db, user, "pantry", [item_id]).items() if k != "undo"}


@router.post("/shopping")
def add_shopping_item(body: ShoppingItemIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = add_shopping_items(db, user, [body])
    return (result["added"] or result["updated"])[0]


@router.patch("/shopping/{item_id}")
def update_shopping_item(item_id: str, body: ShoppingItemPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return update_item(db, user, "shopping", item_id, body.model_dump(exclude_unset=True))[0]


@router.delete("/shopping/{item_id}")
def delete_shopping_item(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_items(db, user, "shopping", [item_id])
    return {"deleted": item_id}


@router.post("/shopping/{item_id}/to-pantry")
def shopping_to_pantry(item_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Bought: move it to the pantry."""
    return {k: v for k, v in move_items(db, user, "shopping", [item_id]).items() if k != "undo"}


SODIUM_TO_SALT = 2.5 / 1000  # mg sodium -> g salt


def _per_100g(food: dict) -> dict:
    by_number = {str(n.get("nutrientNumber")): n.get("value") for n in food.get("foodNutrients", [])}
    values = {}
    for key, _label, _unit, _kind, numbers in NUTRIENTS:
        value = float(next((by_number[n] for n in numbers if by_number.get(n) is not None), 0))
        values[key] = round(value * SODIUM_TO_SALT if key == "salt" else value, 2)
    return values


class _SearchFailed(Exception):
    def __init__(self, message: str):
        self.message = message


def _search_usda(query: str) -> list[dict]:
    params = {
        "api_key": os.getenv("USDA_API_KEY") or "DEMO_KEY",
        "query": query,
        "pageSize": 15,
        # Generic foods and dishes; branded products come from Open Food Facts instead
        "dataType": "Foundation,SR Legacy,Survey (FNDDS)",
    }
    # USDA's server rejects "+" for spaces (400); encode spaces as %20, keep , ( ) literal
    url = f"{FDC_SEARCH_URL}?{urlencode(params, quote_via=quote, safe=',()')}"
    try:
        response = requests.get(url, timeout=15)
    except requests.RequestException:
        raise _SearchFailed("USDA didn't respond") from None
    if response.status_code == 429:
        raise _SearchFailed("USDA search limit reached for this hour (a personal USDA key raises it)")
    if not response.ok:
        raise _SearchFailed(f"USDA returned an error ({response.status_code})")
    return [
        {"source": "usda", "id": str(food["fdcId"]), "fdc_id": food["fdcId"], "name": food["description"],
         "brand": None, "data_type": food.get("dataType"), "per_100g": _per_100g(food)}
        for food in response.json().get("foods", [])
    ]


def _off_value(nutriments: dict, key: str) -> Optional[float]:
    value = nutriments.get(OFF_KEYS[key])
    if value is None and key == "calories" and nutriments.get("energy-kj_100g") is not None:
        value = float(nutriments["energy-kj_100g"]) / 4.184  # some labels only give kJ
    if value is None and key == "salt" and nutriments.get("sodium_100g") is not None:
        value = float(nutriments["sodium_100g"]) * 2.5  # some labels only give sodium (g)
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _search_open_food_facts(query: str) -> list[dict]:
    try:
        response = requests.get(
            OFF_SEARCH_URL,
            params={"q": query, "page_size": 20, "fields": "code,product_name,brands,nutriments,quantity"},
            headers={"User-Agent": OFF_USER_AGENT}, timeout=15,
        )
    except requests.RequestException:
        raise _SearchFailed("Open Food Facts didn't respond") from None
    if not response.ok:
        raise _SearchFailed(f"Open Food Facts returned an error ({response.status_code})")
    results, seen = [], set()
    for product in response.json().get("hits", []):
        nutriments = product.get("nutriments") or {}
        values = {key: _off_value(nutriments, key) for key, *_ in NUTRIENTS}
        name = (product.get("product_name") or "").strip()
        if not name or values["calories"] is None:
            continue  # skip products without a name or calories on the label
        brands = product.get("brands")
        brand = ", ".join(brands[:2]) if isinstance(brands, list) else (brands or None)
        key = (name.lower(), (brand or "").lower(), values["calories"])
        if key in seen:
            continue  # the same product listed twice
        seen.add(key)
        results.append({
            "source": "off", "id": str(product.get("code") or len(results)), "fdc_id": None, "name": name,
            "brand": brand, "data_type": product.get("quantity"),
            "per_100g": {k: (v if v is not None else 0) for k, v in values.items()},
        })
    return results[:15]


@router.get("/foods")
def search_foods(q: str = Query(..., min_length=2, max_length=100), user: User = Depends(get_current_user)):
    """Search USDA (generic foods) and Open Food Facts (branded products) together.
    Values are per 100 g; each result says its `source`. If one database fails, the
    other's results still come back."""
    query = q.strip().lower()
    cached = _search_cache.get(query)
    if cached and time.time() - cached[0] < SEARCH_CACHE_SECONDS:
        return cached[1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_search_usda, query), pool.submit(_search_open_food_facts, query)]
    results, problems = [], []
    for future in futures:
        try:
            results.extend(future.result())
        except _SearchFailed as e:
            problems.append(e.message)
    if problems and not results:
        raise HTTPException(status_code=502, detail=f"Food search failed ({'; '.join(problems)}). Enter the values manually for now.")
    if not problems:
        _search_cache[query] = (time.time(), results)  # don't cache half results
    return results
