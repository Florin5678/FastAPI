# Nutrition widget: daily intake vs goals, filled from a food log.
#
# Goals are widget settings (they persist). The log is stored per local day in the
# widget's integrations row (config["log"] = {"YYYY-MM-DD": [entries]}), so each new
# day starts at zero; the last LOG_DAYS days are kept.
#
# Food lookup: USDA FoodData Central (free; needs a free key from
# https://fdc.nal.usda.gov/api-key-signup.html in USDA_API_KEY - the shared
# DEMO_KEY only allows ~10 lookups/hour. With a key: 1,000 requests/hour).
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Integration, User
from app.security import get_current_user
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "nutrition"
LOG_DAYS = 14
FDC_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
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
]

# Starting goals, from the user's profile: male, 27 y, 173 cm, 66 kg, 3-4 workouts/week,
# pescatarian, wants to gain weight/muscle with a balanced diet.
#   BMR (Mifflin-St Jeor) = 10*66 + 6.25*173 - 5*27 + 5 = 1,611 kcal
#   Maintenance = BMR * 1.55 = ~2,500 kcal; lean-bulk surplus +400 -> 2,900 kcal
#   Protein 2.0 g/kg = 130 g · Fat ~27% of kcal = 85 g · Carbs = the rest = 400 g
#   Fiber 14 g/1,000 kcal ~ 38 g · Sugar < 10% of kcal = 70 g · Sat. fat < 10% = 30 g
DEFAULT_GOALS = {
    "calories": 2900, "protein": 130, "carbs": 400, "fat": 85,
    "fiber": 38, "sugar": 70, "sat_fat": 30,
}
GOAL_MAX = {"calories": 10000}

_search_cache: dict[str, tuple[float, list]] = {}


def _today(tz: Optional[str]) -> date:
    try:
        return datetime.now(ZoneInfo(tz)).date() if tz else datetime.now(timezone.utc).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _log(row: Integration) -> dict:
    return dict((row.config or {}).get("log") or {})


def _totals(entries: list) -> dict:
    return {key: round(sum(e["nutrients"].get(key, 0) for e in entries), 1) for key, *_ in NUTRIENTS}


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    row = _row(db, user)
    day = _today(ctx.tz).isoformat()
    entries = _log(row).get(day, [])
    totals = _totals(entries)
    return {
        "day": day,
        "nutrients": [
            {
                "key": key, "label": label, "unit": unit, "kind": kind,
                "goal": settings[f"goal_{key}"], "actual": totals[key],
            }
            for key, label, unit, kind, _ in NUTRIENTS
        ],
        "entries": sorted(entries, key=lambda e: e["added_at"], reverse=True),
        "personal_food_key": bool(os.getenv("USDA_API_KEY")),  # else the shared, very limited DEMO_KEY
    }


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Nutrition",
    description="Daily intake vs your goals (calories, protein, carbs, fat, fiber, sugar). Log meals from the USDA food database or by hand; resets every day.",
    fetch=fetch,
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


# ---- Food log + food search routes (used by the widget's "Add food" dialog) ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


def _row(db: Session, user: User) -> Integration:
    return widget_row(db, user, WIDGET_ID)


def _save_log(row: Integration, log: dict) -> None:
    keep = sorted(log)[-LOG_DAYS:]
    row.config = {**(row.config or {}), "log": {d: log[d] for d in keep}}
    row.updated_at = datetime.utcnow()


class Nutrients(BaseModel):
    calories: float = Field(0, ge=0, le=20000)
    protein: float = Field(0, ge=0, le=2000)
    carbs: float = Field(0, ge=0, le=2000)
    fat: float = Field(0, ge=0, le=2000)
    fiber: float = Field(0, ge=0, le=2000)
    sugar: float = Field(0, ge=0, le=2000)
    sat_fat: float = Field(0, ge=0, le=2000)


class EntryIn(BaseModel):
    day: date  # the viewer's local date, so the log resets at their midnight
    name: str = Field(min_length=1, max_length=200)
    grams: Optional[float] = Field(None, gt=0, le=5000)
    nutrients: Nutrients
    source: str = Field("manual", pattern="^(manual|usda)$")
    fdc_id: Optional[int] = None


def _check_day(day: date) -> str:
    today = datetime.now(timezone.utc).date()
    # Timezones put "today" within a day of UTC; anything else is a client bug
    if abs((day - today).days) > 1:
        raise HTTPException(status_code=422, detail="Entries can only be added for today")
    return day.isoformat()


@router.post("/entries")
def add_entry(body: EntryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = _row(db, user)
    day = _check_day(body.day)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": body.name.strip(),
        "grams": body.grams,
        "source": body.source,
        "fdc_id": body.fdc_id,
        "nutrients": {k: round(v, 1) for k, v in body.nutrients.model_dump().items()},
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    log = _log(row)
    log[day] = [*log.get(day, []), entry]
    _save_log(row, log)
    db.commit()
    return entry


@router.delete("/entries/{entry_id}")
def delete_entry(
    entry_id: str,
    day: date = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = _row(db, user)
    key = _check_day(day)
    log = _log(row)
    remaining = [e for e in log.get(key, []) if e["id"] != entry_id]
    if len(remaining) == len(log.get(key, [])):
        raise HTTPException(status_code=404, detail="Entry not found")
    log[key] = remaining
    _save_log(row, log)
    db.commit()
    return {"deleted": entry_id}


def _per_100g(food: dict) -> dict:
    by_number = {str(n.get("nutrientNumber")): n.get("value") for n in food.get("foodNutrients", [])}
    values = {}
    for key, _label, _unit, _kind, numbers in NUTRIENTS:
        value = next((by_number[n] for n in numbers if by_number.get(n) is not None), 0)
        values[key] = round(float(value), 2)
    return values


@router.get("/foods")
def search_foods(q: str = Query(..., min_length=2, max_length=100), user: User = Depends(get_current_user)):
    """Search USDA FoodData Central. Values are per 100 g."""
    query = q.strip().lower()
    cached = _search_cache.get(query)
    if cached and time.time() - cached[0] < SEARCH_CACHE_SECONDS:
        return cached[1]

    params = {
        "api_key": os.getenv("USDA_API_KEY") or "DEMO_KEY",
        "query": query,
        "pageSize": 15,
        # Generic foods and dishes; "Branded" (packaged products) is mostly noise here
        "dataType": "Foundation,SR Legacy,Survey (FNDDS)",
    }
    # USDA's server rejects "+" for spaces (400); encode spaces as %20, keep , ( ) literal
    url = f"{FDC_SEARCH_URL}?{urlencode(params, quote_via=quote, safe=',()')}"
    try:
        response = requests.get(url, timeout=15)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="The food database didn't respond. Try again, or enter the values manually.")
    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Food search limit reached for this hour. Enter the values manually for now (a personal USDA key raises the limit).",
        )
    if not response.ok:
        raise HTTPException(status_code=502, detail="The food database returned an error. Enter the values manually for now.")

    results = [
        {
            "fdc_id": food["fdcId"],
            "name": food["description"],
            "data_type": food.get("dataType"),
            "per_100g": _per_100g(food),
        }
        for food in response.json().get("foods", [])
    ]
    _search_cache[query] = (time.time(), results)
    return results
