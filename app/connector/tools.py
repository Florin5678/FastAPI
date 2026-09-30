# The tools Claude gets through the connector. Reads return compact data; writes go
# through the same widget functions (and validation) as the dashboard itself, and each
# one is logged in connector_changes with how to undo it. The journal has no tools.
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from sqlalchemy.orm import Session

from app.connector import changes
from app.connector.oauth import SCOPE, DashboardOAuthProvider, public_url
from app.core.database import SessionLocal
from app.mail.routes import _email_dict
from app.models import BudgetEntry, Email, NutritionEntry, User, Workout
from app.widgets import REGISTRY, budget, google_calendar, gym, news, notes, nutrition, weather
from app.widgets.registry import WidgetContext, widget_row

TIMEZONE = os.getenv("DASHBOARD_TZ", "Europe/Copenhagen")  # the user's local time for "today"
MAX_EMAIL_BODY = 20_000

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

INSTRUCTIONS = (
    "This is the user's personal dashboard (calendar, email, notes & reminders, nutrition, gym, budget, "
    "weather, news). Times are in the user's local timezone. Every change you make is logged on the dashboard "
    "and can be undone (see list_recent_changes / undo_change). Confirm with the user before deleting things. "
    "The user's journal is private and not available. "
    "You can add, edit and delete entries for the user: food (search_foods + log_food for any food, "
    "log_saved_food for saved ones, update_food, delete_food), workouts (log_workout, update_workout, "
    "delete_workout), budget (add_budget_entry, update_budget_entry, delete_budget_entry, set_budget), "
    "reminders and notes. "
    "When the user asks to be briefed (\"brief me\", \"what's my day like\", \"morning briefing\"...), call "
    "get_briefing first and answer from it, following the instructions at its top."
)

MCP_PATH = "/mcp"

mcp = MCPServer(
    name="dashboard",
    title="My Dashboard",
    instructions=INSTRUCTIONS,
    auth_server_provider=DashboardOAuthProvider(),
    auth=AuthSettings(
        issuer_url=public_url(),
        resource_server_url=f"{public_url()}{MCP_PATH}",
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[SCOPE],
        validate_token_resource=False,  # tokens are only ever issued for this one server
    ),
)


# ---- Helpers ----

class _Call:
    """DB session + the signed-in user for one tool call."""

    def __enter__(self) -> "_Call":
        token = get_access_token()
        if token is None or not token.subject:
            raise ToolError("Not signed in to the dashboard")
        self.client_id = token.client_id
        self.db: Session = SessionLocal()
        self.user = self.db.get(User, int(token.subject))
        if self.user is None:
            self.db.close()
            raise ToolError("Unknown user")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.db.close()
        # Turn expected failures into messages Claude can read (anything else is a crash)
        if isinstance(exc, HTTPException):
            raise ToolError(str(exc.detail)) from exc
        if isinstance(exc, ValidationError):
            problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise ToolError(f"Invalid input: {problems}") from exc

    def record(self, tool: str, summary: str, undo: Optional[dict]) -> int:
        return changes.record(self.db, self.user, self.client_id, tool, summary, undo).id


def _run(fn, *args, **kwargs):
    """Call a dashboard route function, turning its HTTP errors into tool errors."""
    try:
        return fn(*args, **kwargs)
    except HTTPException as e:
        raise ToolError(str(e.detail)) from e


def _zone() -> ZoneInfo:
    return ZoneInfo(TIMEZONE)


def _today() -> date:
    return datetime.now(_zone()).date()


def _ctx() -> WidgetContext:
    midnight = datetime.combine(_today(), time.min, tzinfo=_zone())
    return WidgetContext(since=midnight.astimezone(timezone.utc).replace(tzinfo=None), tz=TIMEZONE)


def _widget(call: _Call, widget_id: str, **overrides: Any) -> dict:
    definition = REGISTRY[widget_id]
    row = _run(widget_row, call.db, call.user, widget_id)
    settings = {**definition.settings_for(row), **overrides}
    return _run(definition.fetch, call.db, call.user, settings, _ctx())


