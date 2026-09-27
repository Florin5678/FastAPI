# Generic dashboard routes. Which widgets a user has, their settings and grid
# position live in the `integrations` table (one row per user + widget):
#   app_name = widget id, status = "active" | "disabled",
#   config   = {"settings": {...}, "layout": {"x", "y", "w", "h"}}
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Integration, User
from app.security import get_current_user
from app.widgets import REGISTRY, WidgetContext, WidgetDefinition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widgets")

GRID_COLS = 12


def _definition(widget_id: str) -> WidgetDefinition:
    definition = REGISTRY.get(widget_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Unknown widget {widget_id!r}")
    return definition


def _rows(db: Session, user: User) -> list[Integration]:
    return db.query(Integration).filter(Integration.user_id == user.id).all()


def _settings(definition: WidgetDefinition, row: Integration) -> dict:
    # Defaults first, so settings added to a widget later get a value
    saved = (row.config or {}).get("settings", {})
    known = {f.key for f in definition.config_fields}
    return {**definition.default_settings(), **{k: v for k, v in saved.items() if k in known}}


def _layout(definition: WidgetDefinition, row: Integration) -> dict:
    layout = dict((row.config or {}).get("layout") or {})
    w, h = definition.default_size
    if layout.get("v", 1) < definition.layout_version:
        # Saved before the widget's default size changed: adopt the new default size
        layout.pop("w", None)
        layout.pop("h", None)
    return {
        "x": layout.get("x", 0),
        "y": layout.get("y", 0),
        "w": max(layout.get("w", w), definition.min_size[0]),
        "h": max(layout.get("h", h), definition.min_size[1]),
    }


def _free_spot(db: Session, user: User, w: int, h: int) -> tuple[int, int]:
    """First position (top to bottom, left to right) where a w x h widget fits
    without overlapping the user's other widgets."""
    taken = [
        _layout(REGISTRY[r.app_name], r)
        for r in _rows(db, user)
        if r.status == "active" and r.app_name in REGISTRY
    ]

    def fits(x: int, y: int) -> bool:
        return all(
            x + w <= t["x"] or t["x"] + t["w"] <= x or y + h <= t["y"] or t["y"] + t["h"] <= y
            for t in taken
        )

    bottom = max((t["y"] + t["h"] for t in taken), default=0)
    for y in range(bottom + 1):
        for x in range(GRID_COLS - w + 1):
            if fits(x, y):
                return x, y
    return 0, bottom


def _set_config(row: Integration, **changes: Any) -> None:
    # JSON columns aren't mutation-tracked: assign a new dict so SQLAlchemy saves it
    row.config = {**(row.config or {}), **changes}
    row.updated_at = datetime.utcnow()


def _widget_out(definition: WidgetDefinition, row: Integration) -> dict:
    return {
        **definition.manifest(),
        "settings": _settings(definition, row),
        "layout": _layout(definition, row),
    }


def _enable(db: Session, user: User, definition: WidgetDefinition) -> Integration:
    row = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.app_name == definition.id)
        .first()
    )
    w, h = definition.default_size
    x, y = _free_spot(db, user, w, h)
    if row is None:
        row = Integration(user_id=user.id, app_name=definition.id, status="active", config={})
        db.add(row)
    row.status = "active"
    # Re-enabled widgets keep their settings but get a fresh spot on the grid
    layout = {"x": x, "y": y, "w": w, "h": h, "v": definition.layout_version}
    _set_config(row, settings=(row.config or {}).get("settings", {}), layout=layout)
    db.flush()  # so the next widget placed in this request sees this one
    return row


