from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

router = APIRouter()


@router.get("/debug/users")
def list_users(db: Session = Depends(get_db)):
    """TEMPORARY - remove this route once debugging is done. Don't leave it in production."""
    users = db.query(User).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "google_id": u.google_id,
            "created_at": str(u.created_at),
        }
        for u in users
    ]