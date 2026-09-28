# Courses widget: Google Docs and PDFs the user picks from their Google Drive (with a
# file browser in the widget), with upcoming deadlines read from their text.
# Read-only (drive.readonly scope). Summaries happen on claude.ai with the user's own
# subscription: the widget copies a file's text and opens Claude (see the /text route).
# Only the deadlines go into the Assistant briefing.
#
# Reading files is slow (downloads + PDF parsing on a small server), so the widget
# never does it inside a request: fetch() only checks the picked files' metadata and
# shows what is already known, and a background thread reads new or changed files one at a time.
# What it finds (deadline candidates per file) is saved in the widget's row
# (config["file_cache"]), so files are only read again when they change.
import io
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.google_tokens import get_valid_access_token
from app.core.database import SessionLocal, get_db
from app.core.google_api import NeedsSetup, google_get
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import Integration, User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "courses"
API = "https://www.googleapis.com/drive/v3/files"
DOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
FOLDER = "application/vnd.google-apps.folder"
MAX_FILES = 40  # files the user can pick
FILE_FIELDS = "id,name,mimeType,modifiedTime,webViewLink,size,trashed"
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PDF_PAGES = 80
PDF_SECONDS = 25  # stop extracting a PDF's text after this long (slow server)
MAX_TEXT_CHARS = 200_000  # per file; more than enough to paste into claude.ai
MAX_CANDIDATES = 120  # dated lines kept per file
MAX_DEADLINES = 50
logger = logging.getLogger(__name__)

# Background reads in progress: user id -> {"done": n, "total": m}
_scans: dict[int, dict] = {}
_scans_lock = threading.Lock()

MONTHS = {
    # English and Danish month names / abbreviations
    "jan": 1, "january": 1, "januar": 1, "feb": 2, "february": 2, "februar": 2,
    "mar": 3, "march": 3, "marts": 3, "apr": 4, "april": 4, "may": 5, "maj": 5,
    "jun": 6, "june": 6, "juni": 6, "jul": 7, "july": 7, "juli": 7, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
DATE_PATTERNS = [
    # 2026-10-14
    (re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), lambda m: (m[1], m[2], m[3])),
    # 14 Oct, 14th of October 2026, 14. oktober
    (re.compile(r"(?<![\d.])(\d{1,2})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?" + _MONTH + r"(?:,?\s+(\d{4}))?(?![a-z])", re.I),
     lambda m: (m[3], MONTHS[m[2].lower()], m[1])),
    # Oct 14, October 14th, 2026
    (re.compile(r"(?<![a-z])" + _MONTH + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?(?!\d)", re.I),
     lambda m: (m[3], MONTHS[m[1].lower()], m[2])),
    # 14/10, 14/10/2026 (day first)
    (re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])"), lambda m: (m[3], m[2], m[1])),
    # 14.10.2026 (dots need a year: "3.2" is usually a section number)
    (re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?![\d.])"), lambda m: (m[3], m[2], m[1])),
]


def _make_date(year: Optional[str], month, day, today: date) -> Optional[date]:
    try:
        if year:
            y = int(year)
            return date(y + 2000 if y < 100 else y, int(month), int(day))
        guess = date(today.year, int(month), int(day))
        # No year: the next time that date comes around (dates long past mean next year)
        return guess if guess >= today - timedelta(days=120) else date(today.year + 1, int(month), int(day))
    except ValueError:
        return None


def candidates(text: str, keywords: list[str]) -> list[list[str]]:
    """[label, line] for lines that mention a date and a deadline word (in the line or
    the line before, e.g. a heading). Saved per file; dates are resolved at display
    time (a date without a year depends on today)."""
    if not keywords:
        return []
    keyword = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")", re.I)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    found = []
    for i, line in enumerate(lines):
        if len(line) > 300 or not _has_date(line):
            continue
        # A short line without a date just above (e.g. "Assignment 2" over "Due: 14 Oct")
        # counts as this line's heading
        previous = lines[i - 1] if i else ""
        heading = previous if previous and len(previous) <= 80 and not _has_date(previous) else ""
        if not (keyword.search(line) or (heading and keyword.search(heading))):
            continue
        label = f"{heading} — {line}" if heading and (len(line) < 30 or not keyword.search(line)) else line
        found.append([label, line])
        if len(found) >= MAX_CANDIDATES:
            break
    return found


