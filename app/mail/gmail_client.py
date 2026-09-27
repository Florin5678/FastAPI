import os
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models import Token
from app.core.crypto import encrypt, decrypt

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_valid_access_token(db: Session, user_id: int) -> str:
    """
    Returns a usable (decrypted) Google access token for this user.
    Refreshes it first if it's expired or about to expire.
    """
    token_row = (
        db.query(Token)
        .filter(Token.user_id == user_id, Token.provider == "google")
        .first()
    )

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
    refresh_token = decrypt(token_row.refresh_token)
    if not refresh_token:
        raise ValueError("Access token expired and no refresh token is available. User must log in again.")

    response = requests.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }, timeout=15)
    new_tokens = response.json()

    new_access_token = new_tokens.get("access_token")
    if not new_access_token:
        raise ValueError(f"Failed to refresh token: {new_tokens}")

    expires_in = new_tokens.get("expires_in", 3600)
    token_row.access_token = encrypt(new_access_token)
    token_row.expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in))
    db.commit()

    return new_access_token