# The tools Claude gets through the connector. Reads return compact data; writes go
# through the same widget functions (and validation) as the dashboard itself, and each
# one is logged in connector_changes with how to undo it. The journal has no tools.
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
from app.core.timeutil import DASHBOARD_TZ
from app.mail.routes import _email_dict
from app.models import BudgetEntry, Email, NutritionEntry, User, Workout
from app.widgets import REGISTRY, assistant, budget, google_calendar, gym, news, notes, nutrition, weather, weight
from app.widgets.registry import WidgetContext, widget_row

TIMEZONE = DASHBOARD_TZ  # the user's local time for "today"
MAX_EMAIL_BODY = 20_000

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

MEAL_GUIDE = (
    "When the user asks for meal suggestions, a meal plan or what to eat or cook (also when a briefing section "
    "asks for meal suggestions), call plan_meals: it returns the meals still ahead today, the free time in their "
    "calendar, their goals and what they've eaten, the last week's pattern and their pantry, plus how to plan. "
    "When they say they used up, finished or bought food, update the pantry and the shopping list."
)
PLAN_GUIDE = (
    "Plan ONLY the meals in upcoming_meals (it is local_time now: don't suggest meals that are already over, e.g. "
    "no breakfast in the evening; if the list is empty, at most suggest a light snack).\n"
    "Be realistic about time. For every meal estimate the total time it takes: shopping if something must be "
    "bought, prepping ingredients, cooking, cooling/resting where it applies, and eating (about 15-30 min). Fit "
    "each meal into schedule.free_time (between calendar events; travel to and from events also takes time), "
    "give it a start time, and space meals sensibly: about 3-4 hours between main meals, at least 1.5-2 hours "
    "after last_logged_at for the next main meal, nothing heavy right before bed. On a busy day plan fewer and "
    "quicker meals (no-cook, one-pan, leftovers, something to take along) or cook once for two meals rather than "
    "proposing several elaborate ones back to back; if there isn't time for a meal, say so and suggest a snack "
    "that can be eaten on the go. If `schedule` is null the calendar isn't connected: ask or assume an ordinary day.\n"
    "Split what's `remaining` of today's goals across the meals you plan (more at main meals than snacks) and stay "
    "within what's left of the limits (sugar, saturated fat). Build the meals from the pantry first. Items with "
    "priority=true (starred: close to expiring or already opened) come first: include as many of them as you "
    "sensibly can, but they are a priority, not a must, so leave out the ones that don't fit well. Then prefer "
    "items with the fewest days_left. Keep things to buy to a minimum (check shopping_list: they may already plan "
    "to buy them). Lean towards the nutrients in last_7_days.often_short, go easy on often_over_limit, and avoid "
    "repeating recent_foods. If `weight` shows a goal and the trend isn't moving towards it, adjust portions (e.g. "
    "more calories when a weight-gain goal stalls). Respect the user's diet and preferences.\n"
    "For each meal give: the start time and total time (prep / cook / eat), a name, the ingredients with rough "
    "amounts (mark pantry items, ★ for priority ones), approximate kcal / protein / carbs / fat / fiber, and a "
    "short method. Finish with how the plan covers today's remaining goals, which priority items it uses (and any "
    "it couldn't), and what to buy; offer to add those to the shopping list (add_shopping_items), to log meals "
    "once eaten (log_food) and to update the pantry."
)
RECEIPT_GUIDE = (
    "From a shopping receipt or photo: add each food item with a clear, everyday name (\"Oat milk\", not "
    "\"OATLY HAVRE 1L\"), the amount when it's shown, and leave out non-food lines, deposits and bags. Items on the "
    "shopping list with the same name are removed from it automatically; then look at shopping_list_now for "
    "near matches (e.g. \"Milk\" when they bought \"Oat milk\") and remove those with delete_shopping_items."
)

