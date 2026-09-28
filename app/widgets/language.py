# Language widget: Spanish and Danish flashcards with spaced repetition.
#
# Words live in content/vocab/<language>.md ("- word — meaning" lines, editable). Each
# user's progress per word is a VocabCard row. Scheduling is a simplified SM-2:
#   again -> back in today's queue (ease -0.2), good -> 1 day, 3 days, then interval x ease,
#   easy -> longer intervals (ease +0.15). New words are introduced in file order,
#   up to `new_per_day` per local day. Days are the viewer's local dates.
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import User, VocabCard
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "language"
VOCAB_DIR = Path(__file__).resolve().parents[2] / "content" / "vocab"
LANGUAGES = {
    "Spanish": {"key": "spanish", "speech": "es-ES"},  # speech: browser text-to-speech language
    "Danish": {"key": "danish", "speech": "da-DK"},
}
WORD_LINE = re.compile(r"^-\s+(.+?)\s+—\s+(.+?)\s*$")
MASTERED_DAYS = 21  # a word counts as "learned" once its interval reaches this
MIN_EASE = 1.3

_vocab_cache: dict[str, tuple[float, list[tuple[str, str]]]] = {}


def load_words(language_key: str) -> list[tuple[str, str]]:
    """[(word, meaning)] in file order, re-read when the file changes."""
    path = VOCAB_DIR / f"{language_key}.md"
    mtime = path.stat().st_mtime
    cached = _vocab_cache.get(language_key)
    if not cached or cached[0] != mtime:
        words = [(m.group(1), m.group(2)) for m in map(WORD_LINE.match, path.read_text(encoding="utf-8").splitlines()) if m]
        _vocab_cache[language_key] = (mtime, words)
    return _vocab_cache[language_key][1]


def _language(settings: dict) -> tuple[str, dict]:
    name = settings["language"] if settings["language"] in LANGUAGES else "Spanish"
    return name, LANGUAGES[name]


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    name, lang = _language(settings)
    today = local_today(ctx.tz)
    words = load_words(lang["key"])
    meanings = dict(words)

    cards = db.query(VocabCard).filter(VocabCard.user_id == user.id, VocabCard.language == lang["key"])
    due_cards = (
        cards.filter(VocabCard.due <= today, VocabCard.word.in_(meanings))
        .order_by(VocabCard.due, VocabCard.last_reviewed_at.nullsfirst())
        .all()
    )
    known = {w for (w,) in cards.with_entities(VocabCard.word)}
    introduced_today = cards.filter(VocabCard.introduced_on == today).count()
    new_left = max(0, settings["new_per_day"] - introduced_today)
    unseen = [w for w, _ in words if w not in known]

    if due_cards:
        card = {"word": due_cards[0].word, "is_new": False}
    elif new_left and unseen:
        card = {"word": unseen[0], "is_new": True}
    else:
        card = None
    if card:
        card["meaning"] = meanings[card["word"]]

    return {
        "language": name,
        "languages": list(LANGUAGES),
        "speech_lang": lang["speech"],
        "today": today.isoformat(),
        "card": card,
        "due": len(due_cards),
        "new_left": min(new_left, len(unseen)),
        "learned": cards.filter(VocabCard.interval_days >= MASTERED_DAYS).count(),
        "seen": len(known),
        "total": len(words),
    }


def brief(data: dict, limit: int | None = None) -> str:
    return (
        f"{data['language']}: {data['due']} review(s) due, {data['new_left']} new word(s) left today, "
        f"{data['learned']} of {data['total']} words learned."
    )


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Language",
    description="Spanish and Danish flashcards with spaced repetition: a few new words a day, reviews when they're due.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 8),
    min_size=(3, 6),
    refresh_seconds=1800,
    enabled_by_default=True,
    config_fields=(
        ConfigField("language", "Language", "select", default="Spanish", options=list(LANGUAGES)),
        ConfigField("new_per_day", "New words per day", "number", default=10, min=1, max=50),
    ),
))


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class ReviewIn(BaseModel):
    language: str  # "Spanish" | "Danish"
    word: str
    grade: Literal["again", "good", "easy"]
    day: date  # the user's local date


def schedule(card: VocabCard, grade: str, day: date) -> None:
    """Simplified SM-2 update of one card for a review on `day`."""
    if grade == "again":
        if card.reps:
            card.lapses += 1
        card.reps = 0
        card.interval_days = 0
        card.ease = max(MIN_EASE, card.ease - 0.2)
    elif grade == "good":
        card.interval_days = 1 if card.reps == 0 else 3 if card.reps == 1 else round(card.interval_days * card.ease)
        card.reps += 1
    else:  # easy
        card.interval_days = 3 if card.reps == 0 else round(max(card.interval_days, 1) * card.ease * 1.3)
        card.ease += 0.15
        card.reps += 1
    card.due = day + timedelta(days=card.interval_days)
    card.last_reviewed_at = datetime.utcnow()


@router.post("/review")
def review(body: ReviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    if body.language not in LANGUAGES:
        raise HTTPException(status_code=422, detail="Unknown language")
    if abs((body.day - datetime.now(timezone.utc).date()).days) > 1:
        raise HTTPException(status_code=422, detail="Reviews can only be recorded for today")
    key = LANGUAGES[body.language]["key"]
    if body.word not in dict(load_words(key)):
        raise HTTPException(status_code=404, detail="That word isn't in the list anymore")

    card = (
        db.query(VocabCard)
        .filter(VocabCard.user_id == user.id, VocabCard.language == key, VocabCard.word == body.word)
        .first()
    )
    if card is None:
        card = VocabCard(user_id=user.id, language=key, word=body.word, interval_days=0, ease=2.5,
                         due=body.day, reps=0, lapses=0, introduced_on=body.day)
        db.add(card)
    schedule(card, body.grade, body.day)
    db.commit()
    return {"word": card.word, "due": card.due.isoformat(), "interval_days": card.interval_days}