def upcoming(found: list[list[str]], today: date, days: int) -> list[tuple[date, str]]:
    """(date, label) for the candidates whose date is within `days` from today."""
    out = []
    for label, line in found:
        for pattern, parts in DATE_PATTERNS:
            for match in pattern.finditer(line):
                day = _make_date(*parts(match), today)
                if day and today <= day <= today + timedelta(days=days):
                    out.append((day, label))
    return out


def find_deadlines(text: str, keywords: list[str], today: date, days: int) -> list[tuple[date, str]]:
    return upcoming(candidates(text, keywords), today, days)


def _has_date(line: str) -> bool:
    return any(pattern.search(line) for pattern, _ in DATE_PATTERNS)


def _file_dict(meta: dict, course: str) -> dict:
    return {
        "id": meta["id"], "name": meta["name"], "course": course,
        "kind": "doc" if meta["mimeType"] == DOC else "pdf",
        "modified": meta.get("modifiedTime"), "link": meta.get("webViewLink"),
        "size": int(meta.get("size") or 0),
    }


def _picked_files(token: str, picked: list[dict]) -> tuple[list[dict], list[str]]:
    """(current metadata of the picked files, names of picked files that are gone)."""
    def get(p: dict) -> Optional[dict]:
        try:
            return google_get(f"{API}/{p['id']}", token, {"fields": FILE_FIELDS, "supportsAllDrives": "true"},
                              service="Google Drive", not_found="gone")
        except HTTPException as e:
            if e.status_code == 404:
                return None
            raise

    with ThreadPoolExecutor(max_workers=8) as pool:
        metas = list(pool.map(get, picked))
    files, missing = [], []
    for p, meta in zip(picked, metas, strict=True):
        if meta is None or meta.get("trashed") or meta.get("mimeType") not in (DOC, PDF):
            missing.append(p.get("name") or p["id"])
        else:
            files.append(_file_dict(meta, p.get("course", "")))
    return files, missing


def browse(token: str, folder: str = "root", query: str = "") -> dict:
    """Folders, Docs and PDFs in a Drive folder ("root" = My Drive, "shared" = Shared
    with me), or matching a search."""
    kinds = f"(mimeType = '{FOLDER}' or mimeType = '{DOC}' or mimeType = '{PDF}')"
    if query.strip():
        safe = query.strip().replace("\\", "\\\\").replace("'", "\\'")
        q, name = f"name contains '{safe}' and trashed = false and {kinds}", f'Search: "{query.strip()}"'
    elif folder == "shared":
        q, name = f"sharedWithMe = true and trashed = false and {kinds}", "Shared with me"
    else:
        q = f"'{folder}' in parents and trashed = false and {kinds}"
        name = "My Drive" if folder == "root" else google_get(
            f"{API}/{folder}", token, {"fields": "name", "supportsAllDrives": "true"},
            service="Google Drive", not_found="Folder not found").get("name", "")
    page = google_get(API, token, {
        "q": q, "fields": "files(id,name,mimeType,modifiedTime)", "pageSize": 200,
        "orderBy": "folder,name", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
    }, service="Google Drive")
    items = [
        {"id": f["id"], "name": f["name"], "modified": f.get("modifiedTime"),
         "kind": "folder" if f["mimeType"] == FOLDER else "doc" if f["mimeType"] == DOC else "pdf"}
        for f in page.get("files", [])
    ]
    return {"folder": folder, "name": name, "items": items}


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # imported lazily: only needed for PDFs

    reader = PdfReader(io.BytesIO(data))
    started, parts, size = time.monotonic(), [], 0
    for page in reader.pages[:MAX_PDF_PAGES]:
        parts.append(page.extract_text() or "")
        size += len(parts[-1])
        if size > MAX_TEXT_CHARS or time.monotonic() - started > PDF_SECONDS:
            break
    return "\n".join(parts)


def file_text(token: str, f: dict) -> str:
    """A Doc's or PDF's text (downloaded now; nothing is kept in memory)."""
    if f["kind"] == "doc":
        text = google_get(f"{API}/{f['id']}/export", token, {"mimeType": "text/plain"}, service="Google Drive", raw=True).text
    elif f["size"] > MAX_PDF_BYTES:
        text = ""
    else:
        data = google_get(f"{API}/{f['id']}", token, {"alt": "media", "supportsAllDrives": "true"}, service="Google Drive", raw=True).content
        try:
            text = _pdf_text(data)
        except Exception:
            logger.warning("Courses: couldn't read PDF %s", f["name"], exc_info=True)
            text = ""
    return text.lstrip("\ufeff")[:MAX_TEXT_CHARS]  # Docs exports start with a BOM