@router.get("/catalog")
def catalog(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Every available widget, and whether it's on this user's dashboard."""
    active = {r.app_name for r in _rows(db, user) if r.status == "active"}
    return [{**d.manifest(), "enabled": d.id in active} for d in REGISTRY.values()]


@router.get("")
def my_widgets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The user's dashboard. Default widgets are added once, including ones
    introduced later; removing a widget keeps a disabled row, so it doesn't come back."""
    known = {r.app_name for r in _rows(db, user)}
    missing = [d for d in REGISTRY.values() if d.enabled_by_default and d.id not in known]
    for definition in missing:
        _enable(db, user, definition)
    if missing:
        db.commit()
    rows = _rows(db, user)

    return [
        _widget_out(REGISTRY[r.app_name], r)
        for r in rows
        if r.status == "active" and r.app_name in REGISTRY  # skip widgets removed from the code
    ]


@router.post("/{widget_id}")
def add_widget(widget_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    definition = _definition(widget_id)
    row = _enable(db, user, definition)
    db.commit()
    return _widget_out(definition, row)


@router.delete("/{widget_id}")
def remove_widget(widget_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _definition(widget_id)
    row = (
        db.query(Integration)
        .filter(Integration.user_id == user.id, Integration.app_name == widget_id)
        .first()
    )
    if row is not None:
        row.status = "disabled"  # keep settings in case it's added back
        row.updated_at = datetime.utcnow()
        db.commit()
    return {"removed": widget_id}


class SettingsIn(BaseModel):
    settings: dict[str, Any]


@router.patch("/{widget_id}/settings")
def update_settings(
    widget_id: str,
    body: SettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    definition = _definition(widget_id)
    row = _active_row(db, user, widget_id)
    fields = {f.key: f for f in definition.config_fields}

    new_settings = _settings(definition, row)
    for key, value in body.settings.items():
        if key not in fields:
            raise HTTPException(status_code=422, detail=f"Unknown setting {key!r}")
        try:
            new_settings[key] = fields[key].validate(value)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    _set_config(row, settings=new_settings)
    db.commit()
    return _widget_out(definition, row)


class LayoutItemIn(BaseModel):
    i: str  # widget id (react-grid-layout's name for it)
    x: int
    y: int
    w: int
    h: int


@router.put("/layout")
def save_layout(
    items: list[LayoutItemIn],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = {r.app_name: r for r in _rows(db, user) if r.status == "active"}
    for item in items:
        row = rows.get(item.i)
        definition = REGISTRY.get(item.i)
        if row is None or definition is None:
            continue  # stale item from the browser - ignore rather than fail the whole save
        w = min(max(item.w, definition.min_size[0]), GRID_COLS)
        h = max(item.h, definition.min_size[1])
        x = min(max(item.x, 0), GRID_COLS - w)
        _set_config(row, layout={"x": x, "y": max(item.y, 0), "w": w, "h": h, "v": definition.layout_version})
    db.commit()
    return {"saved": len(items)}


def _active_row(db: Session, user: User, widget_id: str) -> Integration:
    row = (
        db.query(Integration)
        .filter(
            Integration.user_id == user.id,
            Integration.app_name == widget_id,
            Integration.status == "active",
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Widget {widget_id!r} is not on your dashboard")
    return row


@router.get("/{widget_id}/data")
def widget_data(
    widget_id: str,
    since: Optional[datetime] = None,
    tz: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every widget's data comes back in the same envelope. A failing widget
    reports status "error" instead of failing the request, so the rest of the
    dashboard still renders."""
    definition = _definition(widget_id)
    row = _active_row(db, user, widget_id)

    if since is None:
        since_utc = datetime.combine(datetime.utcnow().date(), datetime.min.time())
    elif since.tzinfo is not None:
        since_utc = since.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        since_utc = since
    ctx = WidgetContext(since=since_utc, tz=tz)

    now = datetime.now(timezone.utc).isoformat()
    try:
        data = definition.fetch(db, user, _settings(definition, row), ctx)
    except HTTPException as e:
        return {"status": "error", "error": str(e.detail), "data": None, "last_updated": now}
    except Exception:
        logger.exception("Widget %s failed", widget_id)
        return {"status": "error", "error": "Something went wrong loading this widget", "data": None, "last_updated": now}

    return {"status": "ok", "data": data, "last_updated": now}
