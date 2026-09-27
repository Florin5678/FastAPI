"""The signed-in user's account info for the frontend."""
from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.mail.summarize import get_client
from app.models import User

router = APIRouter()


@router.get("/api/me")
def me(user: User = Depends(get_current_user)):
    return {
        "email": user.email,
        "name": user.name,
        "summaries_enabled": get_client() is not None,
    }