def _day(value: Optional[str]) -> date:
    if not value:
        return _today()
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ToolError("Use a date like 2026-09-28") from e


def _month(value: Optional[str]) -> str:
    return value or _today().isoformat()[:7]


# ---- Read tools ----

@mcp.tool(annotations=READ)
def get_briefing() -> str:
    """The user's daily briefing from their dashboard's Assistant widget: their own instructions for how to
    brief them, then today's email, calendar, weather, nutrition, reminders, news, gym. Call this whenever the
    user says "brief me" or asks about their day, and answer following the instructions at the top."""
    with _Call() as call:
        data = REGISTRY["assistant"].fetch(call.db, call.user, {}, _ctx())
        when = datetime.now(_zone()).strftime("%A %d %B, %H:%M")
        prompt = data["prompt"]
        sections = "\n\n".join(f"## {s['name']}\n{s['text']}" for s in data["sections"]) or "Nothing on the dashboard yet."
        # Same order as the prompt the widget copies to claude.ai: instructions, briefing, question
        return (
            f"# How to brief me\n{prompt['instructions'].replace('{when}', when)}\n\n"
            f"# My dashboard briefing\n{sections}\n\n"
            f"# If I just said \"brief me\" (or similar), answer this\n{prompt['default_question']}"
        )


@mcp.tool(annotations=READ)
def get_calendar(days: int = 7) -> dict:
    """Google Calendar events from today for `days` days (1-31), with local start/end times and durations."""
    with _Call() as call:
        data = _widget(call, "calendar", days=max(1, min(days, 31)))
        if data.get("needs_setup"):
            return {"error": "The calendar isn't connected on the dashboard yet"}
        return {"events": [
            {"when": google_calendar._when(e), "title": e["title"], "location": e["location"], "calendar": e["calendar"],
             "all_day": e["all_day"], "start": e["start"], "end": e["end"]}
            for e in data["events"]
        ]}


@mcp.tool(annotations=READ)
def list_emails(days: int = 2, category: Optional[str] = None, limit: int = 25) -> dict:
    """Recent emails (newest first) from the last `days` days: id, sender, subject, time, category and a
    short summary/snippet. Optionally filter by category (e.g. school, finance, personal, notification)."""
    with _Call() as call:
        since = datetime.utcnow() - timedelta(days=max(1, min(days, 30)))
        query = call.db.query(Email).filter(Email.user_id == call.user.id, Email.timestamp >= since)
        if category:
            query = query.filter(Email.category == category.lower())
        rows = query.order_by(Email.timestamp.desc()).limit(max(1, min(limit, 100))).all()
        return {"emails": [
            {"id": e.id, "from": e.sender, "subject": e.subject, "category": e.category,
             "time": e.timestamp.replace(tzinfo=timezone.utc).astimezone(_zone()).isoformat(timespec="minutes") if e.timestamp else None,
             "summary": e.summary or e.snippet}
            for e in rows
        ]}


@mcp.tool(annotations=READ)
def get_email(email_id: int) -> dict:
    """One email with its full text (use an id from list_emails)."""
    with _Call() as call:
        row = call.db.query(Email).filter(Email.id == email_id, Email.user_id == call.user.id).first()
        if row is None:
            raise ToolError("Email not found")
        data = _email_dict(row, include_body=True)
        if data.get("full_body") and len(data["full_body"]) > MAX_EMAIL_BODY:
            data["full_body"] = data["full_body"][:MAX_EMAIL_BODY] + "\n[... cut off]"
        return data


@mcp.tool(annotations=READ)
def get_notes_and_reminders() -> dict:
    """Open reminders (with due times), recently completed reminders, and notes (pinned first)."""
    with _Call() as call:
        return _widget(call, "notes")


