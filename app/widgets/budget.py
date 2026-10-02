# Budget widget: a monthly money log kept in the dashboard's own database
# (budget_entries): each entry is a month, a category path of up to four levels
# (Income > SU, Expenses > Transport > Plane tickets > Dubai - Copenhagen) and an
# amount. Everything is editable from the widget and its monthly report page;
# existing logs come in once through a CSV import (e.g. a Google Sheet downloaded as
# .csv). Monthly budgets per spending category live in the widget's config.
# Not part of the Assistant briefing (no brief()), on purpose: money stays out of it.
import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import BudgetEntry, User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "budget"
INCOME = "income"  # the top-level category that counts as income (case-insensitive)
LEVELS = 4
MAX_ENTRIES = 20_000
MAX_IMPORT_BYTES = 2 * 1024 * 1024
HISTORY_MONTHS = 12
TILE_MONTHS = 6  # months in the tile's income vs spending chart
MONTH_RE = r"^\d{4}-(0[1-9]|1[0-2])$"
CSV_HEADER = ["Month", "Category", "Sub-category", "Sub-sub-category", "Sub-sub-sub-category", "Amount"]
# The top level is one of these; expenses must use one of the fixed sub-categories below
# (lower levels, and income sub-categories, are free text)
TOP_LEVELS = ["Expenses", "Income"]
# What belongs in each expense sub-category (for Claude, which files entries through the connector)
EXPENSE_GUIDE = {
    "Bank fees": "bank and card fees, currency exchange fees",
    "Barber": "haircuts",
    "Charity/Donations": "donations and charity",
    "Club/Bar": "drinks and entry at bars and clubs, nightlife",
    "Groceries": "supermarket and food shopping",
    "Household items": "things for the home: furniture, kitchenware, cleaning supplies, electronics for the flat",
    "Loan repayments": "loan instalments and payoffs",
    "Lodging": "hotels, hostels, Airbnb",
    "Other": "anything that fits nowhere else: dentist, vet, repairs, activities and tickets, sports fees, "
             "money sent to people, ATM withdrawals",
    "Pharmacy": "medicine, supplements, pharmacy purchases",
    "Rent": "the monthly rent",
    "Restaurant/Café": "eating out, cafés and coffee, canteens, takeaway and food delivery (Wolt, Glovo)",
    "Shopping": "clothes, shoes, gifts, books, games and other personal purchases",
    "Subscriptions": "recurring services: phone plan, internet, streaming, software, cloud storage, gym, union",
    "Transport": "public transport and trains, flights, taxis and Uber, bike and scooter rentals, travel fees",
}
EXPENSE_CATEGORIES = sorted(EXPENSE_GUIDE, key=str.lower)


# ---- Helpers ----

def _path(e: BudgetEntry) -> list[str]:
    return [p for p in (e.category, e.sub1, e.sub2, e.sub3) if p]


def _entry_dict(e: BudgetEntry) -> dict:
    return {"id": e.id, "month": e.month, "path": _path(e), "amount": float(e.amount)}


def _is_income(category: str) -> bool:
    return category.strip().lower() == INCOME


def _clean_path(path: list[str]) -> list[str]:
    """Trimmed levels without trailing blanks; a blank level in the middle is an error."""
    levels = [p.strip() for p in path]
    while levels and not levels[-1]:
        levels.pop()
    if not levels or len(levels) > LEVELS or any(not p for p in levels):
        raise HTTPException(status_code=422, detail="A category path needs 1 to 4 levels without gaps")
    if any(len(p) > 120 for p in levels):
        raise HTTPException(status_code=422, detail="Category names can be at most 120 characters")
    return levels


def _check_categories(path: list[str]) -> list[str]:
    """The path with its top level and (for expenses) sub-category checked against the fixed
    lists and spelled as there; lower levels are free text."""
    top = next((t for t in TOP_LEVELS if t.lower() == path[0].lower()), None)
    if top is None:
        raise HTTPException(status_code=422, detail='The category must be "Expenses" or "Income"')
    path = [top, *path[1:]]
    if top == "Expenses":
        sub = next((c for c in EXPENSE_CATEGORIES if len(path) > 1 and c.lower() == path[1].lower()), None)
        if sub is None:
            given = f'"{path[1]}" is not an expense sub-category. ' if len(path) > 1 else "Expenses need a sub-category. "
            raise HTTPException(status_code=422, detail=given + "Use one of: " + ", ".join(EXPENSE_CATEGORIES))
        path[1] = sub
    return path


