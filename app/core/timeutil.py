"""The viewer's timezone and local date. Widgets receive the browser's IANA timezone
(e.g. "Europe/Copenhagen") and key "days" by the viewer's local date. Needs the tzdata
package on systems without a timezone database (Windows)."""
from datetime import date, datetime, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo


def local_zone(tz: Optional[str]) -> tzinfo:
    """The viewer's timezone; UTC when missing or unknown."""
    try:
        return ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        return timezone.utc


def local_today(tz: Optional[str]) -> date:
    return datetime.now(local_zone(tz)).date()
