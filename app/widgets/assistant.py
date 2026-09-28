# Assistant widget: a one-stop daily briefing built from the user's other widgets, and a
# way to ask Claude about it.
#
# Claude Pro can't be used by an app (only by a person on claude.ai; the API is billed
# separately), so this costs nothing: the briefing is plain text assembled here from
# each widget's brief() (widgets without one, like the private journal, are never
# included), and the frontend opens claude.ai with the briefing + the user's question,
# where Claude answers on their own subscription.
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Integration, User
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition, register

WIDGET_ID = "assistant"
logger = logging.getLogger(__name__)

# The prompt wording is user-editable in content/assistant_prompt.md (repo root)
PROMPT_FILE = Path(__file__).resolve().parents[2] / "content" / "assistant_prompt.md"
PROMPT_DEFAULTS = {
    "instructions": "Here is my personal dashboard briefing for {when}. Use it as context.",
    "default question": "Give me a short overview of my day and three practical suggestions.",
    "suggestions": [],
}
_prompt_cache: dict = {"mtime": None, "prompt": PROMPT_DEFAULTS, "briefing": {}}


def _load() -> None:
    mtime = PROMPT_FILE.stat().st_mtime
    if _prompt_cache["mtime"] == mtime:
        return
    parts = _sections(PROMPT_FILE.read_text(encoding="utf-8"))
    suggestions = [line[2:].strip() for line in parts.get("suggestions", "").splitlines()
                   if line.startswith("- ") and line[2:].strip()]
    instructions = parts.get("instructions") or PROMPT_DEFAULTS["instructions"]
    extras = _extra_instructions(parts.get("extra instructions", ""))
    if extras:
        instructions += "\n\nIn your answer, also include (only where it fits my question):\n" + "\n".join(
            f"- {name}: {text}" for name, text in extras
        )
    _prompt_cache.update(mtime=mtime, briefing=_briefing_rules(parts.get("briefing", "")), prompt={
        "instructions": instructions,
        "default_question": parts.get("default question") or PROMPT_DEFAULTS["default question"],
        "suggestions": suggestions,
    })


def load_prompt() -> dict:
    """{"instructions", "default_question", "suggestions"} from the "## " sections of
    content/assistant_prompt.md, re-read when the file changes. Missing sections fall
    back to the defaults above."""
    _load()
    return _prompt_cache["prompt"]


def load_briefing_rules() -> dict[str, object]:
    """{"widget name or id in lowercase": "off" | "on" | max items} from the "## Briefing"
    section. Widgets not listed are included with their default limit."""
    _load()
    return _prompt_cache["briefing"]


def _extra_instructions(text: str) -> list[tuple[str, str]]:
    """[(name, instruction)] for the ticked "- [x] Name: instruction" lines; unticked
    "- [ ]" lines are switched off."""
    extras = []
    for line in text.splitlines():
        line = line.strip()
        if not line.lower().startswith("- [x]"):
            continue
        name, _, instruction = line[5:].partition(":")
        if name.strip() and instruction.strip():
            extras.append((name.strip(), instruction.strip()))
    return extras


def _briefing_rules(text: str) -> dict[str, object]:
    rules: dict[str, object] = {}
    for line in text.splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        name, _, value = line[2:].rpartition(":")
        value = value.strip().lower()
        if value in ("on", "off"):
            rules[name.strip().lower()] = value
        elif value.isdigit() and int(value) > 0:
            rules[name.strip().lower()] = int(value)
    return rules


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


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    rows = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.status == "active")
        .all()
    )
    active = {row.app_name: row for row in rows}
    rules = load_briefing_rules()

    sections = []
    for definition in REGISTRY.values():  # registry order = a stable, sensible order
        row = active.get(definition.id)
        if row is None or definition.brief is None or definition.id == WIDGET_ID:
            continue
        rule = rules.get(definition.name.lower(), rules.get(definition.id))
        if rule == "off":
            continue
        limit = rule if isinstance(rule, int) else None
        settings = definition.settings_for(row)
        if limit and "max_items" in settings:
            settings = {**settings, "max_items": limit}  # fetch enough items for the briefing
        try:
            text = definition.brief(definition.fetch(db, user, settings, ctx), limit)
        except Exception:
            logger.warning("Briefing: %s widget failed", definition.id, exc_info=True)
            text = "(couldn't load right now)"
        sections.append({"widget": definition.id, "name": definition.name, "text": text})

    return {"sections": sections, "prompt": load_prompt()}


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Assistant",
    description="A daily briefing from all your widgets, and one click to ask Claude about it on claude.ai (uses your Claude subscription, no extra cost).",
    fetch=fetch,
    default_size=(8, 8),
    min_size=(4, 6),
    refresh_seconds=1800,
    enabled_by_default=True,
))
