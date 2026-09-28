# OAuth 2.0 for the Claude connector: the dashboard is its own authorization server.
#
# Flow (claude.ai, Claude Desktop/mobile or Claude Code):
#   1. Claude calls /mcp without a token -> 401 pointing at our metadata
#   2. Claude registers itself (Dynamic Client Registration, POST /register)
#   3. The user's browser goes to /authorize -> our consent page /oauth/consent,
#      which uses the normal dashboard sign-in (Google) and asks "Allow Claude?"
#   4. Allow -> a one-time code back to Claude's callback -> /token swaps it (with the
#      PKCE verifier) for an access token (1 h) and a rotating refresh token
# The MCP SDK implements the endpoints and checks (PKCE, redirect URIs, client auth);
# this module stores clients, codes and tokens (hashed) and renders the consent page.
import hashlib
import hmac
import html
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.database import SessionLocal, get_db
from app.models import ConnectorClient, ConnectorToken, User

SCOPE = "dashboard"
ACCESS_SECONDS = 3600
REFRESH_DAYS = 60
CODE_SECONDS = 300
CONSENT_SECONDS = 600  # how long the consent page stays valid
MAX_CLIENTS = 200  # registrations are open (DCR), so keep the table bounded
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")


def public_url() -> str:
    """This app's public origin, e.g. https://fastapi-oocd.onrender.com (PUBLIC_URL, or
    taken from GOOGLE_REDIRECT_URI so no extra setting is needed)."""
    explicit = os.getenv("PUBLIC_URL")
    if explicit:
        return explicit.rstrip("/")
    redirect = os.getenv("GOOGLE_REDIRECT_URI")
    if redirect:
        parsed = urlparse(redirect)
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:8000"


def _ts(moment: datetime) -> int:
    """Unix time of a naive UTC datetime (as stored in the database)."""
    return int(moment.replace(tzinfo=timezone.utc).timestamp())


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _consent_serializer() -> URLSafeTimedSerializer:
    secret = hmac.new(os.environ["ENCRYPTION_KEY"].encode(), b"connector-consent", hashlib.sha256).hexdigest()
    return URLSafeTimedSerializer(secret, salt="connector-consent")


def allowed_redirect(uri: str) -> bool:
    """claude.ai's callback, or a loopback address on any port (Claude Code, local tools)."""
    if uri == CLAUDE_CALLBACK:
        return True
    parsed = urlparse(uri)
    return parsed.scheme == "http" and parsed.hostname in LOOPBACK_HOSTS


def redirect_label(uri: str) -> str:
    host = urlparse(uri).hostname or uri
    return "Claude Code on this computer" if host in LOOPBACK_HOSTS else host