def _keywords(settings: dict) -> list[str]:
    return [k.strip() for k in settings["keywords"].split(",") if k.strip()]


def _file_key(f: dict, keywords: list[str]) -> str:
    """Changes when the file or the deadline words change (then the file is read again)."""
    return f"{f['modified']}|{','.join(k.lower() for k in keywords)}"


def _scan(user_id: int, files: list[dict], keywords: list[str]) -> None:
    """Background thread: read `files` one by one and save each result as it's done."""
    db = SessionLocal()
    try:
        token = get_valid_access_token(db, user_id)
        for f in files:
            try:
                text = file_text(token, f)
            except NeedsSetup:
                break
            except Exception:
                logger.warning("Courses: couldn't read %s", f["name"], exc_info=True)
                text = ""
            entry = {"key": _file_key(f, keywords), "readable": bool(text.strip()), "found": candidates(text, keywords)}
            del text
            # Re-read the row right before writing so a layout/settings change made
            # meanwhile isn't overwritten; only file_cache changes here
            db.expire_all()
            row = (
                db.query(Integration)
                .filter(Integration.user_id == user_id, Integration.app_name == WIDGET_ID, Integration.status == "active")
                .first()
            )
            if row is None:
                break
            cache = dict((row.config or {}).get("file_cache") or {})
            cache[f["id"]] = entry
            row.config = {**(row.config or {}), "file_cache": cache}
            db.commit()
            with _scans_lock:
                _scans[user_id]["done"] += 1
    except Exception:
        logger.warning("Courses: background read stopped", exc_info=True)
    finally:
        db.close()
        with _scans_lock:
            _scans.pop(user_id, None)


def _picked(row: Integration) -> list[dict]:
    return list((row.config or {}).get("picked") or [])


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    row = widget_row(db, user, WIDGET_ID)
    picked = _picked(row)
    try:
        token = get_valid_access_token(db, user.id)
        if not picked:
            browse(token, "root")  # checks the Drive permission before showing the picker
            return {"needs_setup": "no_file"}
        files, missing = _picked_files(token, picked)
    except NeedsSetup as setup:
        return {"needs_setup": setup.reason}
    except ValueError:
        return {"needs_setup": "permission"}  # no usable Google token

    keywords = _keywords(settings)
    cache = (row.config or {}).get("file_cache") or {}
    current = {f["id"] for f in files}
    if set(cache) - current:
        # Forget files that are no longer picked
        cache = {k: v for k, v in cache.items() if k in current}
        row.config = {**(row.config or {}), "file_cache": cache}
        db.commit()
    pending = [f for f in files if (cache.get(f["id"]) or {}).get("key") != _file_key(f, keywords)]

    with _scans_lock:
        scan = _scans.get(user.id)
        if pending and scan is None:
            scan = _scans[user.id] = {"done": 0, "total": len(pending)}
            threading.Thread(target=_scan, args=(user.id, pending, keywords), daemon=True).start()
        progress = dict(scan) if scan else None

    today = local_today(ctx.tz)
    seen, deadlines = set(), []
    for f in files:
        entry = cache.get(f["id"])
        f["readable"] = entry["readable"] if entry else None  # None: not read yet
        for day, line in upcoming((entry or {}).get("found", []), today, settings["days"]):
            key = (day, line.lower())
            if key not in seen:
                seen.add(key)
                deadlines.append({"date": day.isoformat(), "text": line, "file": f["name"], "course": f["course"], "link": f["link"]})
    deadlines.sort(key=lambda d: d["date"])

    return {
        "needs_setup": None,
        "days": settings["days"],
        "missing": missing,  # picked files that were deleted or can't be opened any more
        "files": sorted(files, key=lambda f: f["modified"] or "", reverse=True),
        "deadlines": deadlines[:MAX_DEADLINES],
        # Files still being read in the background (the widget refreshes until done)
        "reading": {"done": progress["done"], "total": progress["total"]} if progress else None,
    }


