# Wires the Claude connector into the dashboard app: the MCP endpoint (/mcp) and the
# OAuth endpoints (/authorize, /token, /register, /revoke, /.well-known/...) come from
# the MCP SDK as a small Starlette app; MCPDispatch sends those paths to it and
# everything else to FastAPI. The dashboard-side routes (status, undo, revoke) are a
# normal FastAPI router.
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, Depends
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app.connector import changes
from app.connector.oauth import public_url
from app.connector.tools import MCP_PATH, mcp
from app.core.database import get_db
from app.core.security import get_current_user
from app.models import ConnectorClient, ConnectorToken, User

def build_mcp_app() -> ASGIApp:
    return mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,  # no server-side sessions: survives restarts, one request per call
        json_response=True,
        # Public server behind auth; DNS-rebinding checks are for servers on localhost
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


mcp_app = build_mcp_app()
MCP_PATHS = {
    MCP_PATH, "/authorize", "/token", "/register", "/revoke",
    "/.well-known/oauth-authorization-server",
    "/.well-known/oauth-protected-resource",
    f"/.well-known/oauth-protected-resource{MCP_PATH}",
}


class MCPDispatch:
    """ASGI middleware: connector paths go to the MCP app, the rest to the dashboard."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (scope["path"].rstrip("/") or "/") in MCP_PATHS:
            await mcp_app(scope, receive, send)
        else:
            await self.app(scope, receive, send)


@asynccontextmanager
async def connector_lifespan():
    """Runs the MCP session manager (needed even in stateless mode) for the app's lifetime."""
    async with mcp.session_manager.run():
        yield


# ---- Dashboard side: status, undo, disconnect ----

router = APIRouter(prefix="/connector", tags=["connector"])


@router.get("/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Connected Claude apps (one per sign-in), recent changes, and the URL to add in Claude."""
    rows = (
        db.query(ConnectorToken)
        .filter(ConnectorToken.user_id == user.id, ConnectorToken.kind == "refresh", ConnectorToken.expires_at > datetime.utcnow())
        .all()
    )
    clients = {c.client_id: c for c in db.query(ConnectorClient).filter(ConnectorClient.client_id.in_({r.client_id for r in rows}))}
    used = {}
    for t in db.query(ConnectorToken).filter(ConnectorToken.user_id == user.id, ConnectorToken.kind == "access"):
        if t.last_used_at and (t.grant_id not in used or t.last_used_at > used[t.grant_id]):
            used[t.grant_id] = t.last_used_at
    connections = []
    for r in rows:
        info = clients[r.client_id].info if r.client_id in clients else {}
        uris = " ".join(info.get("redirect_uris", []))
        app_name = "Claude Code" if "localhost" in uris or "127.0.0.1" in uris else info.get("client_name") or "Claude"
        last = used.get(r.grant_id)
        connections.append({
            "grant_id": r.grant_id, "app": app_name, "connected_at": r.created_at.isoformat() + "Z",
            "last_used_at": last.isoformat() + "Z" if last else None,
        })
    return {"url": f"{public_url()}{MCP_PATH}", "connections": connections, "changes": changes.recent(db, user, 30)}


@router.post("/changes/{change_id}/undo")
def undo_change(change_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return changes.undo(db, user, change_id)


@router.post("/connections/{grant_id}/revoke")
def revoke(grant_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Disconnect one Claude sign-in (its tokens stop working immediately)."""
    deleted = (
        db.query(ConnectorToken)
        .filter(ConnectorToken.user_id == user.id, ConnectorToken.grant_id == grant_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"revoked": deleted > 0}
