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


def _header(headers: list, name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


@router.get("/messages")
def list_messages(email: str = Query(...), max_results: int = 10, db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = get_valid_access_token(db, user.id)

    response = requests.get(
        f"{GMAIL_API}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"maxResults": max_results},
    )
    response.raise_for_status()
    return response.json()


@router.get("/message/{message_id}")
def get_message(message_id: str, email: str = Query(...), db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = get_valid_access_token(db, user.id)

    response = requests.get(
        f"{GMAIL_API}/messages/{message_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "full"},
    )
    response.raise_for_status()
    return response.json()


@router.post("/sync/gmail")
def sync_gmail(email: str = Query(...), max_results: int = 20, db: Session = Depends(get_db)):
    user = _get_user(db, email)
    access_token = get_valid_access_token(db, user.id)

    list_response = requests.get(
        f"{GMAIL_API}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"maxResults": max_results},
    )
    list_response.raise_for_status()
    message_ids = [m["id"] for m in list_response.json().get("messages", [])]

    saved = 0
    for msg_id in message_ids:
        # Skip messages we already have
        exists = db.query(Email).filter(Email.gmail_id == msg_id, Email.user_id == user.id).first()
        if exists:
            continue

        detail_response = requests.get(
            f"{GMAIL_API}/messages/{msg_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "full"},
        )
        detail_response.raise_for_status()
        detail = detail_response.json()

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
            timestamp=datetime.utcnow(),  # swap for parsed header date later if you want accuracy
        )
        db.add(email_row)
        saved += 1

    db.commit()
    return {"synced": saved, "checked": len(message_ids)}