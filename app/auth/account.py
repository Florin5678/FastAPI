"""The signed-in user's account info for the frontend."""
from fastapi import APIRouter, Depends

from sqlalchemy.orm import Session

from app.auth.google_tokens import google_status
from app.core.database import get_db
from app.core.security import get_current_user
from app.mail.summarize import get_client
from app.models import User

router = APIRouter()


@router.get("/api/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "email": user.email,
        "name": user.name,
        "summaries_enabled": get_client() is not None,
        "google": google_status(db, user.id),  # can the dashboard reach Gmail / Calendar
    }
