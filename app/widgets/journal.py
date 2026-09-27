# Journal widget: write entries with an optional prompt and an optional mood emoji.
#
# Prompts come ONLY from content/journal_prompts.md (repo root) so they can be edited
# freely: one per line as "N. text — *idea*" under "## Section" headings. The file is
# re-read whenever it changes. Entry text is Fernet-encrypted at rest (app/crypto.py).
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.database import get_db
from app.models import JournalEntry, User
from app.core.security import get_current_user, journal_unlock_expires_at, require_journal_unlock
from app.widgets.registry import WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "journal"
# Edit prompts in content/journal_prompts.md (repo root)
PROMPTS_FILE = Path(__file__).resolve().parents[2] / "content" / "journal_prompts.md"
RECENT_PROMPTS_AVOIDED = 30  # don't suggest a prompt answered in the last N entries
PROMPT_LINE = re.compile(r"^(\d+)\.\s+(.+?)\s+—\s+\*(.+)\*\s*$")

_prompts_cache: dict = {"mtime": None, "prompts": {}}


def load_prompts() -> dict[int, dict]:
    """{id: {id, text, idea, source}} from journal_prompts.md, re-read when the file changes."""
    mtime = PROMPTS_FILE.stat().st_mtime
    if _prompts_cache["mtime"] != mtime:
        prompts, section = {}, "Reflection"
        for line in PROMPTS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                heading = line[3:].strip()
                short = re.search(r"\(([^)]+)\)\s*$", heading)  # "Cognitive ... (CBT)" -> "CBT"
                section = short.group(1) if short else heading
                continue
            match = PROMPT_LINE.match(line.strip())
            if match:
                pid = int(match.group(1))
                prompts[pid] = {"id": pid, "text": match.group(2), "idea": match.group(3), "source": section}
        _prompts_cache.update(mtime=mtime, prompts=prompts)
    return _prompts_cache["prompts"]


def pick_prompt(db: Session, user: User, exclude: Optional[int] = None) -> Optional[dict]:
    prompts = load_prompts()
    if not prompts:
        return None
    recent = {
        pid for (pid,) in db.query(JournalEntry.prompt_id)
        .filter(JournalEntry.user_id == user.id, JournalEntry.prompt_id.isnot(None))
        .order_by(JournalEntry.created_at.desc())
        .limit(RECENT_PROMPTS_AVOIDED)
    }
    fresh = [p for pid, p in prompts.items() if pid not in recent and pid != exclude]
    pool = fresh or [p for pid, p in prompts.items() if pid != exclude] or list(prompts.values())
    return random.choice(pool)


def _today(tz: Optional[str]) -> date:
    try:
        return datetime.now(ZoneInfo(tz)).date() if tz else datetime.now(timezone.utc).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _entry_dict(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "day": e.day.isoformat(),
        "prompt_id": e.prompt_id,
        "prompt_text": e.prompt_text,
        "mood": e.mood,
        "body": decrypt(e.body),
        "created_at": e.created_at.isoformat() + "Z" if e.created_at else None,
        "updated_at": e.updated_at.isoformat() + "Z" if e.updated_at else None,
    }


def _streak(db: Session, user: User, today: date) -> int:
    """Consecutive days with at least one entry, ending today (or yesterday)."""
    days = {
        d for (d,) in db.query(JournalEntry.day)
        .filter(JournalEntry.user_id == user.id, JournalEntry.day >= today - timedelta(days=400))
        .distinct()
    }
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    today = _today(ctx.tz)
    todays = (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == user.id, JournalEntry.day == today)
        .order_by(JournalEntry.created_at.desc())
        .all()
    )
    return {
        "day": today.isoformat(),
        "prompt": pick_prompt(db, user),
        # Only moods here: entry text and history need the journal unlock
        "today": [{"id": e.id, "mood": e.mood} for e in todays],
        "total": db.query(JournalEntry).filter(JournalEntry.user_id == user.id).count(),
        "streak": _streak(db, user, today),
    }


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Journal",
    description="Write a journal entry with an optional reflection prompt (CBT, DBT, ACT, Stoicism, existentialism…) and an optional mood emoji. Entries are encrypted.",
    fetch=fetch,
    default_size=(4, 9),
    min_size=(3, 7),
    refresh_seconds=3600,  # the prompt shouldn't change under you while you write
    enabled_by_default=True,
))


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])

