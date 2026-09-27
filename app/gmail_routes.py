import base64
import requests
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Email
from app.gmail_auth import get_valid_access_token

router = APIRouter()

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get_user(db: Session, email: str) -> User:
    """Temporary way to identify 'the user' until you add real session auth.
    Pass ?email=you@gmail.com on requests for now."""
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _get_access_token(db: Session, user: User) -> str:
    """Token problems (none stored, refresh failed) mean the user must log in again."""
    try:
        return get_valid_access_token(db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def _gmail_get(path: str, access_token: str, params: dict) -> dict:
    """GET from the Gmail API, surfacing Google's error instead of a bare 500."""
    response = requests.get(
        f"{GMAIL_API}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        params=params,
        timeout=15,
    )
    if not response.ok:
        try:
            google_error = response.json()
        except ValueError:
            google_error = response.text
        raise HTTPException(
            status_code=502,
            detail={"gmail_status": response.status_code, "gmail_error": google_error},
        )
    return response.json()


def _extract_body(payload: dict) -> str:
    """Gmail bodies are base64url-encoded and can be nested in multipart parts."""
    if payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    return ""


def _received_at(detail: dict) -> datetime:
    """Gmail's internalDate is when the message was received, in ms since the epoch (UTC)."""
    internal_date = detail.get("internalDate")
    if internal_date:
        return datetime.utcfromtimestamp(int(internal_date) / 1000)
    return datetime.utcnow()


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


@router.get("/messages")
def list_messages(email: str = Query(...), max_results: int = 10, db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = _get_access_token(db, user)

    return _gmail_get("/messages", access_token, {"maxResults": max_results})


@router.get("/message/{message_id}")
def get_message(message_id: str, email: str = Query(...), db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = _get_access_token(db, user)

    return _gmail_get(f"/messages/{message_id}", access_token, {"format": "full"})


@router.post("/sync/gmail")
def sync_gmail(email: str = Query(...), max_results: int = 20, db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = _get_access_token(db, user)

    list_data = _gmail_get("/messages", access_token, {"maxResults": max_results})
    message_ids = [m["id"] for m in list_data.get("messages", [])]

    saved = 0
    for msg_id in message_ids:
        # Skip messages we already have
        exists = db.query(Email).filter(Email.gmail_id == msg_id, Email.user_id == user.id).first()
        if exists:
            continue

        detail = _gmail_get(f"/messages/{msg_id}", access_token, {"format": "full"})

        headers = detail.get("payload", {}).get("headers", [])
        subject = _header(headers, "Subject")
        sender = _header(headers, "From")
        body = _extract_body(detail.get("payload", {}))

        email_row = Email(
            user_id=user.id,
            gmail_id=msg_id,
            subject=subject,
            snippet=detail.get("snippet", ""),
            full_body=body,
            sender=sender,
            timestamp=_received_at(detail),
        )
        db.add(email_row)
        saved += 1

    db.commit()
    return {"synced": saved, "checked": len(message_ids)}