INSTRUCTIONS = (
    "This is the user's personal dashboard (calendar, email, reminders, nutrition, gym, budget, "
    "weather, news). Times are in the user's local timezone. Every change you make is logged on the dashboard "
    "and can be undone (see list_recent_changes / undo_change). Confirm with the user before deleting things. "
    "The user's journal is private and not available. "
    "You can add, edit and delete entries for the user: food (search_foods + log_food for any food, "
    "log_saved_food for saved ones, update_food, delete_food), workouts (log_workout, update_workout, "
    "delete_workout), budget (add_budget_entry, update_budget_entry, delete_budget_entry, set_budget; expenses "
    "use a fixed list of sub-categories, see add_budget_entry), "
    "and reminders (add_reminder, update_reminder, delete_reminder; they can repeat daily, weekly or monthly). "
    "For meal suggestions use plan_meals. They keep a pantry and a shopping list (get_pantry returns both; "
    "add_pantry_items / add_shopping_items take one or many items in one call; move_to_pantry when bought, "
    "move_to_shopping_list when used up; set_pantry_priority stars items to use first). "
    "You can also add, change and delete Google Calendar events (add_calendar_event, update_calendar_event, "
    "delete_calendar_event); confirm before deleting events. "
    + MEAL_GUIDE + " "
    "When the user asks to be briefed (\"brief me\", \"what's my day like\", \"morning briefing\"...), call "
    "get_briefing first and answer from it, following its \"How to answer\" part."
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
    """The user's daily briefing from their dashboard's Assistant widget: today's facts (date, week, moon,
    holidays), email, calendar, weather, nutrition, reminders, news, gym, then the user's own "How to answer"
    sections and rules, and their question. Call this whenever the user says "brief me" or asks about their
    day, and answer exactly as its "How to answer" part says."""
    with _Call() as call:
        # The same prompt as "Copy briefing": opening, briefing, how to answer, question
        data = REGISTRY["assistant"].fetch(call.db, call.user, {}, _ctx())
        return assistant.fill_when(data["prompt"], TIMEZONE)


@mcp.tool(annotations=READ)
def get_calendar(days: int = 7) -> dict:
    """Google Calendar events from today for `days` days (1-31), with local start/end times and durations, each
    with its `id` and `calendar_id` (needed to change or delete it), plus the user's calendars (`calendars`:
    id, name, primary, can_edit)."""
    with _Call() as call:
        data = _widget(call, "calendar", days=max(1, min(days, 31)))
        if data.get("needs_setup"):
            return {"error": "The calendar isn't connected on the dashboard yet"}
        return {"events": [
            {"id": e["id"], "calendar_id": e["calendar_id"], "when": google_calendar._when(e), "title": e["title"],
             "location": e["location"], "calendar": e["calendar"], "all_day": e["all_day"], "start": e["start"], "end": e["end"]}
            for e in data["events"]
        ], "calendars": data.get("calendar_list", [])}


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
def get_reminders() -> dict:
    """Open reminders (soonest due first, with due times and how they repeat) and recently completed ones."""
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
            "this_week": {k: week[k] for k in ("week_start", "goal_active_days", "active_days", "goal_minutes", "workouts_done", "minutes_done", "streak_weeks")},
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


# ---- Calendar (changes) ----

EVENT_FIELDS = ("summary", "location", "description", "start", "end")


def _event_snapshot(event: dict) -> dict:
    return {k: event[k] for k in EVENT_FIELDS if k in event}


def _event_out(event: dict) -> dict:
    start, end = event.get("start") or {}, event.get("end") or {}
    return {"id": event.get("id"), "title": event.get("summary"), "start": start.get("dateTime") or start.get("date"),
            "end": end.get("dateTime") or end.get("date"), "location": event.get("location"), "link": event.get("htmlLink")}


@mcp.tool(annotations=WRITE)
def add_calendar_event(title: str, start: str, end: Optional[str] = None, all_day: bool = False,
                       location: Optional[str] = None, description: Optional[str] = None,
                       calendar_id: str = "primary") -> dict:
    """Calendar: add an event to the user's Google Calendar. Timed: `start`/`end` local times like
    2026-10-07T18:00 (end defaults to 1 hour later). All-day: all_day=true with dates like 2026-10-07 (end =
    last day, inclusive). `calendar_id`: from get_calendar's calendars (default: their main calendar). Undoable."""
    with _Call() as call:
        body = google_calendar.event_body(title, start, end, all_day, TIMEZONE, location, description)
        event = _run(google_calendar.create_event, call.db, call.user, calendar_id, body)
        call.record("add_calendar_event", f'Added "{title}" to the calendar ({start})',
                    {"action": "delete_calendar_event", "args": {"calendar_id": calendar_id, "event_id": event["id"]}})
        return _event_out(event)


@mcp.tool(annotations=EDIT)
def update_calendar_event(event_id: str, calendar_id: str = "primary", title: Optional[str] = None,
                          start: Optional[str] = None, end: Optional[str] = None, all_day: Optional[bool] = None,
                          location: Optional[str] = None, description: Optional[str] = None) -> dict:
    """Calendar: change an event (ids and calendar_id from get_calendar): its title, time (`start`/`end` as in
    add_calendar_event; give both when moving it), location or description. Only the fields given change. For
    a repeating event this changes just that occurrence. Undoable."""
    with _Call() as call:
        before = _run(google_calendar.get_event, call.db, call.user, calendar_id, event_id)
        is_all_day = all_day if all_day is not None else "date" in (before.get("start") or {})
        body = google_calendar.event_body(title, start, end, is_all_day, TIMEZONE, location, description)
        event = _run(google_calendar.update_event, call.db, call.user, calendar_id, event_id, body)
        call.record("update_calendar_event", f'Changed "{before.get("summary")}" in the calendar',
                    {"action": "restore_calendar_event", "args": {"calendar_id": calendar_id, "event_id": event_id,
                                                                  "body": _event_snapshot(before)}})
        return _event_out(event)


@mcp.tool(annotations=DELETE)
def delete_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
    """Calendar: delete an event (ids and calendar_id from get_calendar). Confirm with the user first. For a
    repeating event this deletes just that occurrence. Can be undone (it comes back as a new event)."""
    with _Call() as call:
        before = _run(google_calendar.get_event, call.db, call.user, calendar_id, event_id)
        _run(google_calendar.delete_event, call.db, call.user, calendar_id, event_id)
        call.record("delete_calendar_event", f'Deleted "{before.get("summary")}" from the calendar',
                    {"action": "recreate_calendar_event", "args": {"calendar_id": calendar_id, "body": _event_snapshot(before)}})
        return "Deleted"


# ---- Reminders ----

def _find_reminder(call: _Call, reminder_id: str) -> dict:
    row = _run(widget_row, call.db, call.user, notes.WIDGET_ID)
    item = next((i for i in notes._items(row) if i["id"] == reminder_id), None)
    if item is None:
        raise ToolError("Reminder not found")
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
def add_reminder(text: str, due: Optional[str] = None, repeat: Optional[notes.Repeat] = None) -> dict:
    """Reminders: add a NEW reminder. `due`: optional local date-time like 2026-10-02T09:00. `repeat`:
    "daily", "weekly" or "monthly" (monthly = on the due date's day of the month); needs a due time."""
    with _Call() as call:
        item = _run(notes.add_reminder, notes.ReminderIn(text=text, due=_due(due), repeat=repeat, tz=TIMEZONE),
                    user=call.user, db=call.db)
        call.record("add_reminder", f'Added reminder "{item["text"]}"', {"action": "delete_reminder", "args": {"id": item["id"]}})
        return item


@mcp.tool(annotations=EDIT)
def update_reminder(reminder_id: str, text: Optional[str] = None, due: Optional[str] = None,
                    clear_due: bool = False, repeat: Optional[str] = None, done: Optional[bool] = None) -> dict:
    """Reminders: change a reminder's text, due time (or clear_due=true to remove it), `repeat` ("daily",
    "weekly", "monthly", or "none" to stop repeating), or mark it done/not done. Marking a repeating
    reminder done moves it to its next occurrence."""
    with _Call() as call:
        before = _find_reminder(call, reminder_id)
        fields: dict[str, Any] = {"tz": TIMEZONE}
        if text is not None:
            fields["text"] = text
        if due is not None or clear_due:
            fields["due"] = None if clear_due else _due(due)
        if repeat is not None:
            fields["repeat"] = None if repeat == "none" else repeat
        if done is not None:
            fields["done"] = done
        item = _run(notes.update_reminder, reminder_id, notes.ReminderPatch(**fields), user=call.user, db=call.db)
        what = ("Moved to the next time" if before.get("repeat") else "Completed") if done else "Reopened" if done is False else "Changed"
        call.record("update_reminder", f'{what} reminder "{item["text"]}"', {"action": "restore_reminder", "args": {"item": before}})
        return item


@mcp.tool(annotations=DELETE)
def delete_reminder(reminder_id: str) -> str:
    """Reminders: delete a reminder (can be undone from the dashboard)."""
    with _Call() as call:
        before = _find_reminder(call, reminder_id)
        _run(notes.delete_reminder, reminder_id, user=call.user, db=call.db)
        call.record("delete_reminder", f'Deleted reminder "{before["text"]}"', {"action": "restore_reminder", "args": {"item": before}})
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


# ---- Meal planning ----

def _schedule_today(call: _Call, now: datetime) -> Optional[dict]:
    """Today's remaining calendar events and the free time between them (until 23:00), or None
    when the calendar isn't connected."""
    try:
        data = _widget(call, "calendar", days=1)
    except ToolError:
        return None
    if data.get("needs_setup"):
        return None
    day_end = now.replace(hour=23, minute=0, second=0, microsecond=0)
    busy, events, all_day = [], [], []
    for e in data["events"]:
        if e["all_day"]:
            all_day.append(e["title"])
            continue
        start = datetime.fromisoformat(e["start"]).astimezone(now.tzinfo)
        end = datetime.fromisoformat(e["end"]).astimezone(now.tzinfo) if e["end"] else start
        if end <= now or start >= day_end:
            continue
        events.append({"title": e["title"], "from": f"{start:%H:%M}", "to": f"{end:%H:%M}", "location": e["location"]})
        busy.append((max(start, now), min(end, day_end)))
    free, cursor = [], now
    for start, end in sorted(busy):
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < day_end:
        free.append((cursor, day_end))
    return {
        "events_left_today": events,
        "all_day": all_day,
        "free_time": [{"from": f"{a:%H:%M}", "to": f"{b:%H:%M}", "minutes": int((b - a).total_seconds() // 60)}
                      for a, b in free if (b - a).total_seconds() >= 15 * 60],
    }


@mcp.tool(annotations=READ, description=(
    "Nutrition: plan the rest of today's meals. Returns the local time, the meals still ahead, today's calendar "
    "(events left and free time), today's goals with what's eaten and when, the last 7 days' averages (often short "
    "/ often over), foods eaten recently, the pantry (★ priority items first), the shopping list and `how_to_plan`. Use it whenever the user asks for meal "
    "suggestions or a meal plan.\n\n" + PLAN_GUIDE))
def plan_meals() -> dict:
    with _Call() as call:
        _run(widget_row, call.db, call.user, nutrition.WIDGET_ID)
        now = datetime.now(_zone())
        context = nutrition.meal_plan_context(call.db, call.user, now)
        context["schedule"] = _schedule_today(call, now)
        try:  # the Weight widget is optional
            data = REGISTRY["weight"].fetch(call.db, call.user, REGISTRY["weight"].settings_for(
                widget_row(call.db, call.user, weight.WIDGET_ID)), _ctx())
            context["weight"] = {k: data[k] for k in ("latest", "change_week", "change_month", "goal_kg", "to_goal")}
        except HTTPException:
            context["weight"] = None
        return {**context, "how_to_plan": PLAN_GUIDE}


# ---- Pantry & shopping list (not part of the briefing) ----

def _lists_result(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "undo"}


def _record_lists(call: _Call, tool: str, summary: str, undo: dict) -> None:
    call.record(tool, summary[:200], {"action": "restore_lists", "args": {"undo": undo}})


@mcp.tool(annotations=READ, description=(
    "Pantry & shopping list: `items` is the food the user has at home (id, name, amount, best-before `expires`, "
    "`priority` = starred to use first), `shopping` is their shopping list (id, name, amount, note); both "
    "alphabetical.\n\n" + MEAL_GUIDE))
def get_pantry() -> dict:
    with _Call() as call:
        return _run(nutrition.list_pantry, user=call.user, db=call.db)


@mcp.tool(annotations=WRITE, description=(
    "Pantry: add food the user has at home - one item or a whole list in a single call (use this for lists and "
    "receipts). Each item: `name`, optional `amount` (\"500 g\", \"6\", \"half a bag\"), optional `expires` "
    "(best-before like 2026-10-12) and optional `priority` (true to star it). An item already in the pantry (same "
    "name) is updated instead of duplicated. Shopping-list items with the same names are taken off the list. "
    "Undoable as one change.\n\n" + RECEIPT_GUIDE))
def add_pantry_items(items: list[nutrition.PantryItemIn]) -> dict:
    with _Call() as call:
        if not items:
            raise ToolError("Give at least one item")
        result = _run(nutrition.add_pantry_items, call.db, call.user, items)
        names = [i["name"] for i in result["added"] + result["updated"]]
        off = result["removed_from_shopping_list"]
        _record_lists(call, "add_pantry_items", f"Pantry: added {len(result['added'])}, updated {len(result['updated'])} "
                      f"({', '.join(names)})" + (f"; off the shopping list: {', '.join(off)}" if off else ""), result["undo"])
        row = _run(widget_row, call.db, call.user, nutrition.WIDGET_ID)
        return {**_lists_result(result), "shopping_list_now": [i["name"] for i in nutrition._items(row, "shopping")]}


@mcp.tool(annotations=EDIT)
def update_pantry_item(item_id: str, name: Optional[str] = None, amount: Optional[str] = None,
                       expires: Optional[str] = None, clear_expires: bool = False, priority: Optional[bool] = None) -> dict:
    """Pantry: change an item's name, amount (e.g. what's left after cooking), best-before date (or
    clear_expires=true) or priority star. Ids from get_pantry."""
    with _Call() as call:
        changes: dict[str, Any] = {k: v for k, v in (("name", name), ("amount", amount), ("priority", priority)) if v is not None}
        if expires or clear_expires:
            changes["expires"] = None if clear_expires else _day(expires).isoformat()
        item, undo = _run(nutrition.update_item, call.db, call.user, "pantry", item_id, changes)
        _record_lists(call, "update_pantry_item", f'Changed {item["name"]} in the pantry', undo)
        return item


@mcp.tool(annotations=EDIT)
def set_pantry_priority(item_ids: list[str], priority: bool = True) -> dict:
    """Pantry: star (priority=true) or unstar (false) items. Starred items are used first in meal plans: the
    user stars food that's close to expiring or already opened (e.g. an opened can). Ids from get_pantry."""
    with _Call() as call:
        row = _run(widget_row, call.db, call.user, nutrition.WIDGET_ID)
        known = {i["id"]: i for i in nutrition._items(row, "pantry")}
        missing = [i for i in item_ids if i not in known]
        if missing or not item_ids:
            raise ToolError("Pantry item not found (ids from get_pantry)")
        undo = nutrition._new_undo()
        for item_id in item_ids:
            undo["pantry"]["before"] += _run(nutrition.update_item, call.db, call.user, "pantry", item_id, {"priority": priority})[1]["pantry"]["before"]
        names = ", ".join(known[i]["name"] for i in item_ids)
        _record_lists(call, "set_pantry_priority", f"{'Starred' if priority else 'Unstarred'} in the pantry: {names}", undo)
        return {"changed": len(item_ids), "priority": priority}


@mcp.tool(annotations=DELETE)
def delete_pantry_items(item_ids: list[str]) -> str:
    """Pantry: remove items (used up or thrown away; to buy them again use move_to_shopping_list instead).
    Ids from get_pantry. Undoable."""
    with _Call() as call:
        gone, undo = _run(nutrition.delete_items, call.db, call.user, "pantry", item_ids)
        _record_lists(call, "delete_pantry_items", "Removed from the pantry: " + ", ".join(i["name"] for i in gone), undo)
        return f"Removed {len(gone)}"


@mcp.tool(annotations=READ)
def get_shopping_list() -> dict:
    """Shopping list: what the user plans to buy (id, name, amount, note), alphabetical."""
    with _Call() as call:
        return {"items": _run(nutrition.list_pantry, user=call.user, db=call.db)["shopping"]}


@mcp.tool(annotations=WRITE)
def add_shopping_items(items: list[nutrition.ShoppingItemIn]) -> dict:
    """Shopping list: add things to buy - one or many in a single call. Each item: `name`, optional `amount`
    and `note` (e.g. a brand). An item already on the list (same name) is updated instead of duplicated."""
    with _Call() as call:
        if not items:
            raise ToolError("Give at least one item")
        result = _run(nutrition.add_shopping_items, call.db, call.user, items)
        names = [i["name"] for i in result["added"] + result["updated"]]
        _record_lists(call, "add_shopping_items", "Shopping list: added " + ", ".join(names), result["undo"])
        return _lists_result(result)


@mcp.tool(annotations=EDIT)
def update_shopping_item(item_id: str, name: Optional[str] = None, amount: Optional[str] = None,
                         note: Optional[str] = None) -> dict:
    """Shopping list: change an item's name, amount or note. Ids from get_shopping_list / get_pantry."""
    with _Call() as call:
        changes = {k: v for k, v in (("name", name), ("amount", amount), ("note", note)) if v is not None}
        item, undo = _run(nutrition.update_item, call.db, call.user, "shopping", item_id, changes)
        _record_lists(call, "update_shopping_item", f'Changed {item["name"]} on the shopping list', undo)
        return item


@mcp.tool(annotations=DELETE)
def delete_shopping_items(item_ids: list[str]) -> str:
    """Shopping list: remove items (no longer needed, or bought - but to put bought items in the pantry use
    move_to_pantry). Undoable."""
    with _Call() as call:
        gone, undo = _run(nutrition.delete_items, call.db, call.user, "shopping", item_ids)
        _record_lists(call, "delete_shopping_items", "Off the shopping list: " + ", ".join(i["name"] for i in gone), undo)
        return f"Removed {len(gone)}"


@mcp.tool(annotations=WRITE)
def move_to_pantry(item_ids: list[str]) -> dict:
    """Shopping list -> pantry: the user bought these (ids from get_shopping_list). Afterwards set amounts or
    best-before dates with update_pantry_item if you know them. Undoable."""
    with _Call() as call:
        result = _run(nutrition.move_items, call.db, call.user, "shopping", item_ids)
        names = [i["name"] for i in result["added"] + result["updated"]]
        _record_lists(call, "move_to_pantry", "Bought (shopping list → pantry): " + ", ".join(names), result["undo"])
        return _lists_result(result)


@mcp.tool(annotations=WRITE)
def move_to_shopping_list(item_ids: list[str]) -> dict:
    """Pantry -> shopping list: these are used up and need buying again (ids from get_pantry). Undoable."""
    with _Call() as call:
        result = _run(nutrition.move_items, call.db, call.user, "pantry", item_ids)
        names = [i["name"] for i in result["added"] + result["updated"]]
        _record_lists(call, "move_to_shopping_list", "Used up (pantry → shopping list): " + ", ".join(names), result["undo"])
        return _lists_result(result)


# ---- Weight ----

@mcp.tool(annotations=READ)
def get_weight() -> dict:
    """Weight: the latest body weight, the change vs about a week and a month earlier (with the day it's
    measured from), the goal weight (if set) and the entries of the last 3 months (oldest first)."""
    with _Call() as call:
        return _widget(call, "weight")


@mcp.tool(annotations=WRITE)
def log_weight(kg: float, day: Optional[str] = None) -> dict:
    """Weight: log the user's body weight in kg for a day (default today); replaces that day's value."""
    with _Call() as call:
        entry, previous = _run(weight.log_weight, call.db, call.user, _day(day), kg)
        undo = ({"action": "set_weight", "args": previous} if previous
                else {"action": "delete_weight", "args": {"day": entry["day"]}})
        call.record("log_weight", f'Logged weight {entry["kg"]} kg on {entry["day"]}', undo)
        return entry


@mcp.tool(annotations=DELETE)
def delete_weight(day: str) -> str:
    """Weight: remove the weight logged on `day` (like 2026-10-03). Can be undone."""
    with _Call() as call:
        entry = _run(weight.delete_weight, call.db, call.user, _day(day).isoformat())
        call.record("delete_weight", f'Removed weight {entry["kg"]} kg from {entry["day"]}', {"action": "set_weight", "args": entry})
        return "Deleted"


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


BUDGET_GUIDE = (
    "How the user's budget log works: each entry is a month, a category path and a positive amount in the user's "
    "currency (kr). The path's first level is \"Expenses\" or \"Income\". For expenses the second level MUST be "
    "exactly one of these sub-categories (no others exist):\n"
    + "\n".join(f"- {name}: {what}" for name, what in budget.EXPENSE_GUIDE.items())
    + "\nThe third and fourth levels are free text: usually the shop/place or a group (\"Wolt\", \"Midttraffik + DSB\", "
    "\"Wizz Air\") and then a detail such as a route (\"BLL - OTP\"). Spending abroad starts with the country's "
    "flag emoji (\"🇷🇴El Dictador\"). Income sub-categories are free text (e.g. \"SU\", \"Salary\" > employer).\n"
    "Before adding: call get_budget for that month. Its `paths` lists every path used so far: reuse an existing "
    "path with its exact spelling when it fits instead of inventing a new name. The log keeps one total per path "
    "per month, so if the month already has an entry with the same path, add to its amount with "
    "update_budget_entry instead of creating a second one. If the right sub-category isn't clear, ask the user."
)


@mcp.tool(annotations=WRITE, description=(
    "Budget: add a NEW income or expense entry. `path`: 1-4 levels, e.g. [\"Expenses\", \"Restaurant/Café\", \"Wolt\"] "
    "or [\"Income\", \"SU\"]; `amount` positive; `month` like 2026-09 (default this month).\n\n" + BUDGET_GUIDE))
def add_budget_entry(path: list[str], amount: float, month: Optional[str] = None) -> dict:
    with _Call() as call:
        entry = _run(budget.add_entry, budget.EntryIn(month=_month(month), path=path, amount=amount), user=call.user, db=call.db)
        call.record("add_budget_entry", f'Added {_path_text(entry["path"])}: {entry["amount"]:.2f} ({entry["month"]})',
                    {"action": "delete_budget_entry", "args": {"id": entry["id"]}})
        return entry


@mcp.tool(annotations=EDIT, description=(
    "Budget: change an entry's amount, category path or month (ids from get_budget), e.g. to add a new purchase "
    "to this month's total for that path. Paths follow the same rules as add_budget_entry: an expense's second "
    "level must be one of " + ", ".join(budget.EXPENSE_CATEGORIES) + "."))
def update_budget_entry(entry_id: int, amount: Optional[float] = None, path: Optional[list[str]] = None,
                        month: Optional[str] = None) -> dict:
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
