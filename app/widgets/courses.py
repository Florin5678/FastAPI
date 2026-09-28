# Courses widget: the Google Docs and PDFs in a Google Drive folder (and its
# subfolders, e.g. one per course), with upcoming deadlines read from their text.
# Read-only (drive.readonly scope). Summaries happen on claude.ai with the user's own
# subscription: the widget copies a file's text and opens Claude (see the /text route).
# Only the deadlines go into the Assistant briefing.
import io
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.google_tokens import get_valid_access_token
from app.core.database import get_db
from app.core.google_api import NeedsSetup, google_get
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import User
from app.widgets.registry import ConfigField, WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "courses"
API = "https://www.googleapis.com/drive/v3/files"
DOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
FOLDER = "application/vnd.google-apps.folder"
MAX_FILES = 60
MAX_FOLDERS = 30
MAX_DEPTH = 3
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 150
MAX_TEXT_CHARS = 200_000  # per file; more than enough to paste into claude.ai
MAX_DEADLINES = 50
logger = logging.getLogger(__name__)

# File text by (file id, modified time), so unchanged files aren't downloaded again
_text_cache: dict[tuple[str, str], str] = {}
_cache_lock = threading.Lock()

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


def folder_id(link: str) -> Optional[str]:
    """The id from a Google Drive folder link (or a bare id)."""
    link = link.strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]{10,})", link) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", link)
    if match:
        return match.group(1)
    return link if re.fullmatch(r"[A-Za-z0-9_-]{10,}", link) else None


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


def find_deadlines(text: str, keywords: list[str], today: date, days: int) -> list[tuple[date, str]]:
    """(date, line) for lines that mention a date within `days` from today and a
    deadline word (in the line or the line before, e.g. a heading)."""
    if not keywords:
        return []
    keyword = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")", re.I)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    found = []
    for i, line in enumerate(lines):
        if len(line) > 300:
            continue
        # A short line without a date just above (e.g. "Assignment 2" over "Due: 14 Oct")
        # counts as this line's heading
        previous = lines[i - 1] if i else ""
        heading = previous if previous and len(previous) <= 80 and not _has_date(previous) else ""
        if not (keyword.search(line) or (heading and keyword.search(heading))):
            continue
        label = f"{heading} — {line}" if heading and (len(line) < 30 or not keyword.search(line)) else line
        for pattern, parts in DATE_PATTERNS:
            for match in pattern.finditer(line):
                day = _make_date(*parts(match), today)
                if day and today <= day <= today + timedelta(days=days):
                    found.append((day, label))
    return found


def _has_date(line: str) -> bool:
    return any(pattern.search(line) for pattern, _ in DATE_PATTERNS)


def _list_files(token: str, root: str) -> tuple[str, list[dict]]:
    """(folder name, Docs and PDFs in the folder and its subfolders). Each file's
    "course" is the name of the top-level subfolder it's in ("" for the folder itself)."""
    name = google_get(f"{API}/{root}", token, {"fields": "name,mimeType", "supportsAllDrives": "true"},
                      service="Google Drive", not_found="Couldn't open that folder. Check the link in this widget's settings.")
    if name.get("mimeType") != FOLDER:
        raise HTTPException(status_code=422, detail="That link is a file, not a folder. Put your course files in a Drive folder and use the folder's link.")
    files, queue, folders_seen = [], [(root, "", 0)], 0
    while queue and len(files) < MAX_FILES:
        parent, course, depth = queue.pop(0)
        folders_seen += 1
        page_token = None
        while True:
            params = {
                "q": f"'{parent}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,size)",
                "pageSize": 200, "orderBy": "name",
                "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            page = google_get(API, token, params, service="Google Drive")
            for f in page.get("files", []):
                if f["mimeType"] == FOLDER and depth + 1 < MAX_DEPTH and folders_seen + len(queue) < MAX_FOLDERS:
                    queue.append((f["id"], course or f["name"], depth + 1))
                elif f["mimeType"] in (DOC, PDF) and len(files) < MAX_FILES:
                    files.append({
                        "id": f["id"], "name": f["name"], "course": course,
                        "kind": "doc" if f["mimeType"] == DOC else "pdf",
                        "modified": f.get("modifiedTime"), "link": f.get("webViewLink"),
                        "size": int(f.get("size") or 0),
                    })
            page_token = page.get("nextPageToken")
            if not page_token:
                break
    return name.get("name", ""), files


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # imported lazily: only needed for PDFs

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES])


