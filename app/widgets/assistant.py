# Assistant widget: a one-stop daily briefing built from the user's other widgets, and a
# way to ask Claude about it.
#
# Claude Pro can't be used by an app (only by a person on claude.ai; the API is billed
# separately), so this costs nothing: the briefing is plain text assembled here from
# each widget's brief() (widgets without one, like the private journal, are never
# included), and the frontend opens claude.ai with the briefing + the user's question,
# where Claude answers on their own subscription.
#
# What goes into the prompt is edited in the widget's Settings dialog and stored in the
# widget's row (config["assistant"]): the opening instructions, the default question,
# switchable extra instructions, and which widgets are included (and how many items).
# content/assistant_prompt.md only provides the starting values until the settings are
# first saved.
import logging
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Integration, User
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition, register

WIDGET_ID = "assistant"
logger = logging.getLogger(__name__)

# Starting values (used until the user saves the Assistant settings)
PROMPT_FILE = Path(__file__).resolve().parents[2] / "content" / "assistant_prompt.md"
PROMPT_DEFAULTS = {
    "instructions": "Here is my personal dashboard briefing for {when}. Use it as context.",
    "default question": "Give me a short overview of my day and three practical suggestions.",
}
# How many items a widget's brief() sends by default (widgets not listed have no list)
DEFAULT_LIMITS = {"email_summary": 5, "calendar": 12, "news": 6, "notes": 10, "nutrition": 8}
MAX_EXTRAS = 30
MAX_ITEMS = 50


# ---- Settings ----

class ExtraInstruction(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=600)
    enabled: bool = True


class AssistantSettings(BaseModel):
    instructions: str = Field(max_length=3000)
    default_question: str = Field(max_length=1000)
    extras: list[ExtraInstruction] = Field(default_factory=list, max_length=MAX_EXTRAS)
    # widget id -> "on" | "off" | number of items; widgets not listed are included as usual
    briefing: dict[str, Union[int, str]] = Field(default_factory=dict)
    # AI chat (paid Claude API, see assistant_chat.py)
    model: str = Field("claude-haiku-4-5", max_length=60)
    monthly_budget: float = Field(5.0, ge=0, le=200)  # USD; 0 = chat off


def _sections(markdown: str) -> dict[str, str]:
    """{"heading in lowercase": "text under it"} for each "## " heading."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def defaults_from_file() -> AssistantSettings:
    """Starting settings from content/assistant_prompt.md (its old format: "- [x] Name:
    instruction" lines and "- Widget name: N | on | off" lines)."""
    try:
        parts = _sections(PROMPT_FILE.read_text(encoding="utf-8"))
    except OSError:
        parts = {}
    extras = []
    for line in parts.get("extra instructions", "").splitlines():
        line = line.strip()
        box = line[:5].lower()
        if box not in ("- [x]", "- [ ]"):
            continue
        name, _, text = line[5:].partition(":")
        if name.strip() and text.strip():
            extras.append(ExtraInstruction(name=name.strip()[:80], text=text.strip()[:600], enabled=box == "- [x]"))
    by_name = {d.name.lower(): d.id for d in REGISTRY.values()}
    briefing: dict[str, Union[int, str]] = {}
    for line in parts.get("briefing", "").splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        name, _, value = line[2:].rpartition(":")
        widget_id = by_name.get(name.strip().lower()) or (name.strip() if name.strip() in REGISTRY else None)
        value = value.strip().lower()
        if widget_id and value in ("on", "off"):
            briefing[widget_id] = value
        elif widget_id and value.isdigit() and 0 < int(value) <= MAX_ITEMS:
            briefing[widget_id] = int(value)
    return AssistantSettings(
        instructions=parts.get("instructions") or PROMPT_DEFAULTS["instructions"],
        default_question=parts.get("default question") or PROMPT_DEFAULTS["default question"],
        extras=extras[:MAX_EXTRAS],
        briefing=briefing,
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
    return defaults_from_file()


def build_prompt(s: AssistantSettings) -> dict:
    """{"instructions", "default_question"} for the frontend: the opening text, then the
    enabled extra instructions."""
    instructions = s.instructions.strip() or PROMPT_DEFAULTS["instructions"]
    extras = [e for e in s.extras if e.enabled]
    if extras:
        instructions += "\n\nIn your answer, also include (only where it fits my question):\n" + "\n".join(
            f"- {e.name}: {e.text}" for e in extras
        )
    return {"instructions": instructions, "default_question": s.default_question.strip() or PROMPT_DEFAULTS["default question"]}


# ---- Widget ----

def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    rows = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.status == "active")
        .all()
    )
    active = {row.app_name: row for row in rows}
    prefs = load_settings(db, user)

    sections = []
    for definition in REGISTRY.values():  # registry order = a stable, sensible order
        row = active.get(definition.id)
        if row is None or definition.brief is None or definition.id == WIDGET_ID:
            continue
        rule = prefs.briefing.get(definition.id)
        if rule == "off":
            continue
        limit = rule if isinstance(rule, int) else None
        widget_settings = definition.settings_for(row)
        if limit and "max_items" in widget_settings:
            widget_settings = {**widget_settings, "max_items": limit}  # fetch enough items for the briefing
        try:
            text = definition.brief(definition.fetch(db, user, widget_settings, ctx), limit)
        except Exception:
            logger.warning("Briefing: %s widget failed", definition.id, exc_info=True)
            text = "(couldn't load right now)"
        sections.append({"widget": definition.id, "name": definition.name, "text": text})

    return {"sections": sections, "prompt": build_prompt(prefs)}


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
        {"id": d.id, "name": d.name, "on_dashboard": d.id in active, "default_items": DEFAULT_LIMITS.get(d.id)}
        for d in REGISTRY.values()
        if d.brief is not None and d.id != WIDGET_ID
    ]


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"settings": load_settings(db, user).model_dump(), "widgets": _briefing_widgets(db, user)}


@router.put("/settings")
def save_settings(body: AssistantSettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for widget_id, rule in body.briefing.items():
        if widget_id not in REGISTRY:
            raise HTTPException(status_code=422, detail=f"Unknown widget {widget_id!r}")
        if isinstance(rule, str) and rule not in ("on", "off"):
            raise HTTPException(status_code=422, detail="Each widget must be on, off or a number of items")
        if isinstance(rule, int) and not 0 < rule <= MAX_ITEMS:
            raise HTTPException(status_code=422, detail=f"Number of items must be 1 to {MAX_ITEMS}")
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
