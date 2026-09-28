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
_prompt_cache: dict = {"mtime": None, "prompt": PROMPT_DEFAULTS}


def load_prompt() -> dict:
    """{"instructions", "default_question", "suggestions"} from the "## " sections of
    content/assistant_prompt.md, re-read when the file changes. Missing sections fall
    back to the defaults above."""
    mtime = PROMPT_FILE.stat().st_mtime
    if _prompt_cache["mtime"] != mtime:
        parts = _sections(PROMPT_FILE.read_text(encoding="utf-8"))
        suggestions = [line[2:].strip() for line in parts.get("suggestions", "").splitlines()
                       if line.startswith("- ") and line[2:].strip()]
        _prompt_cache.update(mtime=mtime, prompt={
            "instructions": parts.get("instructions") or PROMPT_DEFAULTS["instructions"],
            "default_question": parts.get("default question") or PROMPT_DEFAULTS["default question"],
            "suggestions": suggestions,
        })
    return _prompt_cache["prompt"]


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

    sections = []
    for definition in REGISTRY.values():  # registry order = a stable, sensible order
        row = active.get(definition.id)
        if row is None or definition.brief is None or definition.id == WIDGET_ID:
            continue
        try:
            text = definition.brief(definition.fetch(db, user, definition.settings_for(row), ctx))
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
