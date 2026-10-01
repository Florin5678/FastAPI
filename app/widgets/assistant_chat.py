# The Assistant widget's AI chat: Claude (via the paid API, ANTHROPIC_API_KEY) with the
# whole dashboard as context and the same tools as the Claude connector.
#
# - Context: the system prompt holds the user's dashboard briefing (every widget with a
#   brief(), so never the journal). For details
#   and changes Claude calls the connector tools (app/connector/tools.py): structured
#   retrieval, which suits this data better than vector search.
# - Tools run in-process as the signed-in user; changes land in the connector's change
#   log (client "dashboard-chat") and can be undone.
# - Cost control: model and monthly budget (USD) are Assistant settings; every
#   response's usage is priced and added to config["assistant_usage"][YYYY-MM]; the
#   chat refuses once the month's spend reaches the budget. Prompt caching on the tools
#   and the briefing; short replies; a cap on tool rounds per question.
import json
import logging
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import anyio
from fastapi import APIRouter, Depends, HTTPException
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.connector.tools import INSTRUCTIONS, TIMEZONE, _ctx, mcp
from app.core.database import get_db
from app.core.security import get_current_user
from app.mail.summarize import get_client
from app.models import ConnectorChange, User
from app.widgets import assistant
from app.widgets.assistant import WIDGET_ID, _row, load_settings

logger = logging.getLogger(__name__)

CLIENT_ID = "dashboard-chat"
MAX_TOOL_ROUNDS = 8
MAX_REPLY_TOKENS = 1500
MAX_HISTORY = 20  # messages kept from the conversation
MAX_MESSAGE_CHARS = 6000
MAX_TOOL_RESULT_CHARS = 20_000
BRIEFING_CACHE_SECONDS = 300

# Model id -> (label, $ per million tokens: input, output, cache write, cache read)
MODELS = {
    "claude-haiku-4-5": ("Claude Haiku 4.5", 1.0, 5.0, 1.25, 0.10),
    "claude-sonnet-5": ("Claude Sonnet 5", 2.0, 10.0, 2.50, 0.20),
    "claude-opus-5-5": ("Claude Opus 5.5", 4.0, 20.0, 5.00, 0.20),
    "claude-fable-5-1": ("Claude Fable 5.1", 10.0, 50.0, 12.50, 0.25),
}
DEFAULT_MODEL = "claude-haiku-4-5"

_briefings: dict[int, tuple[float, str]] = {}  # user id -> (time, briefing text)


def month_key() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y-%m")


def month_usage(db: Session, user: User) -> dict:
    row = _row(db, user)
    return dict(((row.config or {}).get("assistant_usage") or {}).get(month_key()) or {})


def _add_usage(db: Session, user: User, model: str, usage) -> float:
    """Price one API response and add it to this month's usage. Returns its cost."""
    _, p_in, p_out, p_write, p_read = MODELS.get(model, MODELS[DEFAULT_MODEL])
    tokens = {
        "input": usage.input_tokens or 0,
        "output": usage.output_tokens or 0,
        "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }
    cost = (tokens["input"] * p_in + tokens["output"] * p_out + tokens["cache_write"] * p_write + tokens["cache_read"] * p_read) / 1_000_000
    row = _row(db, user)
    all_usage = dict((row.config or {}).get("assistant_usage") or {})
    month = dict(all_usage.get(month_key()) or {})
    for key, value in tokens.items():
        month[key] = month.get(key, 0) + value
    month["requests"] = month.get("requests", 0) + 1
    month["cost"] = round(month.get("cost", 0.0) + cost, 6)
    all_usage[month_key()] = month
    row.config = {**(row.config or {}), "assistant_usage": all_usage}
    db.commit()
    return cost


def _briefing(db: Session, user: User) -> str:
    """The briefing data and the user's answer guide (the same builder as get_briefing and
    "Copy briefing", see assistant.py), for the system prompt."""
    cached = _briefings.get(user.id)
    if cached and time.time() - cached[0] < BRIEFING_CACHE_SECONDS:
        return cached[1]
    prefs = assistant.load_settings(db, user)
    sections = assistant.briefing_sections(db, user, _ctx(), prefs)
    text = (
        f"# The user's dashboard right now\n\n{assistant.render_sections(sections)}\n\n"
        "# When the user asks for a briefing (\"brief me\", \"my day\", \"morning update\"...)\n\n"
        f"{assistant.answer_guide(prefs)}\n\n"
        "The rules above apply to every answer, not only briefings."
    )
    _briefings[user.id] = (time.time(), text)
    return text


def _system(db: Session, user: User) -> list[dict]:
    rules = (
        "You are the assistant built into the user's personal dashboard. Answer briefly and concretely. "
        + INSTRUCTIONS
        + " Use the briefing below first; call tools for details it doesn't have (full emails, other days or "
        "months, ids needed for changes). When you change something, say what you changed. Ask before deleting "
        "anything unless the user clearly asked for it. Amounts of money are in the user's currency (kr). "
        "The chat shows plain text: no Markdown headings, tables or bold; write section names as plain lines."
    )
    cached = f"{rules}\n\n{_briefing(db, user)}"
    now = datetime.now(ZoneInfo(TIMEZONE)).strftime("%A %d %B %Y, %H:%M")
    return [
        {"type": "text", "text": cached, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"Current local time: {now} ({TIMEZONE})."},
    ]


def _tools() -> list[dict]:
    tools = [
        {"name": t.name, "description": t.description, "input_schema": t.parameters}
        for t in mcp._tool_manager.list_tools()
    ]
    tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}  # cache the (static) tool list
    return tools


