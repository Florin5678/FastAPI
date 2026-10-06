# Assistant widget: a one-stop daily briefing built from the user's other widgets, and a
# way to ask Claude about it.
#
# The briefing is plain text assembled here from a "Today" section (date, week, moon,
# holidays: app/widgets/today.py) and each widget's brief() (widgets without one, like the
# private journal, are never included), after the user's filters (ignored calendar events,
# skipped email categories) are applied in code. compose_prompt() turns it into one prompt:
#   opening -> the briefing data -> "How to answer" (the answer sections, then the
#   rules) -> the Claude prompt (what "Open in Claude" sends).
# The same prompt is used everywhere: get_briefing in the Claude connector (what "Open in
# Claude" asks Claude on claude.ai to fetch) and "Copy briefing"; the AI chat's system prompt
# (assistant_chat.py) gets the same briefing and "How to answer". Claude Pro answers on the user's own subscription.
#
# What goes into the prompt is edited in the widget's Settings dialog and stored in the
# widget's row (config["assistant"]); default_settings() is used until they're first saved.
import logging
import re
from datetime import datetime, time, timezone
from typing import Optional, Union, get_args
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import DASHBOARD_TZ
from app.mail.summarize import Category
from app.models import Integration, User
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition, register
from app.widgets.today import today_section

WIDGET_ID = "assistant"
logger = logging.getLogger(__name__)

# Fallbacks when the opening or question is left empty
PROMPT_DEFAULTS = {
    "instructions": "Here is my personal dashboard briefing for {when}. Use it as context.",
}
# What follows the answer sections in "How to answer" (editable in Settings as "Rules")
DEFAULT_RULES = (
    "Base each section on the briefing. Don't skip a section: if the briefing has nothing for it, say so in one "
    "short line. If a section asks you to use another connector or tool (e.g. Slack), use it before answering; "
    "if it isn't available to you, say so in that section.\n\n"
    "Rules (always follow):\n"
    "- The Today section (date, week, moon, holidays, sky events) is computed and correct: use it, don't work "
    "these out yourself.\n"
    "- Don't invent facts that aren't in the briefing or a tool result."
)
# What "Open in Claude" pre-fills on claude.ai (editable in Settings as "Claude prompt"):
# Claude then fetches the full briefing itself through the connector's get_briefing
DEFAULT_CLAUDE_PROMPT = (
    'Brief me. First call get_briefing from my "My Dashboard" connector, then answer exactly as its '
    '"How to answer" part says. If you can\'t use that connector here, tell me to switch it on for this chat.'
)
# How many items a widget's brief() sends by default (widgets not listed have no list)
DEFAULT_LIMITS = {"email_summary": 15, "calendar": 25, "news": 3, "notes": 15}
ITEM_LABELS = {"news": "headlines per topic", "calendar": "events", "email_summary": "emails", "notes": "reminders"}
# Widget settings used when fetching for the briefing (the tile may show less)
BRIEF_SETTINGS = {"news": {"topic": "All", "max_items": 500}}
EMAIL_CATEGORIES = [*get_args(Category), "unsummarized"]
TIMEZONE = DASHBOARD_TZ
MAX_EXTRAS = 30
MAX_ITEMS = 50


# ---- Settings ----

class ExtraInstruction(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=600)
    enabled: bool = True


class BriefingFilters(BaseModel):
    """Applied in code before Claude sees anything (more reliable than asking it to ignore)."""
    calendar_ignore: str = Field("", max_length=1000)  # comma/line separated; events whose title contains one
    email_skip_categories: list[str] = Field(default_factory=lambda: ["promotion", "newsletter"])
    email_ignore: str = Field("", max_length=1000)  # comma/line separated; matched in sender or subject


