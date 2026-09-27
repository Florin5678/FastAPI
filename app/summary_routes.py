from datetime import datetime, time, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Email, User
from app.security import get_current_user
from app.summarize import get_client, analyze_email, summarize_pending

router = APIRouter()


def _email_dict(e: Email, include_body: bool = False) -> dict:
    data = {
        "id": e.id,
        "gmail_id": e.gmail_id,
        "subject": e.subject,
        "sender": e.sender,
        "snippet": e.snippet,
        "timestamp": e.timestamp.isoformat() + "Z" if e.timestamp else None,
        "category": e.category,
        "summary": e.summary,
    }
    if include_body:
        data["full_body"] = e.full_body
    return data


@router.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name,
        "summaries_enabled": get_client() is not None,
    }


@router.get("/emails")
def list_emails(
    category: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stored emails, newest first, optionally filtered by category."""
    query = db.query(Email).filter(Email.user_id == user.id)
    if category:
        query = query.filter(Email.category == category)
    total = query.count()
    rows = query.order_by(Email.timestamp.desc()).offset(offset).limit(min(limit, 200)).all()
    return {"total": total, "emails": [_email_dict(e) for e in rows]}


@router.get("/emails/{email_id}")
def get_email(email_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(Email).filter(Email.id == email_id, Email.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return _email_dict(row, include_body=True)


@router.post("/summaries/run")
def run_summaries(limit: int = 10, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Summarize stored emails that don't have a summary yet (called by the sync workflow)."""
    return summarize_pending(db, user.id, limit=limit)


@router.get("/summaries/{email_id}")
def get_summary(email_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Summary for one stored email (by our DB id). Summarizes it on demand if needed."""
    row = db.query(Email).filter(Email.id == email_id, Email.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found")

    if row.summary is None:
        client = get_client()
        if client is None:
            raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not set")
        analysis = analyze_email(client, row)
        if analysis is not None:
            row.category, row.summary = analysis.category, analysis.summary
            db.commit()

    return _email_dict(row)


@router.get("/digest/today")
def digest_today(
    since: Optional[datetime] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Today's emails grouped by category. Pass ?since= (the viewer's local midnight,
    ISO 8601 with offset) to use their timezone; defaults to UTC midnight."""
    if since is None:
        start = datetime.combine(datetime.utcnow().date(), time.min)
    elif since.tzinfo is not None:
        start = since.astimezone(timezone.utc).replace(tzinfo=None)  # DB stores naive UTC
    else:
        start = since
    rows = (
        db.query(Email)
        .filter(Email.user_id == user.id, Email.timestamp >= start)
        .order_by(Email.timestamp.desc())
        .all()
    )

    by_category: dict = {}
    for e in rows:
        by_category.setdefault(e.category or "unsummarized", []).append(_email_dict(e))

    return {"date": start.date().isoformat(), "total": len(rows), "categories": by_category}