def file_text(token: str, f: dict) -> str:
    key = (f["id"], f["modified"] or "")
    with _cache_lock:
        if key in _text_cache:
            return _text_cache[key]
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
    text = text.lstrip("﻿")[:MAX_TEXT_CHARS]  # Docs exports start with a BOM
    with _cache_lock:
        for old in [k for k in _text_cache if k[0] == f["id"]]:
            del _text_cache[old]  # older versions of this file
        _text_cache[key] = text
    return text


def _keywords(settings: dict) -> list[str]:
    return [k.strip() for k in settings["keywords"].split(",") if k.strip()]


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    root = folder_id(settings["folder"])
    if not root:
        return {"needs_setup": "no_file" if not settings["folder"].strip() else "bad_link"}
    try:
        token = get_valid_access_token(db, user.id)
        folder_name, files = _list_files(token, root)

        def read(f: dict) -> str:
            try:
                return file_text(token, f)
            except NeedsSetup:
                raise
            except Exception:
                logger.warning("Courses: couldn't read %s", f["name"], exc_info=True)
                return ""

        with ThreadPoolExecutor(max_workers=6) as pool:
            texts = list(pool.map(read, files))
    except NeedsSetup as setup:
        return {"needs_setup": setup.reason}
    except ValueError:
        return {"needs_setup": "permission"}  # no usable Google token

    today = local_today(ctx.tz)
    keywords = _keywords(settings)
    seen, deadlines = set(), []
    for f, text in zip(files, texts, strict=True):
        f["readable"] = bool(text.strip())
        for day, line in find_deadlines(text, keywords, today, settings["days"]):
            key = (day, line.lower())
            if key not in seen:
                seen.add(key)
                deadlines.append({"date": day.isoformat(), "text": line, "file": f["name"], "course": f["course"], "link": f["link"]})
    deadlines.sort(key=lambda d: d["date"])

    return {
        "needs_setup": None,
        "folder": folder_name,
        "folder_link": f"https://drive.google.com/drive/folders/{root}",
        "days": settings["days"],
        "files": sorted(files, key=lambda f: f["modified"] or "", reverse=True),
        "deadlines": deadlines[:MAX_DEADLINES],
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
    description="Upcoming deadlines from the Google Docs and PDFs in a Drive folder, and one click to summarize a file with Claude (read-only).",
    fetch=fetch,
    brief=brief,
    default_size=(4, 9),
    min_size=(3, 6),
    refresh_seconds=3600,
    config_fields=(
        ConfigField("folder", "Course folder link (Google Drive)", "text", default=""),
        ConfigField("days", "Deadlines: days ahead", "number", default=60, min=7, max=365),
        ConfigField("keywords", "Deadline words (comma-separated)", "text",
                    default="due, deadline, exam, assignment, hand-in, hand in, submit, submission, quiz, test, presentation, project, aflevering, eksamen"),
    ),
))


# ---- Routes used by the widget ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


@router.get("/files/{file_id}/text")
def file_text_route(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A course file's text, for pasting into claude.ai. Only files in the widget's
    folder can be read this way."""
    root = folder_id(DEFINITION.settings_for(widget_row(db, user, WIDGET_ID))["folder"])
    if not root:
        raise HTTPException(status_code=422, detail="Set the course folder in this widget's settings first")
    try:
        token = get_valid_access_token(db, user.id)
        _, files = _list_files(token, root)
        f = next((f for f in files if f["id"] == file_id), None)
        if f is None:
            raise HTTPException(status_code=404, detail="That file isn't in your course folder")
        text = file_text(token, f)
    except (NeedsSetup, ValueError) as e:
        raise HTTPException(status_code=409, detail="Reconnect Google Drive from the widget first") from e
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be read from this file (a scanned PDF, or too large)")
    return {"name": f["name"], "course": f["course"], "text": text}

