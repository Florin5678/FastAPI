# Projects widget: a project tracker. Projects hold tasks; tasks hold comments. Both
# projects and tasks have an optional deadline (a local date) and can be marked completed.
# Everything is stored in the widget's integrations row:
#   config["projects"] = [{id, name, deadline, color, done, done_at, created_at,
#                          tasks: [{id, title, deadline, done, done_at, created_at,
#                                   comments: [{id, text, created_at, edited_at}]}]}]
# Projects and tasks are kept in the user's order (the list order). New ones, and ones whose
# deadline changes, are slotted in by date (before the first item due later; no deadline = last),
# and a list can be sorted by date again. Claude edits the same data through the connector.
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.timeutil import local_today
from app.models import Integration, User
from app.widgets.registry import WidgetContext, WidgetDefinition, register, widget_row

WIDGET_ID = "projects"
MAX_PROJECTS = 100
MAX_TASKS = 300  # per project
MAX_COMMENTS = 100  # per task
SOON_DAYS = 7  # the briefing lists tasks due within this many days (and overdue ones)
# A project's background tint (the frontend maps each to a light and a dark shade)
Color = Literal["blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "gray"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _projects(row: Integration) -> list[dict]:
    return [_copy(p) for p in (row.config or {}).get("projects", [])]


def _copy(project: dict) -> dict:
    """A deep copy, so edits never touch the row's config until it's saved."""
    return {**project, "tasks": [{**t, "comments": [dict(c) for c in t.get("comments", [])]} for t in project.get("tasks", [])]}


def _by_date(item: dict) -> tuple:
    return (item.get("deadline") is None, item.get("deadline") or "")


def _place(items: list[dict], item: dict) -> None:
    """Insert `item` at its date position: before the first item due later (or without a deadline)."""
    if item in items:
        items.remove(item)
    key = _by_date(item)
    index = next((i for i, other in enumerate(items) if _by_date(other) > key), len(items))
    items.insert(index, item)


def _reorder(items: list[dict], ids: list[str], what: str) -> list[dict]:
    """The items in the order of `ids`; any not listed keep their order after them."""
    by_id = {i["id"]: i for i in items}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown {what}: {', '.join(unknown)}")
    listed = list(dict.fromkeys(ids))
    return [by_id[i] for i in listed] + [i for i in items if i["id"] not in listed]


def _save(row: Integration, projects: list[dict]) -> None:
    row.config = {**(row.config or {}), "projects": projects}  # JSON columns aren't mutation-tracked
    row.updated_at = datetime.utcnow()


def _find_project(projects: list[dict], project_id: str) -> dict:
    for p in projects:
        if p["id"] == project_id:
            return p
    raise HTTPException(status_code=404, detail="Project not found")


def _find_task(projects: list[dict], task_id: str) -> tuple[dict, dict]:
    for p in projects:
        for t in p["tasks"]:
            if t["id"] == task_id:
                return p, t
    raise HTTPException(status_code=404, detail="Task not found")


def _find_comment(projects: list[dict], comment_id: str) -> tuple[dict, dict, dict]:
    for p in projects:
        for t in p["tasks"]:
            for c in t["comments"]:
                if c["id"] == comment_id:
                    return p, t, c
    raise HTTPException(status_code=404, detail="Comment not found")


def project_of(db: Session, user: User, *, project_id: str | None = None, task_id: str | None = None,
               comment_id: str | None = None) -> dict:
    """A copy of the project that holds this project / task / comment (for the connector's undo)."""
    projects = _projects(widget_row(db, user, WIDGET_ID))
    if project_id:
        return _find_project(projects, project_id)
    if task_id:
        return _find_task(projects, task_id)[0]
    return _find_comment(projects, comment_id or "")[0]


def restore_projects(db: Session, user: User, saved: list[dict], order: Optional[list[str]] = None) -> None:
    """Undo: put projects back exactly as they were (same ids), replacing their current state, and
    the projects back in their earlier order."""
    row = widget_row(db, user, WIDGET_ID)
    current = _projects(row)
    for project in saved:
        index = next((i for i, p in enumerate(current) if p["id"] == project["id"]), len(current))
        current[index:index + 1] = [_copy(project)]
    if order:
        current = _reorder(current, [i for i in order if any(p["id"] == i for p in current)], "project")
    _save(row, current)
    db.commit()


def project_order(db: Session, user: User) -> list[str]:
    return [p["id"] for p in _projects(widget_row(db, user, WIDGET_ID))]


# ---- Widget ----

def _progress(project: dict) -> dict:
    return {"done": sum(t["done"] for t in project["tasks"]), "total": len(project["tasks"])}


def fetch(db: Session, user: User, settings: dict, ctx: WidgetContext) -> dict:
    projects = _projects(widget_row(db, user, WIDGET_ID))
    for p in projects:
        p["progress"] = _progress(p)
    return {
        "today": local_today(ctx.tz).isoformat(),
        "projects": [p for p in projects if not p["done"]],
        "completed": sorted((p for p in projects if p["done"]), key=lambda p: p.get("done_at") or "", reverse=True),
    }


def _when(deadline: str, today: date) -> str:
    days = (date.fromisoformat(deadline) - today).days
    if days < 0:
        return f"OVERDUE since {date.fromisoformat(deadline):%a %d %b}"
    if days == 0:
        return "due today"
    if days == 1:
        return "due tomorrow"
    return f"due {date.fromisoformat(deadline):%a %d %b}"


def _task_line(t: dict, today: date) -> str:
    parts = [_when(t["deadline"], today) if t.get("deadline") else "no deadline"]
    if t["comments"]:
        latest = " ".join(t["comments"][-1]["text"].split())
        parts.append(f"{len(t['comments'])} comment{'s' if len(t['comments']) != 1 else ''}, latest: "
                     f"\"{latest[:150]}{'…' if len(latest) > 150 else ''}\"")
    return f"  - {t['title']} ({'; '.join(parts)})"


def brief(data: dict, limit: int | None = None) -> str:
    """Every open project with its open tasks (in the user's order), then what's overdue or due soon."""
    today = date.fromisoformat(data["today"])
    if not data["projects"]:
        return "No open projects."
    budget = limit or 30  # open tasks listed in all
    soon = (today + timedelta(days=SOON_DAYS)).isoformat()
    lines = [f"Open projects ({len(data['projects'])}, in the user's order), each with its open tasks in order:"]
    upcoming, listed = [], 0
    for p in data["projects"]:
        open_tasks = [t for t in p["tasks"] if not t["done"]]
        head = f"- {p['name']}: {p['progress']['done']}/{p['progress']['total']} tasks done"
        lines.append(head + (f", project {_when(p['deadline'], today)}" if p.get("deadline") else ""))
        shown = open_tasks[:max(0, budget - listed)]
        lines += [_task_line(t, today) for t in shown]
        listed += len(shown)
        if len(shown) < len(open_tasks):
            lines.append(f"  (+{len(open_tasks) - len(shown)} more open tasks)")
        upcoming += [(t["deadline"], p["name"], t) for t in open_tasks if t.get("deadline") and t["deadline"] <= soon]
    upcoming.sort(key=lambda u: u[0])
    if upcoming:
        lines.append(f"Overdue or due in the next {SOON_DAYS} days: "
                     + "; ".join(f"{t['title']} ({name}, {_when(deadline, today)})" for deadline, name, t in upcoming))
    else:
        lines.append(f"No tasks overdue or due in the next {SOON_DAYS} days.")
    return "\n".join(lines)


register(WidgetDefinition(
    id=WIDGET_ID,
    name="Projects",
    description="A project tracker: tasks grouped by project with deadlines, comments on tasks and completed ticks; reorder them or sort by date.",
    fetch=fetch,
    brief=brief,
    default_size=(4, 10),
    min_size=(3, 5),
    refresh_seconds=300,
    enabled_by_default=True,
))


# ---- Routes used by the widget (and the connector) ----

router = APIRouter(prefix=f"/widgets/{WIDGET_ID}", tags=["widgets"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    deadline: Optional[date] = None
    color: Optional[Color] = None  # none = the tile's own background


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    deadline: Optional[date] = None  # send null to clear
    color: Optional[Color] = None  # send null for no colour
    done: Optional[bool] = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    deadline: Optional[date] = None


class TaskPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    deadline: Optional[date] = None  # send null to clear
    done: Optional[bool] = None
    project_id: Optional[str] = None  # move it to another project


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class OrderIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=MAX_TASKS)  # the new order (unlisted ones follow)
    by_date: bool = False  # instead: sort the whole list by deadline (no deadline last)


def _text(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(status_code=422, detail=f"The {what} can't be empty")
    return value


def _set_done(item: dict, done: bool) -> None:
    if item["done"] != done:
        item["done"] = done
        item["done_at"] = _now() if done else None


def _deadline(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def _load(db: Session, user: User) -> tuple[Integration, list[dict]]:
    row = widget_row(db, user, WIDGET_ID)
    return row, _projects(row)


def _commit(db: Session, row: Integration, projects: list[dict]) -> None:
    _save(row, projects)
    db.commit()


@router.post("/projects")
def add_project(body: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    if len(projects) >= MAX_PROJECTS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_PROJECTS} projects; delete some old ones first")
    project = {"id": _new_id(), "name": _text(body.name, "project name"), "deadline": _deadline(body.deadline),
               "color": body.color, "done": False, "done_at": None, "created_at": _now(), "tasks": []}
    _place(projects, project)
    _commit(db, row, projects)
    return project


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    project = _find_project(projects, project_id)
    if body.name is not None:
        project["name"] = _text(body.name, "project name")
    if "deadline" in body.model_fields_set and project["deadline"] != _deadline(body.deadline):
        project["deadline"] = _deadline(body.deadline)
        _place(projects, project)
    if "color" in body.model_fields_set:
        project["color"] = body.color
    if body.done is not None:
        _set_done(project, body.done)
    _commit(db, row, projects)
    return project


@router.put("/projects/order")
def order_projects(body: OrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Reorder the projects: `ids` in the new order, or by_date=true to sort them by deadline."""
    row, projects = _load(db, user)
    projects = sorted(projects, key=_by_date) if body.by_date else _reorder(projects, body.ids, "project")
    _commit(db, row, projects)
    return {"order": [p["id"] for p in projects]}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    _find_project(projects, project_id)
    _commit(db, row, [p for p in projects if p["id"] != project_id])
    return {"deleted": project_id}


@router.post("/projects/{project_id}/tasks")
def add_task(project_id: str, body: TaskIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    project = _find_project(projects, project_id)
    if len(project["tasks"]) >= MAX_TASKS:
        raise HTTPException(status_code=422, detail=f"A project holds up to {MAX_TASKS} tasks")
    task = {"id": _new_id(), "title": _text(body.title, "task"), "deadline": _deadline(body.deadline),
            "done": False, "done_at": None, "created_at": _now(), "comments": []}
    _place(project["tasks"], task)
    _commit(db, row, projects)
    return task


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskPatch, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    project, task = _find_task(projects, task_id)
    if body.title is not None:
        task["title"] = _text(body.title, "task")
    if "deadline" in body.model_fields_set and task["deadline"] != _deadline(body.deadline):
        task["deadline"] = _deadline(body.deadline)
        _place(project["tasks"], task)
    if body.done is not None:
        _set_done(task, body.done)
    if body.project_id and body.project_id != project["id"]:
        target = _find_project(projects, body.project_id)
        if len(target["tasks"]) >= MAX_TASKS:
            raise HTTPException(status_code=422, detail=f"A project holds up to {MAX_TASKS} tasks")
        project["tasks"].remove(task)
        _place(target["tasks"], task)
    _commit(db, row, projects)
    return task


@router.put("/projects/{project_id}/tasks/order")
def order_tasks(project_id: str, body: OrderIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Reorder a project's tasks: `ids` in the new order, or by_date=true to sort them by deadline."""
    row, projects = _load(db, user)
    project = _find_project(projects, project_id)
    tasks = project["tasks"]
    project["tasks"] = sorted(tasks, key=_by_date) if body.by_date else _reorder(tasks, body.ids, "task")
    _commit(db, row, projects)
    return {"order": [t["id"] for t in project["tasks"]]}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    project, task = _find_task(projects, task_id)
    project["tasks"].remove(task)
    _commit(db, row, projects)
    return {"deleted": task_id}


@router.post("/tasks/{task_id}/comments")
def add_comment(task_id: str, body: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    _, task = _find_task(projects, task_id)
    if len(task["comments"]) >= MAX_COMMENTS:
        raise HTTPException(status_code=422, detail=f"A task holds up to {MAX_COMMENTS} comments")
    comment = {"id": _new_id(), "text": _text(body.text, "comment"), "created_at": _now(), "edited_at": None}
    task["comments"].append(comment)  # oldest first
    _commit(db, row, projects)
    return comment


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: str, body: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    _, _, comment = _find_comment(projects, comment_id)
    comment["text"] = _text(body.text, "comment")
    comment["edited_at"] = _now()
    _commit(db, row, projects)
    return comment


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row, projects = _load(db, user)
    _, task, comment = _find_comment(projects, comment_id)
    task["comments"].remove(comment)
    _commit(db, row, projects)
    return {"deleted": comment_id}