@mcp.tool(annotations=READ)
def get_nutrition(day: Optional[str] = None) -> dict:
    """One day's food log with totals vs the user's goals (calories, protein, carbs, fat, fiber, sugar,
    saturated fat). `day` like 2026-09-28; default today."""
    with _Call() as call:
        _run(widget_row, call.db, call.user, nutrition.WIDGET_ID)
        return nutrition.day_summary(call.db, call.user, _day(day))


@mcp.tool(annotations=READ)
def get_nutrition_history(days: int = 14) -> dict:
    """Daily nutrition totals for the last `days` days (1-90), newest first."""
    with _Call() as call:
        return _run(nutrition.history, end=_today(), days=max(1, min(days, 90)), user=call.user, db=call.db)


@mcp.tool(annotations=READ)
def get_workouts(month: Optional[str] = None) -> dict:
    """Workouts: this week's progress vs goals, plus every workout in `month` (like 2026-09; default this
    month) with totals per type. Also lists the workout types that can be logged."""
    with _Call() as call:
        week = _widget(call, "gym")
        return {
            "this_week": {k: week[k] for k in ("week_start", "goal_workouts", "goal_minutes", "workouts_done", "minutes_done", "streak_weeks")},
            "workout_types": week["kinds"],
            "month": _run(gym.month_report, _month(month), user=call.user, db=call.db),
        }


@mcp.tool(annotations=READ)
def get_budget(month: Optional[str] = None) -> dict:
    """The budget log for `month` (like 2026-09; default this month): every entry (id, category path,
    amount), income and spending totals, the previous month, monthly budgets per spending category and
    the last 12 months. Category "Income" is income; everything else (usually under "Expenses") is spending."""
    with _Call() as call:
        return _run(budget.month_report, _month(month), user=call.user, db=call.db)


@mcp.tool(annotations=READ)
def get_weather(city: Optional[str] = None) -> str:
    """Current weather and today's forecast. `city`: one of the dashboard's cities (default: the widget's)."""
    with _Call() as call:
        overrides = {"city": city} if city in weather.CITIES else {}
        return weather.brief(_widget(call, "weather", **overrides))


@mcp.tool(annotations=READ)
def get_news(topic: Optional[str] = None, limit: int = 10) -> dict:
    """Latest headlines (title, source, link). `topic`: one of the dashboard's news topics (default: the widget's)."""
    with _Call() as call:
        overrides: dict[str, Any] = {"max_items": max(1, min(limit, 30))}
        if topic in news.TOPIC_CHOICES:
            overrides["topic"] = topic
        return _widget(call, "news", **overrides)


# ---- Reminders & notes ----

def _find_item(call: _Call, kind: str, item_id: str) -> dict:
    row = _run(widget_row, call.db, call.user, notes.WIDGET_ID)
    item = next((i for i in notes._items(row, kind) if i["id"] == item_id), None)
    if item is None:
        raise ToolError(f"{kind[:-1].capitalize()} not found")
    return item


def _due(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise ToolError("Use a due time like 2026-10-02T09:00 (local time) or with an offset") from e
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_zone())


@mcp.tool(annotations=WRITE)
def add_reminder(text: str, due: Optional[str] = None) -> dict:
    """Notes & reminders: add a NEW reminder. `due`: optional local date-time like 2026-10-02T09:00."""
    with _Call() as call:
        item = _run(notes.add_reminder, notes.ReminderIn(text=text, due=_due(due)), user=call.user, db=call.db)
        call.record("add_reminder", f'Added reminder "{item["text"]}"', {"action": "delete_reminder", "args": {"id": item["id"]}})
        return item