async def _run_tool(user: User, name: str, arguments: dict) -> tuple[str, bool]:
    """Run a connector tool as `user`. Returns (result text, is_error)."""
    token = auth_context_var.set(AuthenticatedUser(AccessToken(
        token="dashboard-chat", client_id=CLIENT_ID, scopes=["dashboard"], subject=str(user.id),
    )))
    try:
        result = await mcp._tool_manager.call_tool(name, arguments, Context(mcp_server=mcp, subscriptions=mcp._subscriptions))
        text = result if isinstance(result, str) else json.dumps(result, default=str, ensure_ascii=False)
        return text[:MAX_TOOL_RESULT_CHARS], False
    except ToolError as e:
        return str(e), True
    except Exception:
        logger.warning("Assistant chat: tool %s failed", name, exc_info=True)
        return f"Tool {name} failed unexpectedly", True
    finally:
        auth_context_var.reset(token)


# ---- Routes ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)


def _usage_out(db: Session, user: User, model: str, budget: float) -> dict:
    usage = month_usage(db, user)
    return {"month": month_key(), "cost": round(usage.get("cost", 0.0), 4), "requests": usage.get("requests", 0),
            "budget": budget, "model": model, "model_label": MODELS.get(model, MODELS[DEFAULT_MODEL])[0]}


@router.get("/chat/status")
def chat_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = load_settings(db, user)
    return {
        "enabled": get_client() is not None,
        "usage": _usage_out(db, user, settings.model, settings.monthly_budget),
        "models": [{"id": k, "label": v[0], "input": v[1], "output": v[2]} for k, v in MODELS.items()],
    }


@router.post("/chat")
async def chat(body: ChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    client = get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="The AI chat needs a Claude API key: add ANTHROPIC_API_KEY on Render")
    if _row(db, user) is None:
        raise HTTPException(status_code=404, detail="Add the Assistant widget to your dashboard first")
    settings = load_settings(db, user)
    model = settings.model if settings.model in MODELS else DEFAULT_MODEL
    if body.messages[-1].role != "user":
        raise HTTPException(status_code=422, detail="The last message must be from you")

    system = _system(db, user)
    tools = _tools()
    messages: list[dict] = [{"role": m.role, "content": m.content} for m in body.messages[-MAX_HISTORY:]]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)  # the API needs the conversation to start with the user
    started = datetime.utcnow()
    actions: list[dict] = []
    reply = ""

    for _ in range(MAX_TOOL_ROUNDS + 1):
        if month_usage(db, user).get("cost", 0.0) >= settings.monthly_budget:
            reply = reply or (f"This month's AI budget (${settings.monthly_budget:.2f}) is used up. "
                              "Raise it in the Assistant settings (⚙) or wait until next month.")
            break
        try:
            response = await anyio.to_thread.run_sync(lambda: client.messages.create(
                model=model, max_tokens=MAX_REPLY_TOKENS, system=system, tools=tools, messages=messages,
            ))
        except Exception as e:  # anthropic.APIError and network errors
            logger.warning("Assistant chat: Claude API call failed", exc_info=True)
            raise HTTPException(status_code=502, detail=f"Claude didn't answer: {getattr(e, 'message', None) or type(e).__name__}") from e
        _add_usage(db, user, model, response.usage)
        reply = "".join(block.text for block in response.content if block.type == "text")
        if response.stop_reason != "tool_use":
            break
        messages.append({"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in response.content]})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            text, is_error = await _run_tool(user, block.name, block.input or {})
            actions.append({"tool": block.name, "error": text if is_error else None})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    else:
        reply = reply or "I needed too many steps for that one. Could you ask something more specific?"

    changes = (
        db.query(ConnectorChange)
        .filter(ConnectorChange.user_id == user.id, ConnectorChange.client_id == CLIENT_ID, ConnectorChange.created_at >= started)
        .order_by(ConnectorChange.id)
        .all()
    )
    return {
        "reply": reply.strip() or "(no answer)",
        "actions": actions,
        "changes": [{"id": c.id, "summary": c.summary} for c in changes],
        "usage": _usage_out(db, user, model, settings.monthly_budget),
    }
