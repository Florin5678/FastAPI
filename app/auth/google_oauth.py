import os
import requests
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Token
from app.crypto import encrypt

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPE = "https://www.googleapis.com/auth/gmail.readonly email profile"


@router.get("/login")
def google_login():
    url = (
        f"{AUTH_URL}"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={SCOPE}"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return RedirectResponse(url)


@router.get("/callback")
def google_callback(request: Request, code: str, db: Session = Depends(get_db)):
    # Exchange code for tokens
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    token_response = requests.post(TOKEN_URL, data=data)
    tokens = token_response.json()

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")  # seconds, usually 3600

    # Fetch user info
    user_info = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"}
    ).json()

    google_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name")

    # --- Save/update the user ---
    user = db.query(User).filter(User.google_id == google_id).first()
    if user is None:
        user = User(google_id=google_id, email=email, name=name)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.email = email
        user.name = name
        db.commit()

    # --- Save/update the token for this user + provider ---
    expires_at = None
    if expires_in:
        expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))

    token_row = (
        db.query(Token)
        .filter(Token.user_id == user.id, Token.provider == "google")
        .first()
    )

    if token_row is None:
        token_row = Token(
            user_id=user.id,
            provider="google",
            access_token=encrypt(access_token),
            refresh_token=encrypt(refresh_token) if refresh_token else None,
            expires_at=expires_at,
        )
        db.add(token_row)
    else:
        token_row.access_token = encrypt(access_token)
        # Google only sends a refresh_token the first time you consent.
        # Don't overwrite an existing one with None on later logins.
        if refresh_token:
            token_row.refresh_token = encrypt(refresh_token)
        token_row.expires_at = expires_at

    db.commit()

    return {
        "message": "Google OAuth successful",
        "user": {"email": email, "name": name},
    }