@mcp.tool(annotations=EDIT)
def update_reminder(reminder_id: str, text: Optional[str] = None, due: Optional[str] = None,
                    clear_due: bool = False, done: Optional[bool] = None) -> dict:
    """Change a reminder: its text, due time (or clear_due=true to remove it), or mark it done/not done."""
    with _Call() as call:
        before = _find_item(call, "reminders", reminder_id)
        fields: dict[str, Any] = {}
        if text is not None:
            fields["text"] = text
        if due is not None or clear_due:
            fields["due"] = None if clear_due else _due(due)
        if done is not None:
            fields["done"] = done
        item = _run(notes.update_reminder, reminder_id, notes.ReminderPatch(**fields), user=call.user, db=call.db)
        what = "Completed" if done else "Reopened" if done is False else "Changed"
        call.record("update_reminder", f'{what} reminder "{item["text"]}"', {"action": "restore_reminder", "args": {"item": before}})
        return item


@mcp.tool(annotations=DELETE)
def delete_reminder(reminder_id: str) -> str:
    """Delete a reminder (can be undone from the dashboard)."""
    with _Call() as call:
        before = _find_item(call, "reminders", reminder_id)
        _run(notes.delete_reminder, reminder_id, user=call.user, db=call.db)
        call.record("delete_reminder", f'Deleted reminder "{before["text"]}"', {"action": "restore_reminder", "args": {"item": before}})
        return "Deleted"


@mcp.tool(annotations=WRITE)
def add_note(text: str) -> dict:
    """Notes & reminders: add a NEW note."""
    with _Call() as call:
        item = _run(notes.add_note, notes.NoteIn(text=text), user=call.user, db=call.db)
        call.record("add_note", f'Added note "{item["text"][:80]}"', {"action": "delete_note", "args": {"id": item["id"]}})
        return item


@mcp.tool(annotations=EDIT)
def update_note(note_id: str, text: Optional[str] = None, pinned: Optional[bool] = None) -> dict:
    """Change a note's text or pin/unpin it."""
    with _Call() as call:
        before = _find_item(call, "notes", note_id)
        fields = {k: v for k, v in (("text", text), ("pinned", pinned)) if v is not None}
        item = _run(notes.update_note, note_id, notes.NotePatch(**fields), user=call.user, db=call.db)
        call.record("update_note", f'Changed note "{item["text"][:80]}"', {"action": "restore_note", "args": {"item": before}})
        return item


@mcp.tool(annotations=DELETE)
def delete_note(note_id: str) -> str:
    """Delete a note (can be undone from the dashboard)."""
    with _Call() as call:
        before = _find_item(call, "notes", note_id)
        _run(notes.delete_note, note_id, user=call.user, db=call.db)
        call.record("delete_note", f'Deleted note "{before["text"][:80]}"', {"action": "restore_note", "args": {"item": before}})
        return "Deleted"


# ---- Nutrition ----

@mcp.tool(annotations=READ)
def search_foods(query: str) -> dict:
    """Nutrition: look up calories and macros per 100 g for a food: generic foods (USDA) and branded products (Open Food Facts),
    the same search as the dashboard's Add food dialog. Use it before log_food when the user says what
    they ate, unless it's one of their saved foods (list_saved_foods / log_saved_food)."""
    with _Call() as call:
        results = _run(nutrition.search_foods, q=query.strip()[:100], user=call.user)
        return {"results": [
            {"name": f"{r['name']} ({r['brand']})" if r["brand"] else r["name"], "source": r["source"], "per_100g": r["per_100g"]}
            for r in results[:10]
        ]}