class ConnectorClientInfo(OAuthClientInformationFull):
    """Registered client whose loopback redirect URIs match on any port (Claude Code
    picks a new port per session, RFC 8252 7.3)."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and self.redirect_uris:
            wanted = urlparse(str(redirect_uri))
            if wanted.hostname in LOOPBACK_HOSTS:
                for registered in self.redirect_uris:
                    have = urlparse(str(registered))
                    if have.hostname == wanted.hostname and have.path == wanted.path and have.scheme == wanted.scheme:
                        return redirect_uri
                raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")
        return super().validate_redirect_uri(redirect_uri)


def _new_token(db: Session, kind: str, grant_id: str, client_id: str, user_id: int, data: dict, seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    db.add(ConnectorToken(
        kind=kind, token_hash=_hash(token), grant_id=grant_id, client_id=client_id, user_id=user_id,
        data=data, expires_at=datetime.utcnow() + timedelta(seconds=seconds),
    ))
    return token


def _find(db: Session, kind: str, token: str) -> Optional[ConnectorToken]:
    row = db.query(ConnectorToken).filter(ConnectorToken.token_hash == _hash(token), ConnectorToken.kind == kind).first()
    if row is None or row.expires_at <= datetime.utcnow():
        return None
    return row


def _issue(db: Session, client_id: str, user_id: int, grant_id: str, scopes: list[str], resource: Optional[str]) -> OAuthToken:
    data = {"scopes": scopes, "resource": resource}
    access = _new_token(db, "access", grant_id, client_id, user_id, data, ACCESS_SECONDS)
    refresh = _new_token(db, "refresh", grant_id, client_id, user_id, data, REFRESH_DAYS * 86400)
    db.commit()
    return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_SECONDS,
                      refresh_token=refresh, scope=" ".join(scopes))


class DashboardOAuthProvider:
    """OAuthAuthorizationServerProvider backed by the dashboard database."""

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        with SessionLocal() as db:
            row = db.query(ConnectorClient).filter(ConnectorClient.client_id == client_id).first()
            if row is None:
                return None
            info = dict(row.info)
            if info.get("client_secret"):
                info["client_secret"] = decrypt(info["client_secret"])
            return ConnectorClientInfo.model_validate(info)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        if not uris or not all(allowed_redirect(u) for u in uris):
            raise RegistrationError("invalid_redirect_uri", "Only Claude (claude.ai or Claude Code) can connect to this dashboard")
        info = client_info.model_dump(mode="json", exclude_none=True)
        if info.get("client_secret"):
            info["client_secret"] = encrypt(info["client_secret"])
        with SessionLocal() as db:
            count = db.query(ConnectorClient).count()
            if count >= MAX_CLIENTS:
                # Drop the oldest registrations that have no live tokens
                used = {c for (c,) in db.query(ConnectorToken.client_id).distinct()}
                for old in db.query(ConnectorClient).order_by(ConnectorClient.created_at).limit(count - MAX_CLIENTS + 1):
                    if old.client_id not in used:
                        db.delete(old)
            db.add(ConnectorClient(client_id=client_info.client_id, info=info))
            db.commit()

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not allowed_redirect(str(params.redirect_uri)):
            raise AuthorizeError("invalid_request", "Redirect URI not allowed")
        request = _consent_serializer().dumps({
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "explicit": params.redirect_uri_provided_explicitly,
            "challenge": params.code_challenge,
            "state": params.state,
            "scopes": params.scopes or [SCOPE],
            "resource": params.resource,
        })
        return f"{public_url()}/oauth/consent?request={request}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> Optional[AuthorizationCode]:
        with SessionLocal() as db:
            row = _find(db, "code", authorization_code)
            if row is None or row.client_id != client.client_id:
                return None
            d = row.data
            return AuthorizationCode(
                code=authorization_code, scopes=d["scopes"], expires_at=_ts(row.expires_at),
                client_id=row.client_id, code_challenge=d["challenge"], redirect_uri=AnyUrl(d["redirect_uri"]),
                redirect_uri_provided_explicitly=d["explicit"], resource=d.get("resource"), subject=str(row.user_id),
            )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        with SessionLocal() as db:
            row = _find(db, "code", authorization_code.code)
            if row is None:
                raise TokenError("invalid_grant", "Authorization code expired or already used")
            db.delete(row)  # one use only
            cleanup_expired(db)
            return _issue(db, client.client_id, row.user_id, row.grant_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> Optional[RefreshToken]:
        with SessionLocal() as db:
            row = _find(db, "refresh", refresh_token)
            if row is None or row.client_id != client.client_id:
                return None
            return RefreshToken(token=refresh_token, client_id=row.client_id, scopes=row.data["scopes"],
                                expires_at=_ts(row.expires_at), resource=row.data.get("resource"),
                                subject=str(row.user_id))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with SessionLocal() as db:
            row = _find(db, "refresh", refresh_token.token)
            if row is None:
                raise TokenError("invalid_grant", "Refresh token expired or revoked")
            # Rotate: the old refresh token and the grant's old access tokens stop working
            db.query(ConnectorToken).filter(ConnectorToken.grant_id == row.grant_id).delete(synchronize_session=False)
            return _issue(db, client.client_id, row.user_id, row.grant_id, scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        with SessionLocal() as db:
            row = _find(db, "access", token)
            if row is None:
                return None
            if row.last_used_at is None or row.last_used_at < datetime.utcnow() - timedelta(minutes=5):
                row.last_used_at = datetime.utcnow()
                db.commit()
            return AccessToken(token=token, client_id=row.client_id, scopes=row.data["scopes"],
                               expires_at=_ts(row.expires_at), resource=row.data.get("resource"),
                               subject=str(row.user_id))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with SessionLocal() as db:
            row = db.query(ConnectorToken).filter(ConnectorToken.token_hash == _hash(token.token)).first()
            if row is not None:
                db.query(ConnectorToken).filter(ConnectorToken.grant_id == row.grant_id).delete(synchronize_session=False)
                db.commit()


# ---- Consent page (uses the normal dashboard sign-in) ----

router = APIRouter(tags=["connector"])

CONSENT_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f6fa;color:#1d1f27;margin:0;
display:flex;min-height:100vh;align-items:center;justify-content:center;padding:16px}
.card{background:#fff;border-radius:16px;box-shadow:0 10px 40px rgb(0 0 0/.08);padding:28px;max-width:440px;width:100%}
h1{font-size:20px;margin:0 0 12px}p,li{font-size:15px;line-height:1.5}ul{padding-left:20px;margin:8px 0 16px}
.muted{color:#6b7080;font-size:13px}.row{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
button{font:inherit;font-size:15px;border-radius:10px;padding:10px 18px;border:1px solid #d9dbe3;background:#fff;cursor:pointer}
button.primary{background:#5046e5;border-color:#5046e5;color:#fff;font-weight:600}
@media (prefers-color-scheme:dark){body{background:#12141b;color:#e8e9ee}.card{background:#1b1e27;box-shadow:none}
button{background:#1b1e27;color:#e8e9ee;border-color:#343846}.muted{color:#9aa0b0}}
"""


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>Connect Claude</title><style>{CONSENT_CSS}</style></head><body><div class=card>{body}</div></body></html>",
        headers={"X-Frame-Options": "DENY", "Cache-Control": "no-store"},
    )


