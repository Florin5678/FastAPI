# News widget: latest headlines per topic from public RSS feeds (free, no keys).
# Shows headline + short excerpt + link to the source; never the full article.
# Feeds are cached per topic for CACHE_SECONDS, so each source is hit a few times an hour at most.
import html
import re
import time
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser
import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

CACHE_SECONDS = 20 * 60
USER_AGENT = "Mozilla/5.0 (personal dashboard RSS reader)"

# All verified 2026-09-27 (status 200, dated entries)
TOPICS: dict[str, list[tuple[str, str]]] = {
    "AI": [
        ("MIT Technology Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
        ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ],
    "Tech": [
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("WIRED", "https://www.wired.com/feed/rss"),
    ],
    "Science": [
        ("ScienceDaily", "https://www.sciencedaily.com/rss/top/science.xml"),
        ("Quanta Magazine", "https://www.quantamagazine.org/feed/"),
        ("Nature", "https://www.nature.com/nature.rss"),
    ],
    "World": [
        ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
    ],
    "Europe": [
        ("POLITICO Europe", "https://www.politico.eu/feed/"),
        ("The Guardian", "https://www.theguardian.com/world/europe-news/rss"),
        ("Euronews", "https://www.euronews.com/rss?level=theme&name=news"),
    ],
    "Romania": [
        ("Digi24", "https://www.digi24.ro/rss"),
        ("HotNews", "https://www.hotnews.ro/rss"),
        ("G4Media", "https://www.g4media.ro/feed"),
    ],
}

ALL = "All"  # every topic, merged chronologically
TOPIC_CHOICES = [ALL, *TOPICS]

_cache: dict[str, tuple[float, list, list]] = {}  # topic -> (fetched_at, items, failed sources)


def _clean(text: str, limit: int = 220) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _read_feed(source: str, url: str) -> list[dict]:
    response = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    items = []
    for entry in feedparser.parse(response.content).entries[:20]:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if not entry.get("link") or not entry.get("title"):
            continue
        items.append({
            "title": _clean(entry.title, 200),
            "link": entry.link,
            "source": source,
            "published": (
                datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).isoformat() if parsed else None
            ),
            "excerpt": _clean(entry.get("summary", "")),
        })
    return items


def _topic_items(topic: str) -> tuple[list, list]:
    cached = _cache.get(topic)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]

    items, failed = [], []
    with ThreadPoolExecutor(max_workers=len(TOPICS[topic])) as pool:
        futures = {pool.submit(_read_feed, name, url): name for name, url in TOPICS[topic]}
        for future, name in futures.items():
            try:
                items.extend(future.result())
            except Exception:
                failed.append(name)

    if not items:
        if cached:
            return cached[1], cached[2]  # stale beats nothing
        raise HTTPException(status_code=502, detail="Couldn't reach any news source. Try again in a minute.")

    for item in items:
        item["topic"] = topic
    unique = _newest_unique(items)
    _cache[topic] = (time.time(), unique, failed)
    return unique, failed


def _newest_unique(items: list[dict]) -> list[dict]:
    """Newest first (undated last), dropping repeated headlines across sources/topics."""
    seen, unique = set(), []
    for item in sorted(items, key=lambda i: i["published"] or "", reverse=True):
        key = item["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _all_items() -> tuple[list, list]:
    """Every topic merged in one chronological list (each topic keeps its own cache)."""
    items, failed = [], []
    with ThreadPoolExecutor(max_workers=len(TOPICS)) as pool:
        for topic, future in [(t, pool.submit(_topic_items, t)) for t in TOPICS]:
            try:
                topic_items, topic_failed = future.result()
                items.extend(topic_items)
                failed.extend(topic_failed)
            except HTTPException:
                failed.append(f"all {topic} sources")
    if not items:
        raise HTTPException(status_code=502, detail="Couldn't reach any news source. Try again in a minute.")
    return _newest_unique(items), sorted(set(failed))


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    topic = settings["topic"] if settings["topic"] in TOPIC_CHOICES else "AI"
    if topic == ALL:
        items, failed = _all_items()
        sources = sorted({name for feeds in TOPICS.values() for name, _ in feeds})
    else:
        items, failed = _topic_items(topic)
        sources = [name for name, _ in TOPICS[topic]]
    return {
        "topic": topic,
        "topics": TOPIC_CHOICES,
        "sources": sources,
        "unavailable": failed,
        "items": items[: settings["max_items"]],
    }


def brief(data: dict) -> str:
    lines = [f"Latest {data['topic']} headlines:"]
    lines += [f"- {i['title']} ({i['source']})" for i in data["items"][:6]]
    return "\n".join(lines)


register(WidgetDefinition(
    id="news",
    name="News",
    description="Latest headlines on AI, tech, science, world, European and Romanian news from public RSS feeds.",
    fetch=fetch,
    brief=brief,
    default_size=(8, 8),
    min_size=(4, 6),
    refresh_seconds=900,
    enabled_by_default=True,
    config_fields=(
        ConfigField("topic", "Topic", "select", default="AI", options=TOPIC_CHOICES),
        ConfigField("max_items", "Headlines to show", "number", default=12, min=3, max=30),
    ),
))