@mcp.tool(annotations=WRITE)
def log_food(name: str, calories: float, protein: float = 0, carbs: float = 0, fat: float = 0, fiber: float = 0,
             sugar: float = 0, sat_fat: float = 0, grams: Optional[float] = None, day: Optional[str] = None,
             values_per_100g: bool = False) -> dict:
    """Nutrition: add a NEW entry to the food log (any meal, snack or drink, not only saved foods) for a day
    (default today). Nutrients are for the amount eaten; or, with
    values_per_100g=true (e.g. straight from search_foods), per 100 g and scaled to `grams` (then required).
    If the user didn't say the amount, estimate a typical portion and tell them."""
    with _Call() as call:
        values = {"calories": calories, "protein": protein, "carbs": carbs, "fat": fat, "fiber": fiber, "sugar": sugar, "sat_fat": sat_fat}
        if values_per_100g:
            if not grams:
                raise ToolError("Give `grams` (the amount eaten) when the values are per 100 g")
            values = {k: round(v * grams / 100, 1) for k, v in values.items()}
        calories = values["calories"]
        entry = _run(nutrition.add_entry, nutrition.EntryIn(
            day=_day(day), name=name, grams=grams, nutrients=nutrition.Nutrients(**values),
        ), user=call.user, db=call.db)
        call.record("log_food", f'Logged {entry["name"]} ({round(calories)} kcal) on {entry["day"]}', {"action": "delete_food", "args": {"id": entry["id"]}})
        return entry


@mcp.tool(annotations=DELETE)
def delete_food(entry_id: int) -> str:
    """Nutrition: remove an entry from the food log (ids from get_nutrition; can be undone)."""
    with _Call() as call:
        row = call.db.query(NutritionEntry).filter(NutritionEntry.id == entry_id, NutritionEntry.user_id == call.user.id).first()
        if row is None:
            raise ToolError("Entry not found")
        before = nutrition._entry_dict(row)
        _run(nutrition.delete_entry, entry_id, user=call.user, db=call.db)
        call.record("delete_food", f'Removed {before["name"]} from {before["day"]}', {"action": "readd_food", "args": {"entry": before}})
        return "Deleted"


NUTRIENT_KEYS = ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sat_fat")


@mcp.tool(annotations=EDIT)
def update_food(entry_id: int, grams: Optional[float] = None, name: Optional[str] = None, day: Optional[str] = None,
                calories: Optional[float] = None, protein: Optional[float] = None, carbs: Optional[float] = None,
                fat: Optional[float] = None, fiber: Optional[float] = None, sugar: Optional[float] = None,
                sat_fat: Optional[float] = None) -> dict:
    """Nutrition: edit an existing food log entry (ids from get_nutrition). Change only `grams` to rescale its values to the new
    amount; or give new nutrient values for the amount eaten (others stay as they are); or rename it, or
    move it to another `day` (like 2026-09-28)."""
    with _Call() as call:
        row = call.db.query(NutritionEntry).filter(NutritionEntry.id == entry_id, NutritionEntry.user_id == call.user.id).first()
        if row is None:
            raise ToolError("Entry not found")
        before = nutrition._entry_dict(row)
        given = {k: v for k, v in zip(NUTRIENT_KEYS, (calories, protein, carbs, fat, fiber, sugar, sat_fat), strict=True) if v is not None}
        patch: dict[str, Any] = {}
        if given:
            patch["nutrients"] = nutrition.Nutrients(**{**before["nutrients"], **given})
        if grams is not None:
            patch["grams"] = grams
        if name is not None:
            patch["name"] = name
        if day is not None:
            patch["day"] = _day(day)
        entry = _run(nutrition.update_entry, entry_id, nutrition.EntryPatch(**patch), user=call.user, db=call.db)
        call.record("update_food", f'Changed {before["name"]} ({before["day"]}): {round(before["nutrients"]["calories"])} → {round(entry["nutrients"]["calories"])} kcal',
                    {"action": "restore_food", "args": {"id": entry_id, "entry": before}})
        return entry


@mcp.tool(annotations=READ)
def list_saved_foods() -> dict:
    """The user's saved foods ("My foods"), most recently used first, with values per 100 g and the usual
    amount in grams. Use log_saved_food to log one again."""
    with _Call() as call:
        return _run(nutrition.list_saved_foods, user=call.user, db=call.db)