def _load_request(token: str) -> Optional[dict]:
    try:
        return _consent_serializer().loads(token, max_age=CONSENT_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def _signed_in(request: Request, db: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    return db.get(User, user_id) if user_id is not None else None


@router.get("/oauth/consent", response_class=HTMLResponse)
def consent_page(request: Request, db: Session = Depends(get_db)):
    token = request.query_params.get("request", "")
    data = _load_request(token)
    if data is None:
        return _page("<h1>This link has expired</h1><p>Go back to Claude and connect again.</p>")
    user = _signed_in(request, db)
    if user is None:
        # Sign in first (the Google login brings the browser back here)
        request.session["after_login"] = f"/oauth/consent?request={token}"
        return RedirectResponse("/auth/google/login", status_code=303)
    client = db.query(ConnectorClient).filter(ConnectorClient.client_id == data["client_id"]).first()
    name = (client.info.get("client_name") if client else None) or "Claude"
    csrf = request.session.setdefault("connector_csrf", secrets.token_urlsafe(24))
    return _page(f"""
<h1>Allow {html.escape(name)} to use your dashboard?</h1>
<p>Signed in as <b>{html.escape(user.email)}</b>. Claude will be able to:</p>
<ul>
<li>read your dashboard: calendar, emails, notes &amp; reminders, nutrition, workouts, budget, weather and news</li>
<li>add, change and delete reminders, notes, food, workouts and budget entries (every change is logged on the dashboard and can be undone)</li>
</ul>
<p class=muted>Your journal is never shared. You can disconnect any time from the dashboard or from Claude.<br>
After you allow it, you'll be sent back to <b>{html.escape(redirect_label(data["redirect_uri"]))}</b>.</p>
<form method=post action="/oauth/consent" class=row>
<input type=hidden name=request value="{html.escape(token)}"><input type=hidden name=csrf value="{html.escape(csrf)}">
<button name=decision value=deny>Deny</button><button class=primary name=decision value=allow>Allow</button>
</form>""")


@router.post("/oauth/consent")
def consent_decision(request: Request, db: Session = Depends(get_db), request_token: str = Form(..., alias="request"),
                     csrf: str = Form(...), decision: str = Form(...)):
    data = _load_request(request_token)
    user = _signed_in(request, db)
    expected = request.session.get("connector_csrf")
    if data is None or user is None or not expected or not secrets.compare_digest(csrf, expected):
        return _page("<h1>Something went wrong</h1><p>Go back to Claude and connect again.</p>")
    redirect_uri, state = data["redirect_uri"], data.get("state")
    if decision != "allow":
        return RedirectResponse(construct_redirect_uri(redirect_uri, error="access_denied", state=state), status_code=303)
    code = _new_token(db, "code", secrets.token_hex(16), data["client_id"], user.id, {
        "scopes": data["scopes"], "resource": data.get("resource"), "redirect_uri": redirect_uri,
        "explicit": data["explicit"], "challenge": data["challenge"],
    }, CODE_SECONDS)
    db.commit()
    return RedirectResponse(construct_redirect_uri(redirect_uri, code=code, state=state), status_code=303)


def safe_after_login(path: Optional[str]) -> Optional[str]:
    """Only our own consent page may be a post-login destination."""
    return path if path and re.fullmatch(r"/oauth/consent\?request=[A-Za-z0-9_.\-]+", path) else None


def cleanup_expired(db: Session) -> None:
    db.query(ConnectorToken).filter(ConnectorToken.expires_at < datetime.utcnow()).delete(synchronize_session=False)
    db.commit()

