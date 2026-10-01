# Email summary widget: today's mail at a glance (counts per category + latest emails)
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Email, User
from app.mail.summarize import get_client
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
    # For the Assistant's briefing: everything from the last 24 hours
    recent = (
        db.query(Email)
        .filter(Email.user_id == user.id, Email.timestamp >= datetime.utcnow() - timedelta(hours=24))
        .order_by(Email.timestamp.desc())
        .limit(RECENT_MAX)
        .all()
    )
    zone = ZoneInfo(ctx.tz or "Europe/Copenhagen")

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
        "last_24h": [
            {"sender": e.sender, "subject": e.subject, "category": e.category or "unsummarized",
             "summary": e.summary or e.snippet,
             "time": f"{e.timestamp.replace(tzinfo=ZoneInfo('UTC')).astimezone(zone):%a %H:%M}" if e.timestamp else ""}
            for e in recent
        ],
        "summaries_enabled": get_client() is not None,
        "last_new_mail_at": last_synced.isoformat() + "Z" if last_synced else None,
    }


# Briefing order: mail that may need the user first, bulk mail last
CATEGORY_ORDER = ["personal", "work", "school", "finance", "travel", "social", "shopping", "other",
                  "unsummarized", "notification", "newsletter", "promotion"]
RECENT_MAX = 80


def _sender(sender: str | None) -> str:
    """'"Altibox Danmark A/S" <noreply@altibox.dk>' -> 'Altibox Danmark A/S'."""
    name = re.sub(r"\s*<[^>]*>\s*$", "", sender or "").strip().strip('"')
    return name or (sender or "Unknown").strip("<>")


def brief(data: dict, limit: int | None = None) -> str:
    emails = data.get("last_24h", [])
    if not emails:
        return "No emails in the last 24 hours."
    counts: dict[str, int] = {}
    for e in emails:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    ordered = sorted(emails, key=lambda e: rank.get(e["category"], len(rank)))  # stable: newest first within a category
    shown = ordered[:limit or 15]
    lines = [
        f"{len(emails)} email(s) in the last 24 hours (" + ", ".join(f"{c} {n}" for c, n in sorted(counts.items(), key=lambda x: rank.get(x[0], 99))) + ").",
        "Most relevant first, as [category] time · sender: subject - summary:",
    ]
    for e in shown:
        line = f"- [{e['category']}] {e['time']} · {_sender(e['sender'])}: {e['subject'] or '(no subject)'}"
        if e["summary"]:
            line += f" - {e['summary'].strip()[:300]}"
        lines.append(line)
    rest = ordered[len(shown):]
    if rest:
        left: dict[str, int] = {}
        for e in rest:
            left[e["category"]] = left.get(e["category"], 0) + 1
        lines.append(f"(+{len(rest)} lower-priority emails not listed: " + ", ".join(f"{c} {n}" for c, n in left.items()) + ")")
    return "\n".join(lines)


register(WidgetDefinition(
    id="email_summary",
    name="Email",
    description="Today's mail at a glance: counts per category and your latest emails with their summaries.",
    fetch=fetch,
    brief=brief,
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