ASCII_WORD = re.compile(r"[A-Za-z0-9]")


def _clean_mood(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # Any emoji is fine (including multi-codepoint ones like 🧘🏽‍♂️ or 🇩🇰); plain words aren't
    if len(value) > 16 or ASCII_WORD.search(value):
        raise ValueError("Mood must be an emoji")
    return value


class EntryIn(BaseModel):
    day: date  # the user's local date
    body: str = Field(min_length=1, max_length=20000)
    prompt_id: Optional[int] = None  # null = free writing (prompt removed)
    mood: Optional[str] = None

    @field_validator("mood")
    @classmethod
    def _check_mood(cls, value: Optional[str]) -> Optional[str]:
        return _clean_mood(value)


class EntryPatch(BaseModel):
    body: Optional[str] = Field(None, min_length=1, max_length=20000)
    mood: Optional[str] = None  # send "" or null to clear

    @field_validator("mood")
    @classmethod
    def _check_mood(cls, value: Optional[str]) -> Optional[str]:
        return _clean_mood(value)


@router.get("/prompt")
def another_prompt(
    exclude: Optional[int] = Query(None, description="The prompt currently shown"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prompt = pick_prompt(db, user, exclude=exclude)
    if prompt is None:
        raise HTTPException(status_code=404, detail="No prompts found in journal_prompts.md")
    return prompt


@router.post("/entries")
def add_entry(body: EntryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    if body.day > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(status_code=422, detail="Entries can't be dated in the future")

    prompt = None
    if body.prompt_id is not None:
        prompt = load_prompts().get(body.prompt_id)
        if prompt is None:
            raise HTTPException(status_code=422, detail="That prompt no longer exists; pick another one")

    entry = JournalEntry(
        user_id=user.id,
        day=body.day,
        prompt_id=prompt["id"] if prompt else None,
        prompt_text=prompt["text"] if prompt else None,
        mood=body.mood,
        body=encrypt(body.body.strip()),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _entry_dict(entry)


@router.get("/entries")
def list_entries(
    before_id: Optional[int] = Query(None, description="For paging: entries older than this id"),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_journal_unlock),
    db: Session = Depends(get_db),
):
    """Entries newest first, paged by id."""
    widget_row(db, user, WIDGET_ID)
    query = db.query(JournalEntry).filter(JournalEntry.user_id == user.id)
    if before_id is not None:
        query = query.filter(JournalEntry.id < before_id)
    rows = query.order_by(JournalEntry.id.desc()).limit(limit + 1).all()
    return {
        "entries": [_entry_dict(e) for e in rows[:limit]],
        "has_more": len(rows) > limit,
        "total": db.query(JournalEntry).filter(JournalEntry.user_id == user.id).count(),
    }


def _own_entry(db: Session, user: User, entry_id: int) -> JournalEntry:
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id, JournalEntry.user_id == user.id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryPatch, user: User = Depends(require_journal_unlock), db: Session = Depends(get_db)):
    entry = _own_entry(db, user, entry_id)
    if body.body is not None:
        entry.body = encrypt(body.body.strip())
    if "mood" in body.model_fields_set:
        entry.mood = body.mood
    db.commit()
    db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(require_journal_unlock), db: Session = Depends(get_db)):
    entry = _own_entry(db, user, entry_id)
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}


# ---- Journal history (locked behind a fresh Google sign-in) ----

@router.get("/access")
def access(request: Request, user: User = Depends(get_current_user)):
    """Whether journal history is unlocked in this browser session, and until when."""
    expires = journal_unlock_expires_at(request) if request.session.get("user_id") == user.id else None
    return {
        "unlocked": expires is not None,
        "expires_at": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat() if expires else None,
    }


@router.post("/lock")
def lock(request: Request, user: User = Depends(get_current_user)):
    request.session.pop("journal_unlocked_at", None)
    return {"unlocked": False}


@router.get("/days/{day}")
def get_day(day: date, user: User = Depends(require_journal_unlock), db: Session = Depends(get_db)):
    """All entries written on one day, oldest first (the order they were written)."""
    widget_row(db, user, WIDGET_ID)
    rows = (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == user.id, JournalEntry.day == day)
        .order_by(JournalEntry.created_at, JournalEntry.id)
        .all()
    )
    return {"day": day.isoformat(), "entries": [_entry_dict(e) for e in rows]}


