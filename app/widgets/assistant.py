# Assistant widget: a one-stop daily briefing built from the user's other widgets, and a
# way to ask Claude about it.
#
# Claude Pro can't be used by an app (only by a person on claude.ai; the API is billed
# separately), so this costs nothing: the briefing is plain text assembled here from
# each widget's brief() (widgets without one, like the private journal, are never
# included), and the frontend opens claude.ai with the briefing + the user's question,
# where Claude answers on their own subscription.
import logging

from sqlalchemy.orm import Session

from app.models import Integration, User
from app.widgets.registry import REGISTRY, WidgetContext, WidgetDefinition, register

WIDGET_ID = "assistant"
logger = logging.getLogger(__name__)


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

    return {"sections": sections}


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