def _set_path(e: BudgetEntry, path: list[str]) -> None:
    padded = path + [None] * (LEVELS - len(path))
    e.category, e.sub1, e.sub2, e.sub3 = padded


def _shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    index = y * 12 + (m - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _budgets(db: Session, user: User) -> dict[str, float]:
    return dict((widget_row(db, user, WIDGET_ID).config or {}).get("budgets") or {})


def _totals(db: Session, user: User, first: str, last: str) -> dict[str, dict]:
    """{month: {"income", "expenses", "categories": {spending category: total}}} for
    months first..last. The spending category is the second level (Expenses > Rent)
    or the top level when there is none."""
    rows = (
        db.query(BudgetEntry.month, BudgetEntry.category, BudgetEntry.sub1, func.sum(BudgetEntry.amount))
        .filter(BudgetEntry.user_id == user.id, BudgetEntry.month >= first, BudgetEntry.month <= last)
        .group_by(BudgetEntry.month, BudgetEntry.category, BudgetEntry.sub1)
        .all()
    )
    out: dict[str, dict] = {}
    for month, category, sub1, total in rows:
        m = out.setdefault(month, {"income": 0.0, "expenses": 0.0, "categories": {}})
        if _is_income(category):
            m["income"] += float(total)
        else:
            m["expenses"] += float(total)
            name = sub1 or category
            m["categories"][name] = m["categories"].get(name, 0.0) + float(total)
    return out


def _month_or_400(month: str) -> str:
    if not re.match(MONTH_RE, month or ""):
        raise HTTPException(status_code=422, detail="Month must look like 2026-09")
    return month


def _paths(db: Session, user: User) -> list[list[str]]:
    """Every distinct category path, for suggestions when adding entries."""
    rows = (
        db.query(BudgetEntry.category, BudgetEntry.sub1, BudgetEntry.sub2, BudgetEntry.sub3)
        .filter(BudgetEntry.user_id == user.id)
        .distinct()
        .all()
    )
    return sorted(([p for p in r if p] for r in rows), key=lambda p: [s.lower() for s in p])


# ---- Widget ----

def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    month = local_today(ctx.tz).isoformat()[:7]
    first = _shift_month(month, -(TILE_MONTHS - 1))
    totals = _totals(db, user, first, month)
    now = totals.get(month, {})
    has_entries = db.query(BudgetEntry.id).filter(BudgetEntry.user_id == user.id).first() is not None
    return {
        "month": month,
        "has_entries": has_entries,
        "currency": settings["currency"].strip(),
        "income": round(now.get("income", 0.0), 2),
        "expenses": round(now.get("expenses", 0.0), 2),
        # Income vs spending per month, oldest first (the tile's column chart)
        "history": [
            {"month": m, "income": round(totals.get(m, {}).get("income", 0.0), 2),
             "expenses": round(totals.get(m, {}).get("expenses", 0.0), 2)}
            for m in (_shift_month(first, i) for i in range(TILE_MONTHS))
        ],
        "paths": _paths(db, user),
        "expense_categories": EXPENSE_CATEGORIES,
    }


DEFINITION = register(WidgetDefinition(
    id=WIDGET_ID,
    name="Budget",
    description="Log income and expenses by month and category, with budgets per category and a monthly report. Kept in the dashboard (import your existing log as CSV).",
    fetch=fetch,
    default_size=(4, 8),
    min_size=(3, 5),
    refresh_seconds=1800,
    config_fields=(
        ConfigField("currency", "Currency", "text", default="kr"),
    ),
))


# ---- Routes used by the widget and its report page ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class EntryIn(BaseModel):
    month: str = Field(pattern=MONTH_RE)
    path: list[str] = Field(min_length=1, max_length=LEVELS)
    amount: float = Field(ge=-1e9, le=1e9)


class EntryPatch(BaseModel):
    month: Optional[str] = Field(None, pattern=MONTH_RE)
    path: Optional[list[str]] = Field(None, min_length=1, max_length=LEVELS)
    amount: Optional[float] = Field(None, ge=-1e9, le=1e9)


class GroupIn(BaseModel):
    path: list[str] = Field(min_length=1, max_length=LEVELS)
    month: str = Field(pattern=MONTH_RE)


class BudgetsIn(BaseModel):
    budgets: dict[str, Optional[float]]  # spending category -> monthly budget (None/0 removes it)


class ImportIn(BaseModel):
    csv: str = Field(max_length=MAX_IMPORT_BYTES)
    replace: bool = False  # delete every existing entry first


def _under(query, user: User, path: list[str], month: Optional[str]):
    """Entries whose category path starts with `path` (optionally in one month)."""
    query = query.filter(BudgetEntry.user_id == user.id)
    for column, name in zip((BudgetEntry.category, BudgetEntry.sub1, BudgetEntry.sub2, BudgetEntry.sub3), path, strict=False):
        query = query.filter(column == name)
    if month:
        query = query.filter(BudgetEntry.month == month)
    return query


@router.get("/month")
def month_report(month: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything the report page shows for one month: its entries, totals, the
    previous month, budgets and the last 12 months."""
    month = _month_or_400(month)
    row = widget_row(db, user, WIDGET_ID)  # 404 unless the widget is on the dashboard
    entries = (
        db.query(BudgetEntry)
        .filter(BudgetEntry.user_id == user.id, BudgetEntry.month == month)
        .order_by(BudgetEntry.amount.desc())
        .all()
    )
    first_history = _shift_month(month, -(HISTORY_MONTHS - 1))
    totals = _totals(db, user, first_history, month)
    previous = totals.get(_shift_month(month, -1))
    first_month = db.query(func.min(BudgetEntry.month)).filter(BudgetEntry.user_id == user.id).scalar()
    history = []
    for i in range(HISTORY_MONTHS):
        m = _shift_month(first_history, i)
        t = totals.get(m, {"income": 0.0, "expenses": 0.0})
        history.append({"month": m, "income": round(t["income"], 2), "expenses": round(t["expenses"], 2)})
    now = totals.get(month, {"income": 0.0, "expenses": 0.0, "categories": {}})
    return {
        "month": month,
        "currency": DEFINITION.settings_for(row)["currency"].strip(),
        "entries": [_entry_dict(e) for e in entries],
        "income": round(now["income"], 2),
        "expenses": round(now["expenses"], 2),
        "previous": {
            "month": _shift_month(month, -1),
            "income": round(previous["income"], 2) if previous else None,
            "expenses": round(previous["expenses"], 2) if previous else None,
            "categories": {k: round(v, 2) for k, v in (previous or {}).get("categories", {}).items()},
        },
        "budgets": _budgets(db, user),
        "history": history,
        "first_month": first_month,
        "paths": _paths(db, user),
        "expense_categories": EXPENSE_CATEGORIES,
    }


@router.post("/entries")
def add_entry(body: EntryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    if db.query(func.count(BudgetEntry.id)).filter(BudgetEntry.user_id == user.id).scalar() >= MAX_ENTRIES:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_ENTRIES} entries")
    entry = BudgetEntry(user_id=user.id, month=body.month, amount=Decimal(str(round(body.amount, 2))))
    _set_path(entry, _check_categories(_clean_path(body.path)))
    db.add(entry)
    db.commit()
    return _entry_dict(entry)


@router.patch("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.query(BudgetEntry).filter(BudgetEntry.id == entry_id, BudgetEntry.user_id == user.id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if body.month is not None:
        entry.month = body.month
    if body.path is not None:
        _set_path(entry, _check_categories(_clean_path(body.path)))
    if body.amount is not None:
        entry.amount = Decimal(str(round(body.amount, 2)))
    db.commit()
    return _entry_dict(entry)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entry = db.query(BudgetEntry).filter(BudgetEntry.id == entry_id, BudgetEntry.user_id == user.id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": entry_id}


@router.post("/delete-group")
def delete_group(body: GroupIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a category and everything under it, in one month."""
    deleted = _under(db.query(BudgetEntry), user, _clean_path(body.path), body.month).delete(synchronize_session=False)
    db.commit()
    return {"deleted": deleted}


@router.put("/budgets")
def set_budgets(body: BudgetsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budgets = {}
    for name, amount in body.budgets.items():
        if amount is not None and not 0 <= amount <= 1e9:
            raise HTTPException(status_code=422, detail="Budgets must be positive numbers")
        if name.strip() and amount:
            category = next((c for c in EXPENSE_CATEGORIES if c.lower() == name.strip().lower()), None)
            if category is None:
                raise HTTPException(status_code=422, detail=f'"{name}" is not an expense sub-category')
            budgets[category] = round(float(amount), 2)
    row = widget_row(db, user, WIDGET_ID)
    row.config = {**(row.config or {}), "budgets": budgets}
    db.commit()
    return {"budgets": budgets}


# ---- CSV import / export ----

def _amount(value: Any) -> Optional[float]:
    """12.50 / 12,50 / 1.234,56 / 1,234.56 / "kr 45" -> float."""
    text = str(value).strip().replace("−", "-")
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".") if len(text) - text.rfind(",") - 1 in (1, 2) else text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -abs(number) if negative else number


def _month(value: str) -> Optional[str]:
    text = value.strip()
    for pattern, order in ((r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", (1, 2)), (r"^(\d{1,2})[/.-](\d{4})$", (2, 1)),
                           (r"^\d{1,2}[/.](\d{1,2})[/.](\d{4})$", (2, 1))):
        m = re.match(pattern, text)
        if m:
            year, month = int(m.group(order[0])), int(m.group(order[1]))
            return f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    try:
        return datetime.strptime(text, "%B %Y").strftime("%Y-%m")
    except ValueError:
        return None


def _parse_csv(text: str) -> tuple[list[tuple[str, list[str], float]], list[str]]:
    """(entries, problems) from a CSV with Month / Category / Sub-category... / Amount
    columns (a header row; column names matched loosely)."""
    text = text.lstrip("﻿")
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise HTTPException(status_code=422, detail="The file is empty")
    header = [h.strip().lower() for h in rows[0]]

    def col(*names: str) -> Optional[int]:
        return next((i for i, h in enumerate(header) if any(h == n or h.startswith(n + " ") for n in names)), None)

    month_col, amount_col = col("month", "date"), col("amount")
    levels = [col("category"), col("sub-category", "subcategory"), col("sub-sub-category"), col("sub-sub-sub-category")]
    if month_col is None or amount_col is None or levels[0] is None:
        raise HTTPException(status_code=422, detail="The first row needs Month, Category and Amount columns")

    entries, problems = [], []
    for line, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        cells = [c.strip() for c in row]
        get = lambda i, cells=cells: cells[i] if i is not None and i < len(cells) else ""  # noqa: E731
        month, amount = _month(get(month_col)), _amount(get(amount_col))
        path = [get(i) for i in levels]
        while path and not path[-1]:
            path.pop()
        if month is None or amount is None or not path or any(not p for p in path) or any(len(p) > 120 for p in path):
            problems.append(f"line {line}: {', '.join(row)[:80]}")
            continue
        try:
            path = _check_categories(path)
        except HTTPException as e:
            problems.append(f"line {line}: {e.detail}"[:160])
            continue
        entries.append((month, path, round(amount, 2)))
    return entries, problems


@router.post("/import")
def import_csv(body: ImportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    widget_row(db, user, WIDGET_ID)
    entries, problems = _parse_csv(body.csv)
    existing = 0 if body.replace else db.query(func.count(BudgetEntry.id)).filter(BudgetEntry.user_id == user.id).scalar()
    if existing + len(entries) > MAX_ENTRIES:
        raise HTTPException(status_code=422, detail=f"That would be more than {MAX_ENTRIES} entries")
    if body.replace:
        db.query(BudgetEntry).filter(BudgetEntry.user_id == user.id).delete(synchronize_session=False)
    for month, path, amount in entries:
        entry = BudgetEntry(user_id=user.id, month=month, amount=Decimal(str(amount)))
        _set_path(entry, path)
        db.add(entry)
    db.commit()
    return {"imported": len(entries), "skipped": len(problems), "problems": problems[:10]}


@router.get("/export")
def export_csv(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    entries = (
        db.query(BudgetEntry)
        .filter(BudgetEntry.user_id == user.id)
        .order_by(BudgetEntry.month, BudgetEntry.category, BudgetEntry.sub1, BudgetEntry.sub2, BudgetEntry.sub3)
        .all()
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_HEADER)
    for e in entries:
        path = _path(e)
        writer.writerow([e.month, *path, *[""] * (LEVELS - len(path)), f"{e.amount:.2f}"])
    return Response(
        content=out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="budget-{date.today().isoformat()}.csv"'},
    )
