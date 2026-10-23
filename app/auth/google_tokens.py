"""Google access tokens for API calls (Gmail, Calendar): decrypt, refresh when expired.
When renewing fails (the sign-in expired or was revoked), the reason is kept on the token row
so the dashboard can say so and offer to reconnect (google_status), instead of every widget
just looking "not connected"."""
import os
import requests
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Token
from app.core.crypto import encrypt, decrypt

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _google_row(db: Session, user_id: int) -> Optional[Token]:
    return db.query(Token).filter(Token.user_id == user_id, Token.provider == "google").first()


def _fail(db: Session, token_row: Token, reason: str) -> None:
    """Remember why Google access stopped (keeping when it first stopped), then raise."""
    if token_row.last_error is None:
        token_row.last_error_at = datetime.utcnow()
    token_row.last_error = reason[:500]
    db.commit()
    raise ValueError(reason)


def google_status(db: Session, user_id: int) -> dict:
    """Whether the dashboard can use the user's Google sign-in (Gmail, Calendar), and if not, why."""
    row = _google_row(db, user_id)
    if row is None:
        return {"ok": False, "problem": "Not signed in with Google", "since": None}
    if row.last_error:
        return {"ok": False, "problem": row.last_error,
                "since": row.last_error_at.isoformat() + "Z" if row.last_error_at else None}
    return {"ok": True, "problem": None, "since": None}


def get_valid_access_token(db: Session, user_id: int) -> str:
    """
    Returns a usable (decrypted) Google access token for this user.
    Refreshes it first if it's expired or about to expire.
    """
    token_row = _google_row(db, user_id)

    if token_row is None:
        raise ValueError("No Google token found for this user. They need to log in again.")

    # Refresh a bit early (60s buffer) rather than right at the edge
    is_expired = (
        token_row.expires_at is None
        or token_row.expires_at <= datetime.utcnow() + timedelta(seconds=60)
    )

    if not is_expired:
        return decrypt(token_row.access_token)

    # Expired - use the refresh token to get a new access token
    refresh_token = decrypt(token_row.refresh_token) if token_row.refresh_token else None
    if not refresh_token:
        _fail(db, token_row, "Google didn't give the dashboard lasting access. Sign in again to reconnect.")

    response = requests.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    new_tokens = response.json()

    new_access_token = new_tokens.get("access_token")
    if not new_access_token:
        if new_tokens.get("error") == "invalid_grant":
            # The refresh token is dead: only signing in again helps
            google = new_tokens.get("error_description") or "invalid_grant"
            _fail(db, token_row, f"Your Google sign-in expired or was revoked (Google: {google}). Sign in again to reconnect.")
        raise ValueError(f"Couldn't renew the Google sign-in: {new_tokens.get('error_description') or new_tokens.get('error') or response.status_code}")

    expires_in = new_tokens.get("expires_in", 3600)
    token_row.access_token = encrypt(new_access_token)
    token_row.expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
    token_row.last_error = token_row.last_error_at = None
    db.commit()

    return new_access_token
