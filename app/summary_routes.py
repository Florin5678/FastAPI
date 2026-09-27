from datetime import datetime, time
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Email
from app.gmail_routes import _get_user
from app.summarize import get_client, analyze_email, summarize_pending

router = APIRouter()


def _email_dict(e: Email) -> dict:
    return {
        "id": e.id,
        "gmail_id": e.gmail_id,
        "subject": e.subject,
        "sender": e.sender,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "category": e.category,
        "summary": e.summary,
    }


@router.post("/summaries/run")
def run_summaries(email: str = Query(...), limit: int = 10, db: Session = Depends(get_db)):
    """Summarize stored emails that don't have a summary yet (called by the sync workflow)."""
    user = _get_user(db, email)
    return summarize_pending(db, user.id, limit=limit)


@router.get("/summaries/{email_id}")
def get_summary(email_id: int, email: str = Query(...), db: Session = Depends(get_db)):
    """Summary for one stored email (by our DB id). Summarizes it on demand if needed."""
    user = _get_user(db, email)
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
def digest_today(email: str = Query(...), db: Session = Depends(get_db)):
    """Today's emails (UTC), grouped by category."""
    user = _get_user(db, email)
    start = datetime.combine(datetime.utcnow().date(), time.min)
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
