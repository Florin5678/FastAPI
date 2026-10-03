import base64
import html
import re
import requests
from datetime import datetime
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.models import User, Email
from app.auth.google_tokens import get_valid_access_token
from app.core.security import get_sync_user
from app.mail.summarize import summarize_pending

router = APIRouter()
logger = logging.getLogger(__name__)

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


def _get_access_token(db: Session, user: User) -> str:
    """Token problems (none stored, refresh failed) mean the user must log in again."""
    try:
        return get_valid_access_token(db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


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


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")


def _find_part(payload: dict, mime_type: str) -> str:
    """Depth-first search for the first part of this type (bodies can be nested several levels deep)."""
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []):
        found = _find_part(part, mime_type)
        if found:
            return found
    return ""


def _html_to_text(html_body: str) -> str:
    text = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html_body)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _extract_body(payload: dict) -> str:
    """Gmail bodies are base64url-encoded, often nested in multipart parts. Prefer plain text."""
    plain = _find_part(payload, "text/plain")
    if plain:
        return plain
    html_body = _find_part(payload, "text/html")
    if html_body:
        return _html_to_text(html_body)
    # Single-part message with no declared text type
    if payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
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


def _summarize_new(user_id: int) -> None:
    """Summarize the emails a scheduled sync just stored (after the response, so the
    scheduler's request doesn't time out)."""
    db = SessionLocal()
    try:
        summarize_pending(db, user_id, limit=20)
    except Exception:
        logger.warning("Summarizing after the scheduled sync failed", exc_info=True)
    finally:
        db.close()


@router.post("/sync/gmail")
def sync_gmail(
    background: BackgroundTasks,
    user: User = Depends(get_sync_user),
    max_results: int = 20,
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Store new Gmail messages. Called by "Sync now" (which then summarizes itself, to
    show the count) and every 10 minutes by cron-job.org with X-API-Key, in which case
    the new emails are summarized in the background and the morning brief is written
    when it's due."""
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
    if x_api_key:
        if saved:
            background.add_task(_summarize_new, user.id)
        from app.widgets.assistant_chat import maybe_morning_brief  # (here: avoids an import cycle)
        background.add_task(maybe_morning_brief, user.id)
    return {"synced": saved, "checked": len(message_ids)}
