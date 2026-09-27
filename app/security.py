# Who is making this request: a signed-in browser (session cookie) or the
# sync workflow (X-API-Key header + ?email=).
import os
import secrets
from typing import Optional
from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"
# Set it as API_KEY on Render (and as a GitHub Actions secret for the sync workflow).
API_KEY = os.getenv("API_KEY")


def get_current_user(
    request: Request,
    email: Optional[str] = Query(default=None, description="Only used with X-API-Key"),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    user_id = request.session.get("user_id")
    if user_id is not None:
        user = db.get(User, user_id)
        if user is not None:
            return user
        request.session.clear()  # user row is gone - stale cookie

    if x_api_key is not None:
        # Fail closed: never serve mail data just because the key wasn't configured
        if not API_KEY:
            raise HTTPException(status_code=503, detail="API_KEY is not configured on the server")
        if not secrets.compare_digest(x_api_key, API_KEY):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
        if not email:
            raise HTTPException(status_code=400, detail="?email= is required when using X-API-Key")
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    raise HTTPException(status_code=401, detail="Not signed in")
