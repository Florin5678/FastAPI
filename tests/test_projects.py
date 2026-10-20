from datetime import date, timedelta

from app.connector import tools
from app.widgets import projects


def _data(client):
    return client.get("/widgets/projects/data", params={"tz": "Europe/Copenhagen"}).json()["data"]


def test_tasks_are_in_date_order_within_a_project(client):
    p = client.post("/widgets/projects/projects", json={"name": "Thesis"}).json()
    for title, deadline in [("Write intro", "2026-11-20"), ("No date", None), ("Outline", "2026-11-01"), ("Submit", "2026-12-15")]:
        client.post(f"/widgets/projects/projects/{p['id']}/tasks", json={"title": title, "deadline": deadline})
    tasks = _data(client)["projects"][0]["tasks"]
    assert [t["title"] for t in tasks] == ["Outline", "Write intro", "Submit", "No date"]
    # Changing a deadline moves the task to its new place
    client.patch(f"/widgets/projects/tasks/{tasks[2]['id']}", json={"deadline": "2026-10-25"})
    assert [t["title"] for t in _data(client)["projects"][0]["tasks"]][0] == "Submit"


def test_projects_and_tasks_can_be_completed_and_reopened(client):
    p = client.post("/widgets/projects/projects", json={"name": "Move flat", "deadline": "2026-12-01"}).json()
    t = client.post(f"/widgets/projects/projects/{p['id']}/tasks", json={"title": "Book van"}).json()
    done = client.patch(f"/widgets/projects/tasks/{t['id']}", json={"done": True}).json()
    assert done["done"] and done["done_at"]
    assert _data(client)["projects"][0]["progress"] == {"done": 1, "total": 1}
    client.patch(f"/widgets/projects/projects/{p['id']}", json={"done": True})
    data = _data(client)
    assert data["projects"] == [] and data["completed"][0]["name"] == "Move flat"
    client.patch(f"/widgets/projects/projects/{p['id']}", json={"done": False, "deadline": None})
    reopened = _data(client)["projects"][0]
    assert reopened["done"] is False and reopened["done_at"] is None and reopened["deadline"] is None


def test_comments_can_be_added_edited_and_deleted(client):
    p = client.post("/widgets/projects/projects", json={"name": "Garden"}).json()
    t = client.post(f"/widgets/projects/projects/{p['id']}/tasks", json={"title": "Plant bulbs"}).json()
    c = client.post(f"/widgets/projects/tasks/{t['id']}/comments", json={"text": "Tulips + daffodils"}).json()
    edited = client.patch(f"/widgets/projects/comments/{c['id']}", json={"text": "Tulips only"}).json()
    assert edited["text"] == "Tulips only" and edited["edited_at"]
    assert client.patch(f"/widgets/projects/comments/{c['id']}", json={"text": "   "}).status_code == 422
    client.delete(f"/widgets/projects/comments/{c['id']}")
    assert _data(client)["projects"][0]["tasks"][0]["comments"] == []


def test_briefing_lists_overdue_and_upcoming_tasks():
    today = date(2026, 10, 20)
    data = {"today": today.isoformat(), "projects": [{
        "name": "Thesis", "deadline": "2026-12-15", "progress": {"done": 1, "total": 4},
        "tasks": [
            {"title": "Outline", "deadline": "2026-10-18", "done": False, "comments": [{"text": "x"}]},
            {"title": "Read papers", "deadline": "2026-10-21", "done": False, "comments": []},
            {"title": "Old", "deadline": "2026-10-01", "done": True, "comments": []},
            {"title": "Later", "deadline": (today + timedelta(days=30)).isoformat(), "done": False, "comments": []},
        ]}], "completed": []}
    text = projects.brief(data)
    assert "Thesis: 1/4 tasks done" in text
    assert "Outline (Thesis; OVERDUE since Sun 18 Oct; 1 comment)" in text
    assert "Read papers (Thesis; due tomorrow)" in text
    assert "Old" not in text and "Later" not in text


def test_claude_can_manage_projects_tasks_and_comments_and_undo(claude, db, user):
    p = tools.add_project("Website", deadline="2026-12-01")
    t = tools.add_task(p["id"], "Pick a theme", deadline="2026-11-01")
    c = tools.add_comment(t["id"], "Try the dark one")
    tools.update_comment(c["id"], "Try the light one")
    tools.update_task(t["id"], done=True)
    assert claude[-1][1] == 'Completed task "Pick a theme" (Website)'
    claude.undo_last(db, user)  # reopen
    task = tools.get_projects()["projects"][0]["tasks"][0]
    assert task["done"] is False and task["comments"][0]["text"] == "Try the light one"

    other = tools.add_project("Blog")
    tools.update_task(t["id"], project_id=other["id"])
    by_name = {p["name"]: p for p in tools.get_projects()["projects"]}
    assert by_name["Website"]["tasks"] == [] and by_name["Blog"]["tasks"][0]["title"] == "Pick a theme"
    claude.undo_last(db, user)  # moved back, both projects restored
    by_name = {p["name"]: p for p in tools.get_projects()["projects"]}
    assert len(by_name["Website"]["tasks"]) == 1 and by_name["Blog"]["tasks"] == []

    tools.delete_project(p["id"])
    assert [p["name"] for p in tools.get_projects()["projects"]] == ["Blog"]
    claude.undo_last(db, user)  # the project comes back with its task and comment
    restored = next(p for p in tools.get_projects()["projects"] if p["name"] == "Website")
    assert restored["tasks"][0]["comments"][0]["text"] == "Try the light one"

    tools.update_project(other["id"], done=True)
    completed = tools.get_projects()["completed"]
    assert [(c["id"], c["name"]) for c in completed] == [(other["id"], "Blog")] and "tasks" not in completed[0]
    assert tools.get_projects(include_completed=True)["completed"][0]["tasks"] == []
    tools.add_project("Temp")
    claude.undo_last(db, user)  # undoing an add deletes it
    assert "Temp" not in [p["name"] for p in tools.get_projects()["projects"]]
