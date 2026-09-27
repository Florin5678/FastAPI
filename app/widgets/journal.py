# Journal widget: write entries with an optional prompt and an optional mood emoji.
#
# Prompts come ONLY from journal_prompts.md (next to this file) so they can be edited
# freely: one per line as "N. text — *idea*" under "## Section" headings. The file is
# re-read whenever it changes. Entry text is Fernet-encrypted at rest (app/crypto.py).
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.crypto import decrypt, encrypt
from app.database import get_db
from app.models import JournalEntry, User
from app.security import get_current_user
from app.widgets.registry import WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "journal"
PROMPTS_FILE = Path(__file__).with_name("journal_prompts.md")
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
        "today": [
            {"id": e.id, "mood": e.mood, "prompt_text": e.prompt_text, "created_at": e.created_at.isoformat() + "Z"}
            for e in todays
        ],
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
    user: User = Depends(get_current_user),
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
def update_entry(entry_id: int, body: EntryPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = _own_entry(db, user, entry_id)
    if body.body is not None:
        entry.body = encrypt(body.body.strip())
    if "mood" in body.model_fields_set:
        entry.mood = body.mood
    db.commit()
    db.refresh(entry)
    return _entry_dict(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = _own_entry(db, user, entry_id)
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}