class AssistantSettings(BaseModel):
    instructions: str = Field(max_length=3000)
    rules: str = Field(DEFAULT_RULES, max_length=4000)  # after the answer sections in "How to answer"
    claude_prompt: str = Field(DEFAULT_CLAUDE_PROMPT, max_length=2000)  # what "Open in Claude" sends
    extras: list[ExtraInstruction] = Field(default_factory=list, max_length=MAX_EXTRAS)
    # widget id -> "on" | "off" | number of items; widgets not listed are included as usual
    briefing: dict[str, Union[int, str]] = Field(default_factory=dict)
    filters: BriefingFilters = Field(default_factory=BriefingFilters)
    # AI chat (paid Claude API, see assistant_chat.py)
    model: str = Field("claude-haiku-4-5", max_length=60)
    monthly_budget: float = Field(5.0, ge=0, le=200)  # USD; 0 = chat off
    # Morning brief (assistant_chat.py): written by Claude each day after this local time
    morning_brief: bool = False
    morning_brief_time: str = Field("07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def default_settings() -> AssistantSettings:
    """Starting settings, until the user saves their own in the Settings dialog."""
    return AssistantSettings(
        instructions="Here is my personal dashboard briefing for {when}. Use it as context.",
        extras=[
            ExtraInstruction(name="Daily forecast", text="The day, week number, weather, moon phase and any holidays "
                             "or sky events (see Today), and my calendar events for today and the coming days."),
            ExtraInstruction(name="Email", text="Which emails are important and which need a reply today."),
            ExtraInstruction(name="Urgent tasks", text="Which reminders are overdue or due soon (see Reminders)."),
            ExtraInstruction(name="Health", text="Meal and workout suggestions based on what I've eaten and trained "
                             "recently (see Nutrition and Gym)."),
            ExtraInstruction(name="News digest", text="The few most important headlines (see News)."),
        ],
    )


def _row(db: Session, user: User) -> Optional[Integration]:
    return db.query(Integration).filter(Integration.user_id == user.id, Integration.app_name == WIDGET_ID).first()


def load_settings(db: Session, user: User) -> AssistantSettings:
    row = _row(db, user)
    saved = (row.config or {}).get("assistant") if row else None
    if saved:
        try:
            settings = AssistantSettings.model_validate(saved)
            # Drop widgets that no longer exist in the app
            settings.briefing = {k: v for k, v in settings.briefing.items() if k in REGISTRY}
            return settings
        except ValueError:
            logger.warning("Assistant settings for user %s are invalid; using defaults", user.id)
    return default_settings()


def _words(text: str) -> list[str]:
    return [w.strip().lower() for w in re.split(r"[,\n]", text) if w.strip()]


def _apply_filters(widget_id: str, data: dict, f: BriefingFilters) -> tuple[dict, Optional[str]]:
    """The widget's data without what the user filtered out, and a note saying how much."""
    if widget_id == "calendar" and data.get("events"):
        words = _words(f.calendar_ignore)
        kept = [e for e in data["events"] if not any(w in (e["title"] or "").lower() for w in words)]
        left = len(data["events"]) - len(kept)
        return {**data, "events": kept}, (f"({left} event(s) left out by the ignore list)" if left else None)
    if widget_id == "email_summary" and data.get("last_24h"):
        skip, words = set(f.email_skip_categories), _words(f.email_ignore)
        kept, left = [], {}
        for e in data["last_24h"]:
            reason = e["category"] if e["category"] in skip else (
                "ignore list" if any(w in f"{e['sender']} {e['subject']}".lower() for w in words) else None)
            if reason:
                left[reason] = left.get(reason, 0) + 1
            else:
                kept.append(e)
        note = "(Left out by filters: " + ", ".join(f"{n} {r}" for r, n in left.items()) + ")" if left else None
        return {**data, "last_24h": kept}, note
    return data, None


def default_ctx() -> WidgetContext:
    """Context for "today" in the user's timezone (for routes without the browser's)."""
    zone = ZoneInfo(TIMEZONE)
    midnight = datetime.combine(datetime.now(zone).date(), time.min, tzinfo=zone)
    return WidgetContext(since=midnight.astimezone(timezone.utc).replace(tzinfo=None), tz=TIMEZONE)


def briefing_sections(db: Session, user: User, ctx: WidgetContext, prefs: AssistantSettings) -> list[dict]:
    rows = db.query(Integration).filter(Integration.user_id == user.id, Integration.status == "active").all()
    active = {row.app_name: row for row in rows}
    sections = [{"widget": "today", "name": "Today", "text": today_section(ctx.tz or TIMEZONE)}]
    for definition in REGISTRY.values():  # registry order = a stable, sensible order
        row = active.get(definition.id)
        if row is None or definition.brief is None or definition.id == WIDGET_ID:
            continue
        rule = prefs.briefing.get(definition.id)
        if rule == "off":
            continue
        limit = rule if isinstance(rule, int) else DEFAULT_LIMITS.get(definition.id)
        widget_settings = definition.settings_for(row)
        if limit and "max_items" in widget_settings:
            widget_settings = {**widget_settings, "max_items": limit}  # fetch enough items for the briefing
        widget_settings = {**widget_settings, **BRIEF_SETTINGS.get(definition.id, {})}
        try:
            data, note = _apply_filters(definition.id, definition.fetch(db, user, widget_settings, ctx), prefs.filters)
            text = definition.brief(data, limit) + (f"\n{note}" if note else "")
        except Exception:
            logger.warning("Briefing: %s widget failed", definition.id, exc_info=True)
            text = "(couldn't load right now)"
        sections.append({"widget": definition.id, "name": definition.name, "text": text})
    return sections


def render_sections(sections: list[dict]) -> str:
    return "\n\n".join(f"## {s['name']}\n{s['text']}" for s in sections)


def answer_guide(s: AssistantSettings) -> str:
    """The answer sections (the "extras"), then the user's rules."""
    parts = []
    sections = [e for e in s.extras if e.enabled]
    if sections:
        parts.append(
            "Answer with these sections, in this order, each under its name as a heading:\n"
            + "\n".join(f"{n}. {e.name}: {e.text}" for n, e in enumerate(sections, 1))
        )
    parts.append(s.rules.strip() or DEFAULT_RULES)
    return "\n\n".join(parts)


def compose_prompt(s: AssistantSettings, sections: list[dict]) -> str:
    """The whole prompt; "{when}" is left for the caller to fill with the current time."""
    opening = s.instructions.strip() or PROMPT_DEFAULTS["instructions"]
    return (
        f"{opening}\n\n# My dashboard briefing\n\n{render_sections(sections)}\n\n"
        f"# How to answer\n\n{answer_guide(s)}\n\n# My question\n\n{s.claude_prompt.strip() or DEFAULT_CLAUDE_PROMPT}"
    )


def fill_when(prompt: str, tz: Optional[str] = None) -> str:
    return prompt.replace("{when}", datetime.now(ZoneInfo(tz or TIMEZONE)).strftime("%A %d %B %Y at %H:%M"))


# ---- Widget ----

def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    prefs = load_settings(db, user)
    sections = briefing_sections(db, user, ctx, prefs)
    return {"sections": sections, "prompt": compose_prompt(prefs, sections),
            "claude_prompt": prefs.claude_prompt.strip() or DEFAULT_CLAUDE_PROMPT,
            "morning_brief": {"enabled": prefs.morning_brief, "time": prefs.morning_brief_time,
                              **((_row(db, user).config or {}).get("morning_brief") or {})}}


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Assistant",
    description="A daily briefing from all your widgets, and one click to ask Claude about it on claude.ai (uses your Claude subscription, no extra cost).",
    fetch=fetch,
    default_size=(4, 4),
    min_size=(3, 4),
    layout_version=3,  # v2: 8x8 -> 4x3 once the preview and question box were removed; v3: 4x4 for the Chat button
    refresh_seconds=1800,
    enabled_by_default=True,
))


