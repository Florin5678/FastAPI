# Email summary widget: today's mail at a glance (counts per category + latest emails)
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Email, User
from app.summarize import get_client
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = db.query(Email).filter(Email.user_id == user.id, Email.timestamp >= ctx.since)

    counts = (
        today.with_entities(Email.category, func.count(Email.id))
        .group_by(Email.category)
        .all()
    )
    categories = sorted(
        ({"category": category or "unsummarized", "count": count} for category, count in counts),
        key=lambda c: (c["category"] == "unsummarized", -c["count"]),
    )

    latest = (
        db.query(Email)
        .filter(Email.user_id == user.id)
        .order_by(Email.timestamp.desc())
        .limit(settings["max_items"])
        .all()
    )
    last_synced = db.query(func.max(Email.created_at)).filter(Email.user_id == user.id).scalar()

    return {
        "today_total": sum(c["count"] for c in categories),
        "categories": categories if settings["show_categories"] else [],
        "latest": [
            {
                "id": e.id,
                "subject": e.subject,
                "sender": e.sender,
                "timestamp": e.timestamp.isoformat() + "Z" if e.timestamp else None,
                "category": e.category,
                "summary": e.summary,
                "snippet": e.snippet,
            }
            for e in latest
        ],
        "summaries_enabled": get_client() is not None,
        "last_new_mail_at": last_synced.isoformat() + "Z" if last_synced else None,
    }


register(WidgetDefinition(
    id="email_summary",
    name="Email",
    description="Today's mail at a glance: counts per category and your latest emails with their summaries.",
    fetch=fetch,
    default_size=(4, 7),
    min_size=(3, 5),
    layout_version=3,  # v2: 6x9 -> 5x8 for weather; v3: 4x7 so email/weather/nutrition share a row
    refresh_seconds=300,
    enabled_by_default=True,
    config_fields=(
        ConfigField("max_items", "Emails to show", "number", default=5, min=1, max=15),
        ConfigField("show_categories", "Show category counts", "boolean", default=True),
    ),
))
