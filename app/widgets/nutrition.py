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
    "fiber": "fiber_100g", "sugar": "sugars_100g", "sat_fat": "saturated-fat_100g",
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
    "fiber": 38, "sugar": 70, "sat_fat": 30,
}
GOAL_MAX = {"calories": 10000}
MAX_SAVED_FOODS = 300

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
    return day_summary(db, user, local_today(ctx.tz))


def brief(data: dict, limit: int | None = None) -> str:
    parts = [f"{n['label']} {round(n['actual'])}/{round(n['goal'])} {n['unit']}" + (" (limit)" if n["kind"] == "limit" else "")
             for n in data["nutrients"]]
    foods = ", ".join(e["name"] for e in data["entries"][:limit or 8]) or "nothing logged yet"
    return f"Today's intake vs goals: {'; '.join(parts)}. Foods: {foods}."


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Nutrition",
    description="Daily intake vs your goals (calories, protein, carbs, fat, fiber, sugar). Log meals from the USDA food database or by hand; every day is kept in your history.",
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


def _per_100g(food: dict) -> dict:
    by_number = {str(n.get("nutrientNumber")): n.get("value") for n in food.get("foodNutrients", [])}
    values = {}
    for key, _label, _unit, _kind, numbers in NUTRIENTS:
        value = next((by_number[n] for n in numbers if by_number.get(n) is not None), 0)
        values[key] = round(float(value), 2)
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