@router.get("/history")
def history(
    end: date = Query(..., description="Last day (inclusive), usually the viewer's today"),
    days: int = Query(30, ge=1, le=3660),
    user: User = Depends(require_journal_unlock),
    db: Session = Depends(get_db),
):
    """Days with entries in the range, newest first: moods, count, words and a preview."""
    widget_row(db, user, WIDGET_ID)
    start = end - timedelta(days=days - 1)
    rows = (
        db.query(JournalEntry)
        .filter(JournalEntry.user_id == user.id, JournalEntry.day >= start, JournalEntry.day <= end)
        .order_by(JournalEntry.day.desc(), JournalEntry.created_at, JournalEntry.id)
        .all()
    )
    by_day: dict[date, list[JournalEntry]] = {}
    for entry in rows:
        by_day.setdefault(entry.day, []).append(entry)

    result = []
    for day, entries in by_day.items():
        bodies = [decrypt(e.body) for e in entries]
        first = " ".join(bodies[0].split())
        result.append({
            "day": day.isoformat(),
            "entries": len(entries),
            "moods": [e.mood for e in entries if e.mood],
            "words": sum(len(b.split()) for b in bodies),
            "preview": first if len(first) <= 90 else first[:89].rsplit(" ", 1)[0] + "…",
        })

    first_day = db.query(func.min(JournalEntry.day)).filter(JournalEntry.user_id == user.id).scalar()
    return {
        "days": result,
        "first_entry_day": first_day.isoformat() if first_day else None,
        "streak": _streak(db, user, end),
        "total": db.query(JournalEntry).filter(JournalEntry.user_id == user.id).count(),
    }


@router.get("/moods")
def monthly_moods(
    end: date = Query(..., description="The viewer's today; its month is the newest one"),
    months: int = Query(6, ge=1, le=36),
    user: User = Depends(require_journal_unlock),
    db: Session = Depends(get_db),
):
    """Mood emoji per month, newest month first: counts per emoji and the moods of each day."""
    widget_row(db, user, WIDGET_ID)
    # First day of the oldest month in range
    y, m = end.year, end.month - (months - 1)
    while m <= 0:
        y, m = y - 1, m + 12
    start = date(y, m, 1)

    rows = (
        db.query(JournalEntry.day, JournalEntry.mood)
        .filter(JournalEntry.user_id == user.id, JournalEntry.day >= start, JournalEntry.day <= end)
        .order_by(JournalEntry.day, JournalEntry.created_at, JournalEntry.id)
        .all()
    )

    result = []
    y, m = end.year, end.month
    for _ in range(months):
        key = f"{y:04d}-{m:02d}"
        in_month = [(d, mood) for d, mood in rows if d.year == y and d.month == m]
        counts: dict[str, int] = {}
        days: dict[str, list[str]] = {}
        for d, mood in in_month:
            days.setdefault(d.isoformat(), [])
            if mood:
                counts[mood] = counts.get(mood, 0) + 1
                days[d.isoformat()].append(mood)
        result.append({
            "month": key,
            "entries": len(in_month),
            "days_logged": len(days),
            "moods": [{"emoji": e, "count": c} for e, c in sorted(counts.items(), key=lambda kv: -kv[1])],
            "days": days,  # "YYYY-MM-DD" -> moods that day, in writing order ([] = entries without a mood)
        })
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return {"months": result}