# ---- Settings routes (the widget's Settings dialog) ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


def _briefing_widgets(db: Session, user: User) -> list[dict]:
    """Widgets that can be in the briefing, for the settings dialog."""
    active = {
        r.app_name for r in db.query(Integration).filter(Integration.user_id == user.id, Integration.status == "active")
    }
    return [
        {"id": d.id, "name": d.name, "on_dashboard": d.id in active, "default_items": DEFAULT_LIMITS.get(d.id),
         "items_label": ITEM_LABELS.get(d.id, "items")}
        for d in REGISTRY.values()
        if d.brief is not None and d.id != WIDGET_ID
    ]


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"settings": load_settings(db, user).model_dump(), "widgets": _briefing_widgets(db, user),
            "email_categories": EMAIL_CATEGORIES}


@router.post("/preview")
def preview(body: AssistantSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The prompt as it would be with these (unsaved) settings, for the Settings dialog."""
    ctx = default_ctx()
    return {"prompt": fill_when(compose_prompt(body, briefing_sections(db, user, ctx, body)))}


@router.put("/settings")
def save_settings(body: AssistantSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for widget_id, rule in body.briefing.items():
        if widget_id not in REGISTRY:
            raise HTTPException(status_code=422, detail=f"Unknown widget {widget_id!r}")
        if isinstance(rule, str) and rule not in ("on", "off"):
            raise HTTPException(status_code=422, detail="Each widget must be on, off or a number of items")
        if isinstance(rule, int) and not 0 < rule <= MAX_ITEMS:
            raise HTTPException(status_code=422, detail=f"Number of items must be 1 to {MAX_ITEMS}")
    unknown = set(body.filters.email_skip_categories) - set(EMAIL_CATEGORIES)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown email categories: {', '.join(sorted(unknown))}")
    from app.widgets.assistant_chat import MODELS  # (imported here: assistant_chat imports this module)
    if body.model not in MODELS:
        raise HTTPException(status_code=422, detail=f"Model must be one of: {', '.join(MODELS)}")
    row = _row(db, user)
    if row is None:
        raise HTTPException(status_code=404, detail="Add the Assistant widget to your dashboard first")
    # JSON columns aren't mutation-tracked: assign a new dict
    row.config = {**(row.config or {}), "assistant": body.model_dump()}
    db.commit()
    return {"settings": body.model_dump()}
