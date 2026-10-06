# Changes Claude makes through the connector: every write tool records one row with a
# plain-language summary and how to reverse it, so the dashboard can list them and
# undo any of them. Undo goes through the same widget functions as normal edits.
from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ConnectorChange, User
from app.widgets import budget, google_calendar, gym, notes, nutrition, weight


def record(db: Session, user: User, client_id: Optional[str], tool: str, summary: str, undo: Optional[dict]) -> ConnectorChange:
    change = ConnectorChange(user_id=user.id, client_id=client_id, tool=tool, summary=summary[:300], undo=undo)
    db.add(change)
    db.commit()
    db.refresh(change)
    return change


def change_dict(c: ConnectorChange) -> dict:
    return {
        "id": c.id, "tool": c.tool, "summary": c.summary, "at": c.created_at.isoformat() + "Z",
        "can_undo": c.undo is not None and c.undone_at is None,
        "undone_at": c.undone_at.isoformat() + "Z" if c.undone_at else None,
    }


def recent(db: Session, user: User, limit: int = 20) -> list[dict]:
    rows = (
        db.query(ConnectorChange)
        .filter(ConnectorChange.user_id == user.id)
        .order_by(ConnectorChange.created_at.desc(), ConnectorChange.id.desc())
        .limit(limit)
        .all()
    )
    return [change_dict(c) for c in rows]


# ---- Undo actions ----

def _restore_reminder(db: Session, user: User, item: dict) -> None:
    """Put a reminder back exactly as it was (same id)."""
    row = notes.widget_row(db, user, notes.WIDGET_ID)
    items = [i for i in notes._items(row) if i["id"] != item["id"]]
    notes._save(row, [*items, item])
    db.commit()


def _restore_pantry_item(db: Session, user: User, item: dict) -> None:
    """Put a pantry item back exactly as it was (same id)."""
    row = nutrition.widget_row(db, user, nutrition.WIDGET_ID)
    items = [i for i in nutrition._pantry(row) if i["id"] != item["id"]]
    nutrition._store_pantry(row, [*items, item])
    db.commit()


def _undo_pantry_items(db: Session, user: User, added: list[str], before: list[dict]) -> None:
    """Undo add_pantry_items: remove the items it added, put the ones it updated back."""
    row = nutrition.widget_row(db, user, nutrition.WIDGET_ID)
    restored = {i["id"]: i for i in before}
    items = [restored.get(i["id"], i) for i in nutrition._pantry(row) if i["id"] not in added]
    nutrition._store_pantry(row, items)
    db.commit()


def _readd_food(db: Session, user: User, entry: dict) -> None:
    nutrition.add_entry(nutrition.EntryIn(
        day=date.fromisoformat(entry["day"]), name=entry["name"], grams=entry.get("grams"),
        nutrients=nutrition.Nutrients(**{k: entry.get(k, 0) or 0 for k in nutrition.Nutrients.model_fields}),
        source=entry.get("source") or "manual", fdc_id=entry.get("fdc_id"),
    ), user=user, db=db)


UNDO_ACTIONS: dict[str, Any] = {
    "delete_reminder": lambda db, user, a: notes.delete_reminder(a["id"], user=user, db=db),
    "restore_reminder": lambda db, user, a: _restore_reminder(db, user, a["item"]),
    "delete_food": lambda db, user, a: nutrition.delete_entry(a["id"], user=user, db=db),
    "readd_food": lambda db, user, a: _readd_food(db, user, a["entry"]),
    "delete_pantry_item": lambda db, user, a: nutrition.delete_pantry_item(a["id"], user=user, db=db),
    "restore_pantry_item": lambda db, user, a: _restore_pantry_item(db, user, a["item"]),
    "restore_saved_food": lambda db, user, a: nutrition.restore_saved_food(db, user, a["food"]),
    "restore_lists": lambda db, user, a: nutrition.restore_lists(db, user, a["undo"]),
    "delete_calendar_event": lambda db, user, a: google_calendar.delete_event(db, user, a["calendar_id"], a["event_id"]),
    "restore_calendar_event": lambda db, user, a: google_calendar.update_event(db, user, a["calendar_id"], a["event_id"], a["body"]),
    "recreate_calendar_event": lambda db, user, a: google_calendar.create_event(db, user, a["calendar_id"], a["body"]),
    "set_weight": lambda db, user, a: weight.log_weight(db, user, date.fromisoformat(a["day"]), a["kg"]),
    "delete_weight": lambda db, user, a: weight.delete_weight(db, user, a["day"]),
    "undo_pantry_items": lambda db, user, a: _undo_pantry_items(db, user, a["added"], a["before"]),
    "restore_food": lambda db, user, a: nutrition.update_entry(a["id"], nutrition.EntryPatch(
        day=date.fromisoformat(a["entry"]["day"]), name=a["entry"]["name"], grams=a["entry"].get("grams"),
        nutrients=nutrition.Nutrients(**a["entry"]["nutrients"]),
    ), user=user, db=db),
    "delete_workout": lambda db, user, a: gym.delete_workout(a["id"], user=user, db=db),
    "readd_workout": lambda db, user, a: gym.log_workout(gym.WorkoutIn(**a["workout"]), user=user, db=db),
    "restore_workout": lambda db, user, a: gym.update_workout(
        a["id"], gym.WorkoutPatch(**{**a["workout"], "note": a["workout"]["note"] or ""}), user=user, db=db),
    "delete_budget_entry": lambda db, user, a: budget.delete_entry(a["id"], user=user, db=db),
    "readd_budget_entry": lambda db, user, a: budget.add_entry(budget.EntryIn(**a["entry"]), user=user, db=db),
    "update_budget_entry": lambda db, user, a: budget.update_entry(a["id"], budget.EntryPatch(**a["entry"]), user=user, db=db),
    "set_budgets": lambda db, user, a: budget.set_budgets(budget.BudgetsIn(budgets=a["budgets"]), user=user, db=db),
}


def undo(db: Session, user: User, change_id: int) -> dict:
    change = db.query(ConnectorChange).filter(ConnectorChange.id == change_id, ConnectorChange.user_id == user.id).first()
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    if change.undone_at is not None:
        raise HTTPException(status_code=409, detail="That change was already undone")
    if not change.undo:
        raise HTTPException(status_code=422, detail="That change can't be undone")
    action = UNDO_ACTIONS.get(change.undo["action"])
    if action is None:  # e.g. a change to Notes, which no longer exist
        raise HTTPException(status_code=422, detail="That change can't be undone any more")
    try:
        action(db, user, change.undo["args"])
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=409, detail="Can't undo: the item was changed or deleted since") from e
        raise
    change.undone_at = datetime.utcnow()
    db.commit()
    return change_dict(change)