def brief(data: dict, limit: int | None = None) -> str:
    if data["needs_setup"]:
        return "Course folder not connected yet."
    if not data["deadlines"]:
        return f"No deadlines found in my course files for the next {data['days']} days."
    shown = data["deadlines"][:limit or 10]
    lines = ["Upcoming deadlines found in my course files (read automatically from the text, so double-check):"]
    for d in shown:
        day = datetime.fromisoformat(d["date"])
        source = " / ".join(p for p in (d["course"], d["file"]) if p)
        lines.append(f"- {day:%a %d %b}: {d['text']} ({source})")
    if len(data["deadlines"]) > len(shown):
        lines.append(f"(+{len(data['deadlines']) - len(shown)} more)")
    return "\n".join(lines)


DEFINITION = register(WidgetDefinition(
    id=WIDGET_ID,
    name="Courses",
    description="Upcoming deadlines from Google Docs and PDFs you pick in your Drive, and one click to summarize a file with Claude (read-only).",
    fetch=fetch,
    brief=brief,
    default_size=(4, 9),
    min_size=(3, 6),
    refresh_seconds=3600,
    config_fields=(
        ConfigField("days", "Deadlines: days ahead", "number", default=60, min=7, max=365),
        ConfigField("keywords", "Deadline words (comma-separated)", "text",
                    default="due, deadline, exam, assignment, hand-in, hand in, submit, submission, quiz, test, presentation, project, aflevering, eksamen"),
    ),
))


# ---- Routes used by the widget ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class PickedFile(BaseModel):
    id: str = Field(min_length=5, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    course: str = Field("", max_length=120)  # the folder it was picked from


class PickIn(BaseModel):
    files: list[PickedFile] = Field(max_length=MAX_FILES)


def _token_or_409(db: Session, user: User) -> str:
    try:
        return get_valid_access_token(db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail="Reconnect Google Drive from the widget first") from e


@router.get("/browse")
def browse_route(folder: str = "root", q: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The file picker: a Drive folder's folders/Docs/PDFs, Shared with me, or a search."""
    widget_row(db, user, WIDGET_ID)
    if folder not in ("root", "shared") and not re.fullmatch(r"[A-Za-z0-9_-]{5,200}", folder):
        raise HTTPException(status_code=422, detail="Unknown folder")
    try:
        return browse(_token_or_409(db, user), folder, q[:100])
    except NeedsSetup as e:
        raise HTTPException(status_code=409, detail="Reconnect Google Drive from the widget first") from e


@router.put("/files")
def pick_files(body: PickIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Save which files the widget reads (checked against Drive: Docs and PDFs only)."""
    row = widget_row(db, user, WIDGET_ID)
    wanted = list({f.id: f for f in body.files}.values())  # no duplicates
    try:
        files, missing = _picked_files(_token_or_409(db, user), [{"id": f.id, "course": f.course.strip()} for f in wanted])
    except NeedsSetup as e:
        raise HTTPException(status_code=409, detail="Reconnect Google Drive from the widget first") from e
    if missing:
        raise HTTPException(status_code=422, detail="Only Google Docs and PDFs you can open can be picked")
    row.config = {**(row.config or {}), "picked": [{"id": f["id"], "name": f["name"], "course": f["course"]} for f in files]}
    db.commit()
    return {"files": [{"id": f["id"], "name": f["name"], "course": f["course"]} for f in files]}


@router.get("/files")
def picked_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The current pick (for the picker's checkboxes)."""
    return {"files": _picked(widget_row(db, user, WIDGET_ID))}


@router.get("/files/{file_id}/text")
def file_text_route(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A picked file's text, for pasting into claude.ai. Only picked files can be read
    this way."""
    picked = [p for p in _picked(widget_row(db, user, WIDGET_ID)) if p["id"] == file_id]
    if not picked:
        raise HTTPException(status_code=404, detail="That file isn't picked in the Courses widget")
    try:
        files, _ = _picked_files(_token_or_409(db, user), picked)
        if not files:
            raise HTTPException(status_code=404, detail="That file was deleted or can't be opened any more")
        f = files[0]
        text = file_text(_token_or_409(db, user), f)
    except NeedsSetup as e:
        raise HTTPException(status_code=409, detail="Reconnect Google Drive from the widget first") from e
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be read from this file (a scanned PDF, or too large)")
    return {"name": f["name"], "course": f["course"], "text": text}
