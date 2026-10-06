# Gmail changes for Claude (connector tools): drafts, sending, archiving, read/unread, trash.
# Needs the gmail.modify + gmail.compose scopes (one sign-in after they were added); the
# dashboard itself still only reads mail. Messages are addressed by the dashboard's stored
# email id (emails.gmail_id is Gmail's message id).
import base64
from email.message import EmailMessage
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.google_tokens import get_valid_access_token
from app.core.google_api import NeedsSetup, google_request
from app.models import Email, User

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
NO_PERMISSION = ("The dashboard isn't allowed to send or change your Gmail yet: sign out of the dashboard and sign "
                 "in again, and allow it to manage your email.")


def _call(db: Session, user: User, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None):
    try:
        token = get_valid_access_token(db, user.id)
        return google_request(method, f"{GMAIL_API}{path}", token, params=params, body=body, service="Gmail",
                              not_found="That email wasn't found in Gmail (it may have been deleted)")
    except (NeedsSetup, ValueError) as e:
        raise HTTPException(status_code=403, detail=NO_PERMISSION) from e


def stored_email(db: Session, user: User, email_id: int) -> Email:
    row = db.query(Email).filter(Email.id == email_id, Email.user_id == user.id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Email not found (ids from list_emails)")
    return row


def _raw(user: User, to: str, subject: str, body: str, headers: Optional[dict] = None) -> str:
    message = EmailMessage()
    message["From"] = user.email
    message["To"] = to
    message["Subject"] = subject
    for key, value in (headers or {}).items():
        message[key] = value
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def compose(db: Session, user: User, body: str, email_id: Optional[int] = None, to: Optional[str] = None,
            subject: Optional[str] = None) -> dict:
    """The Gmail message to send or save as a draft: a reply in the same thread (email_id), or a new
    email (to + subject)."""
    if email_id is None:
        if not to or not subject:
            raise HTTPException(status_code=422, detail="A new email needs `to` and `subject` (or give email_id to reply)")
        return {"raw": _raw(user, to, subject, body), "to": to, "subject": subject}
    original = _call(db, user, "GET", f"/messages/{stored_email(db, user, email_id).gmail_id}",
                     params={"format": "metadata", "metadataHeaders": ["From", "Reply-To", "Subject", "Message-ID", "References"]})
    head = {h["name"].lower(): h["value"] for h in original.get("payload", {}).get("headers", [])}
    original_subject = head.get("subject", "")
    reply_subject = subject or (original_subject if original_subject.lower().startswith("re:") else f"Re: {original_subject}")
    reply_to = to or head.get("reply-to") or head.get("from", "")
    threading = {}
    if head.get("message-id"):
        threading = {"In-Reply-To": head["message-id"],
                     "References": f"{head.get('references', '')} {head['message-id']}".strip()}
    return {"raw": _raw(user, reply_to, reply_subject, body, threading), "threadId": original.get("threadId"),
            "to": reply_to, "subject": reply_subject}


def send(db: Session, user: User, message: dict) -> dict:
    payload = {"raw": message["raw"], **({"threadId": message["threadId"]} if message.get("threadId") else {})}
    return _call(db, user, "POST", "/messages/send", payload)


def create_draft(db: Session, user: User, message: dict) -> dict:
    payload = {"raw": message["raw"], **({"threadId": message["threadId"]} if message.get("threadId") else {})}
    return _call(db, user, "POST", "/drafts", {"message": payload})


def delete_draft(db: Session, user: User, draft_id: str) -> None:
    _call(db, user, "DELETE", f"/drafts/{draft_id}")


def change_labels(db: Session, user: User, gmail_id: str, add: Optional[list[str]] = None, remove: Optional[list[str]] = None) -> None:
    _call(db, user, "POST", f"/messages/{gmail_id}/modify", {"addLabelIds": add or [], "removeLabelIds": remove or []})


def trash(db: Session, user: User, gmail_id: str) -> None:
    _call(db, user, "POST", f"/messages/{gmail_id}/trash")


def untrash(db: Session, user: User, gmail_id: str) -> None:
    _call(db, user, "POST", f"/messages/{gmail_id}/untrash")