@mcp.tool(annotations=WRITE)
def log_saved_food(food: str, grams: Optional[float] = None, day: Optional[str] = None) -> dict:
    """Nutrition: add a saved food ("My foods") to the food log again. `food`: its name (or id) from list_saved_foods; `grams`:
    the amount eaten (default: the amount used last time, else 100 g); `day` default today."""
    with _Call() as call:
        foods = _run(nutrition.list_saved_foods, user=call.user, db=call.db)["foods"]
        wanted = food.strip().lower()
        match = [f for f in foods if f["id"] == food or f["name"].lower() == wanted] or [f for f in foods if wanted in f["name"].lower()]
        if len(match) != 1:
            names = ", ".join(f["name"] for f in (match or foods)[:15])
            raise ToolError(f"{'Several' if match else 'No'} saved foods match '{food}'. Saved foods: {names or 'none yet'}")
        saved = match[0]
        amount = grams or saved.get("grams") or 100
        nutrients = {k: round(saved["per_100g"].get(k, 0) * amount / 100, 1) for k in NUTRIENT_KEYS}
        entry = _run(nutrition.add_entry, nutrition.EntryIn(
            day=_day(day), name=saved["name"], grams=amount, nutrients=nutrition.Nutrients(**nutrients), saved_food_id=saved["id"],
        ), user=call.user, db=call.db)
        call.record("log_food", f'Logged {entry["name"]}, {round(amount)} g ({round(nutrients["calories"])} kcal) on {entry["day"]}',
                    {"action": "delete_food", "args": {"id": entry["id"]}})
        return entry


# ---- Gym ----

@mcp.tool(annotations=WRITE)
def log_workout(kind: str, minutes: int, day: Optional[str] = None, note: Optional[str] = None) -> dict:
    """Gym: add a NEW workout entry. `kind` must be one of the workout types from get_workouts; `day` default today."""
    with _Call() as call:
        workout = _run(gym.log_workout, gym.WorkoutIn(day=_day(day), kind=kind, minutes=minutes, note=note), user=call.user, db=call.db)
        call.record("log_workout", f'Logged {workout["kind"]} workout, {workout["minutes"]} min on {workout["day"]}',
                    {"action": "delete_workout", "args": {"id": workout["id"]}})
        return workout


@mcp.tool(annotations=EDIT)
def update_workout(workout_id: int, kind: Optional[str] = None, minutes: Optional[int] = None,
                   day: Optional[str] = None, note: Optional[str] = None) -> dict:
    """Gym: edit an existing workout entry (ids from get_workouts): its type, minutes, day (like 2026-09-28) or note
    ("" clears the note). Only the fields given change."""
    with _Call() as call:
        row = call.db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == call.user.id).first()
        if row is None:
            raise ToolError("Workout not found")
        before = {"day": row.day.isoformat(), "kind": row.kind, "minutes": row.minutes, "note": row.note}
        workout = _run(gym.update_workout, workout_id, gym.WorkoutPatch(
            kind=kind, minutes=minutes, day=_day(day) if day else None, note=note,
        ), user=call.user, db=call.db)
        call.record("update_workout", f'Changed {before["kind"]} workout ({before["day"]}, {before["minutes"]} min) → '
                    f'{workout["kind"]}, {workout["day"]}, {workout["minutes"]} min',
                    {"action": "restore_workout", "args": {"id": workout_id, "workout": before}})
        return workout


@mcp.tool(annotations=DELETE)
def delete_workout(workout_id: int) -> str:
    """Gym: delete a workout entry (ids from get_workouts; can be undone)."""
    with _Call() as call:
        row = call.db.query(Workout).filter(Workout.id == workout_id, Workout.user_id == call.user.id).first()
        if row is None:
            raise ToolError("Workout not found")
        before = {"day": row.day.isoformat(), "kind": row.kind, "minutes": row.minutes, "note": row.note}
        _run(gym.delete_workout, workout_id, user=call.user, db=call.db)
        call.record("delete_workout", f'Deleted {before["kind"]} workout from {before["day"]}', {"action": "readd_workout", "args": {"workout": before}})
        return "Deleted"


# ---- Budget ----

