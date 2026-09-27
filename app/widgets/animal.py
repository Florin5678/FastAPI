# Animal Fact of the Day: one animal per (local) day from content/animals.md, with its
# photo and summary from Wikipedia's free page-summary API (no key; text CC BY-SA).
# Wikipedia asks API clients to send a descriptive User-Agent *with contact info*
# (https://meta.wikimedia.org/wiki/User-Agent_policy); requests from cloud servers
# without it can be refused. Summaries are cached per animal for a day. If the server
# still can't reach Wikipedia, fetch() returns just the animal and the browser loads
# the summary itself (the REST API allows cross-origin requests).
import logging
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.widgets.registry import WidgetContext, WidgetDefinition, register

# Edit the list in content/animals.md (repo root)
ANIMALS_FILE = Path(__file__).resolve().parents[2] / "content" / "animals.md"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
USER_AGENT = "PersonalDashboard/1.0 (https://github.com/Florin5678/FastAPI; personal non-commercial dashboard) python-requests"
logger = logging.getLogger(__name__)
CACHE_SECONDS = 24 * 3600

_animals_cache: dict = {"mtime": None, "animals": []}
_summary_cache: dict[str, tuple[float, dict]] = {}


def load_animals() -> list[str]:
    """Animal names ("- Title" lines), in a fixed shuffled order so the daily
    rotation doesn't walk through similar animals in list order."""
    mtime = ANIMALS_FILE.stat().st_mtime
    if _animals_cache["mtime"] != mtime:
        names = [line[2:].strip() for line in ANIMALS_FILE.read_text(encoding="utf-8").splitlines()
                 if line.startswith("- ") and line[2:].strip()]
        random.Random(2026).shuffle(names)
        _animals_cache.update(mtime=mtime, animals=names)
    return _animals_cache["animals"]


def _local_date(tz: Optional[str]):
    try:
        return datetime.now(ZoneInfo(tz)).date() if tz else datetime.now(timezone.utc).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _summary_url(name: str) -> str:
    return SUMMARY_URL.format(title=quote(name.replace(" ", "_"), safe=""))


def _summary(name: str) -> Optional[dict]:
    """Wikipedia's summary for the animal, or None if the server can't get it."""
    cached = _summary_cache.get(name)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    for attempt in range(2):
        try:
            response = requests.get(
                _summary_url(name),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=10,
            )
            if response.ok:
                data = response.json()
                _summary_cache[name] = (time.time(), data)
                return data
            logger.warning("Wikipedia summary for %r: HTTP %s %s", name, response.status_code, response.text[:200])
        except requests.RequestException as e:
            logger.warning("Wikipedia summary for %r failed: %s", name, e)
        if attempt == 0:
            time.sleep(0.5)
    return cached[1] if cached else None


# Wikimedia only serves standard thumbnail widths (e.g. 330, 500, 960; 640 -> 400 error)
STANDARD_WIDTHS = (500, 960)


def _thumbnail(summary: dict, width: int) -> Optional[str]:
    """The summary's ~330px thumbnail re-requested at a standard width, if the original is that big."""
    thumb = summary.get("thumbnail") or {}
    original_width = (summary.get("originalimage") or {}).get("width") or 0
    if not thumb.get("source"):
        return None
    if original_width < width or not re.search(r"/\d+px-", thumb["source"]):
        return thumb["source"]
    return re.sub(r"/\d+px-", f"/{width}px-", thumb["source"], count=1)


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    animals = load_animals()
    if not animals:
        raise HTTPException(status_code=500, detail="content/animals.md has no animals")
    today = _local_date(ctx.tz)
    name = animals[today.toordinal() % len(animals)]
    summary = _summary(name)
    if summary is None:
        # The browser will load the summary straight from Wikipedia instead
        return {"day": today.isoformat(), "name": name, "summary_url": _summary_url(name), "loaded": False}
    return {
        "loaded": True,
        "summary_url": _summary_url(name),
        "day": today.isoformat(),
        "name": name,
        "wikipedia_title": summary.get("title"),
        "description": summary.get("description"),
        "extract": summary.get("extract"),
        "image": _thumbnail(summary, STANDARD_WIDTHS[0]),
        "image_2x": _thumbnail(summary, STANDARD_WIDTHS[1]),  # for high-density screens
        "link": ((summary.get("content_urls") or {}).get("desktop") or {}).get("page"),
    }


register(WidgetDefinition(
    id="animal",
    name="Animal of the day",
    description="A different animal every day, with a photo and facts from Wikipedia.",
    fetch=fetch,
    default_size=(4, 8),
    min_size=(3, 6),
    refresh_seconds=3600,
    enabled_by_default=True,
))
