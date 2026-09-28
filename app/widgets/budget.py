# Budget widget: this month's spending vs budget, from a Google Sheet of transactions.
# Read-only (drive.readonly scope, which also covers the Sheets API). The sheet has one
# row per transaction (date, amount, category columns, names set in the widget's
# settings) and optionally a budget tab with a monthly budget per category.
# Not part of the Assistant briefing (no brief()), on purpose: money stays out of it.
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth.google_tokens import get_valid_access_token
from app.core.google_api import NeedsSetup, google_get
from app.core.timeutil import local_today
from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register

WIDGET_ID = "budget"
API = "https://sheets.googleapis.com/v4/spreadsheets"
HEADER_SEARCH_ROWS = 10  # the header row may sit below a title
SHEETS_EPOCH = date(1899, 12, 30)  # Google Sheets date serial number 0
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d/%m/%y", "%d.%m.%y", "%d-%m-%y")


def spreadsheet_id(link: str) -> Optional[str]:
    """The id from a Google Sheets link (or a bare id)."""
    link = link.strip()
    match = re.search(r"/d/([A-Za-z0-9_-]{20,})", link)
    if match:
        return match.group(1)
    return link if re.fullmatch(r"[A-Za-z0-9_-]{20,}", link) else None


def _date(value: Any) -> Optional[date]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return SHEETS_EPOCH + timedelta(days=int(value))  # a real date cell (serial number)
    if isinstance(value, str) and value.strip():
        text = value.strip().split(" ")[0].split("T")[0]
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _amount(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace("−", "-")
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9,.\-]", "", text)  # drop currency symbols, spaces
    if not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        # whichever comes last is the decimal separator: 1.234,56 or 1,234.56
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        # 12,50 (decimal) vs 1,250 (thousands)
        text = text.replace(",", ".") if len(text) - text.rfind(",") - 1 in (1, 2) else text.replace(",", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -abs(number) if negative else number


def _header(rows: list[list], *names: str) -> Optional[tuple[int, dict[str, int]]]:
    """(row index, {name: column}) of the first row containing all the column names."""
    wanted = [n.strip().lower() for n in names]
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        cells = [str(c).strip().lower() for c in row]
        if all(w in cells for w in wanted):
            return i, {name: cells.index(w) for name, w in zip(names, wanted, strict=True)}
    return None


def _cell(row: list, col: int) -> Any:
    return row[col] if col < len(row) else None


def _tab_range(tab: str) -> str:
    return "'" + tab.replace("'", "''") + "'"


def _budgets(rows: list[list], category_col: str) -> dict[str, tuple[str, float]]:
    """{category lowercase: (category, monthly budget)} from the budget tab: the category
    column plus a column named like "Budget"/"Amount"/"Limit" (else the next column)."""
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        cells = [str(c).strip().lower() for c in row]
        if category_col.lower() not in cells:
            continue
        cat = cells.index(category_col.lower())
        amount = next((j for j, c in enumerate(cells) if j != cat and c in ("budget", "monthly budget", "amount", "limit")), cat + 1)
        budgets = {}
        for r in rows[i + 1:]:
            name, value = str(_cell(r, cat) or "").strip(), _amount(_cell(r, amount))
            if name and value is not None:
                budgets[name.lower()] = (name, abs(value))
        return budgets
    return {}


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    sheet_id = spreadsheet_id(settings["sheet"])
    if not sheet_id:
        return {"needs_setup": "no_file" if not settings["sheet"].strip() else "bad_link"}

    try:
        token = get_valid_access_token(db, user.id)
        not_found = "Couldn't open that spreadsheet. Check the link in this widget's settings."
        meta = google_get(f"{API}/{sheet_id}", token, {"fields": "properties.title,sheets.properties.title"},
                          service="Google Sheets", not_found=not_found)
        tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
        tx_tab = settings["transactions_tab"].strip() or tabs[0]
        if tx_tab not in tabs:
            raise HTTPException(status_code=422, detail=f"No tab named {tx_tab!r} in the sheet (tabs: {', '.join(tabs)}). Fix it in this widget's settings.")
        budget_tab = settings["budget_tab"].strip()
        ranges = [_tab_range(tx_tab)] + ([_tab_range(budget_tab)] if budget_tab in tabs and budget_tab != tx_tab else [])
        values = google_get(f"{API}/{sheet_id}/values:batchGet", token, {
            "ranges": ranges,
            "valueRenderOption": "UNFORMATTED_VALUE",  # numbers as numbers
            "dateTimeRenderOption": "SERIAL_NUMBER",  # dates as serial numbers (no locale guessing)
        }, service="Google Sheets")
    except NeedsSetup as setup:
        return {"needs_setup": setup.reason}
    except ValueError:
        return {"needs_setup": "permission"}  # no usable Google token

    tables = [v.get("values", []) for v in values.get("valueRanges", [])]
    rows = tables[0] if tables else []
    columns = (settings["date_column"], settings["amount_column"], settings["category_column"])
    found = _header(rows, *columns)
    if found is None:
        raise HTTPException(status_code=422, detail=(
            f"Couldn't find the columns {', '.join(repr(c) for c in columns)} in the {tx_tab!r} tab. "
            "Set the column names in this widget's settings."
        ))
    header_row, col = found

    transactions, skipped = [], 0
    for row in rows[header_row + 1:]:
        day, amount = _date(_cell(row, col[columns[0]])), _amount(_cell(row, col[columns[1]]))
        if day is None or amount is None:
            skipped += 1 if any(str(c).strip() for c in row) else 0
            continue
        transactions.append((day, amount, str(_cell(row, col[columns[2]]) or "").strip() or "Uncategorized"))

    # A sheet with negative amounts has expenses negative and income positive;
    # otherwise every row is an expense
    if any(amount < 0 for _, amount, _ in transactions):
        transactions = [(d, -a, c) for d, a, c in transactions if a < 0]

    today = local_today(ctx.tz)
    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    spent: dict[str, float] = {}
    names: dict[str, str] = {}
    last_month_total = 0.0
    for day, amount, category in transactions:
        if month_start <= day <= today:
            spent[category.lower()] = spent.get(category.lower(), 0.0) + amount
            names.setdefault(category.lower(), category)
        elif last_month_start <= day < month_start:
            last_month_total += amount

    budgets = _budgets(tables[1], settings["category_column"]) if len(tables) > 1 else {}
    categories = [
        {"category": name, "spent": round(spent.get(key, 0.0), 2), "budget": budget}
        for key, (name, budget) in budgets.items()
    ] + sorted(
        ({"category": names[key], "spent": round(total, 2), "budget": None} for key, total in spent.items() if key not in budgets),
        key=lambda c: -c["spent"],
    )

    return {
        "needs_setup": None,
        "title": meta.get("properties", {}).get("title"),
        "link": f"https://docs.google.com/spreadsheets/d/{sheet_id}",
        "month": month_start.isoformat()[:7],
        "last_month": last_month_start.isoformat()[:7],
        "currency": settings["currency"].strip(),
        "total": round(sum(spent.values()), 2),
        "last_month_total": round(last_month_total, 2),
        "budget_total": round(sum(b for _, b in budgets.values()), 2) if budgets else None,
        "has_budget_tab": bool(budgets),
        "categories": categories,
        "skipped_rows": skipped,
    }


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Budget",
    description="This month's spending vs your budget per category, from a Google Sheet of transactions (read-only).",
    fetch=fetch,
    default_size=(4, 8),
    min_size=(3, 5),
    refresh_seconds=1800,
    config_fields=(
        ConfigField("sheet", "Spreadsheet link", "text", default=""),
        ConfigField("transactions_tab", "Transactions tab (empty = first tab)", "text", default=""),
        ConfigField("date_column", "Date column", "text", default="Date"),
        ConfigField("amount_column", "Amount column", "text", default="Amount"),
        ConfigField("category_column", "Category column", "text", default="Category"),
        ConfigField("budget_tab", "Budget tab (Category + Budget columns)", "text", default="Budget"),
        ConfigField("currency", "Currency", "text", default="kr"),
    ),
))