def _budget_entry(call: _Call, entry_id: int) -> dict:
    row = call.db.query(BudgetEntry).filter(BudgetEntry.id == entry_id, BudgetEntry.user_id == call.user.id).first()
    if row is None:
        raise ToolError("Budget entry not found")
    return budget._entry_dict(row)


def _path_text(path: list[str]) -> str:
    return " › ".join(path)


@mcp.tool(annotations=WRITE)
def add_budget_entry(path: list[str], amount: float, month: Optional[str] = None) -> dict:
    """Budget: add a NEW income or expense entry. `path`: 1-4 category levels, e.g. ["Expenses", "Groceries", "Netto"]
    or ["Income", "SU"]. `amount` is positive, in the user's currency. `month` like 2026-09 (default this month)."""
    with _Call() as call:
        entry = _run(budget.add_entry, budget.EntryIn(month=_month(month), path=path, amount=amount), user=call.user, db=call.db)
        call.record("add_budget_entry", f'Added {_path_text(entry["path"])}: {entry["amount"]:.2f} ({entry["month"]})',
                    {"action": "delete_budget_entry", "args": {"id": entry["id"]}})
        return entry


@mcp.tool(annotations=EDIT)
def update_budget_entry(entry_id: int, amount: Optional[float] = None, path: Optional[list[str]] = None,
                        month: Optional[str] = None) -> dict:
    """Budget: edit an existing entry's amount, category path or month (ids from get_budget)."""
    with _Call() as call:
        before = _budget_entry(call, entry_id)
        fields = {k: v for k, v in (("amount", amount), ("path", path), ("month", month)) if v is not None}
        entry = _run(budget.update_entry, entry_id, budget.EntryPatch(**fields), user=call.user, db=call.db)
        call.record("update_budget_entry", f'Changed {_path_text(before["path"])} ({before["month"]}): {before["amount"]:.2f} → {entry["amount"]:.2f}',
                    {"action": "update_budget_entry", "args": {"id": entry_id, "entry": {k: before[k] for k in ("month", "path", "amount")}}})
        return entry


@mcp.tool(annotations=DELETE)
def delete_budget_entry(entry_id: int) -> str:
    """Budget: delete an entry (can be undone)."""
    with _Call() as call:
        before = _budget_entry(call, entry_id)
        _run(budget.delete_entry, entry_id, user=call.user, db=call.db)
        call.record("delete_budget_entry", f'Deleted {_path_text(before["path"])}: {before["amount"]:.2f} ({before["month"]})',
                    {"action": "readd_budget_entry", "args": {"entry": {k: before[k] for k in ("month", "path", "amount")}}})
        return "Deleted"


@mcp.tool(annotations=EDIT)
def set_budget(category: str, amount: Optional[float] = None) -> dict:
    """Budget: set the monthly budget for a spending category (the level under "Expenses", e.g. "Groceries").
    Leave `amount` empty to remove that budget."""
    with _Call() as call:
        previous = budget._budgets(call.db, call.user)
        updated = {**previous, category: amount} if amount else {k: v for k, v in previous.items() if k != category}
        result = _run(budget.set_budgets, budget.BudgetsIn(budgets=updated), user=call.user, db=call.db)
        summary = f"Set the {category} budget to {amount:.0f}" if amount else f"Removed the {category} budget"
        call.record("set_budget", summary, {"action": "set_budgets", "args": {"budgets": previous}})
        return result


# ---- Change log ----

@mcp.tool(annotations=READ)
def list_recent_changes(limit: int = 10) -> dict:
    """Changes made through this connector, newest first (id, summary, time, whether it can be undone)."""
    with _Call() as call:
        return {"changes": changes.recent(call.db, call.user, max(1, min(limit, 50)))}


@mcp.tool(annotations=EDIT)
def undo_change(change_id: int) -> dict:
    """Undo a change made through this connector (ids from list_recent_changes)."""
    with _Call() as call:
        return _run(changes.undo, call.db, call.user, change_id)
