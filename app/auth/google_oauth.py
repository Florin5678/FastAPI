import os
import secrets
import requests
from typing import Optional
from urllib.parse import urlencode
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException
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
def google_login(request: Request):
    # Random state ties the callback to this browser (protects against login CSRF)
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out"}


@router.get("/callback")
def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if error:
        # e.g. the user clicked "Cancel" on Google's consent screen
        return RedirectResponse("/?" + urlencode({"login_error": error}))

    expected_state = request.session.pop("oauth_state", None)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid login attempt - start again from the sign-in page")

    # Exchange code for tokens
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    token_response = requests.post(TOKEN_URL, data=data, timeout=15)
    tokens = token_response.json()

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")  # seconds, usually 3600

    # Fetch user info
    user_info = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    ).json()

    google_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name")

    if not access_token or not google_id or not email:
        # Never create a half-empty user row (this is what caused the early IntegrityError)
        return RedirectResponse("/?" + urlencode({"login_error": "google_login_failed"}))

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

    # Signed-in from now on: the frontend is served from this same app
    request.session["user_id"] = user.id
    return RedirectResponse("/")
