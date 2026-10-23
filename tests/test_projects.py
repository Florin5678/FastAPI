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
    assert '  - Outline (OVERDUE since Sun 18 Oct; 1 comment, latest: "x")' in text  # every open task, in order
    assert "  - Later (due " in text and "Old" not in text  # completed tasks are left out
    assert "Overdue or due in the next 7 days: Outline (Thesis, OVERDUE since Sun 18 Oct); Read papers (Thesis, due tomorrow)" in text
    assert "(+1 more open tasks)" in projects.brief(data, limit=2)


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


def test_tasks_and_projects_keep_a_manual_order_and_can_be_sorted_by_date(client):
    p = client.post("/widgets/projects/projects", json={"name": "Trip"}).json()
    ids = {}
    for title, deadline in [("Book flights", "2026-11-01"), ("Pack", "2026-12-01"), ("Visa", "2026-10-25")]:
        ids[title] = client.post(f"/widgets/projects/projects/{p['id']}/tasks", json={"title": title, "deadline": deadline}).json()["id"]
    titles = lambda: [t["title"] for t in _data(client)["projects"][0]["tasks"]]  # noqa: E731
    assert titles() == ["Visa", "Book flights", "Pack"]  # placed by date
    client.put(f"/widgets/projects/projects/{p['id']}/tasks/order", json={"ids": [ids["Pack"], ids["Visa"]]})
    assert titles() == ["Pack", "Visa", "Book flights"]  # listed first, the rest after
    client.post(f"/widgets/projects/projects/{p['id']}/tasks", json={"title": "Insurance", "deadline": "2026-10-30"})
    assert titles() == ["Insurance", "Pack", "Visa", "Book flights"]  # slotted before the first one due later
    client.patch(f"/widgets/projects/tasks/{ids['Pack']}", json={"title": "Pack bags"})
    assert titles()[1] == "Pack bags"  # other edits don't move it
    client.put(f"/widgets/projects/projects/{p['id']}/tasks/order", json={"by_date": True})
    assert titles() == ["Visa", "Insurance", "Book flights", "Pack bags"]
    assert client.put(f"/widgets/projects/projects/{p['id']}/tasks/order", json={"ids": ["nope"]}).status_code == 404

    q = client.post("/widgets/projects/projects", json={"name": "Taxes", "deadline": "2026-10-28"}).json()
    names = lambda: [x["name"] for x in _data(client)["projects"]]  # noqa: E731
    assert names() == ["Taxes", "Trip"]  # a dated project goes before ones without a deadline
    client.put("/widgets/projects/projects/order", json={"ids": [p["id"], q["id"]]})
    assert names() == ["Trip", "Taxes"]


def test_claude_can_reorder_and_undo_restores_the_order(claude, db, user):
    a = tools.add_project("A")
    b = tools.add_project("B")
    tools.reorder_projects([b["id"], a["id"]])
    assert [p["name"] for p in tools.get_projects()["projects"]] == ["B", "A"]
    claude.undo_last(db, user)
    assert [p["name"] for p in tools.get_projects()["projects"]] == ["A", "B"]
    t1, t2 = tools.add_task(a["id"], "one"), tools.add_task(a["id"], "two")
    tools.reorder_tasks(a["id"], [t2["id"], t1["id"]])
    assert [t["title"] for t in tools.get_projects()["projects"][0]["tasks"]] == ["two", "one"]
    tools.delete_project(a["id"])
    claude.undo_last(db, user)  # back in its old place, tasks in the user's order
    first = tools.get_projects()["projects"][0]
    assert first["name"] == "A" and [t["title"] for t in first["tasks"]] == ["two", "one"]


def test_projects_have_an_optional_colour(client, claude):
    p = client.post("/widgets/projects/projects", json={"name": "Garden", "color": "green"}).json()
    assert p["color"] == "green"
    assert client.patch(f"/widgets/projects/projects/{p['id']}", json={"color": "magenta"}).status_code == 422
    assert client.patch(f"/widgets/projects/projects/{p['id']}", json={"color": None}).json()["color"] is None
    assert tools.update_project(p["id"], color="purple")["color"] == "purple"
    assert tools.update_project(p["id"], color="none")["color"] is None
    assert tools.add_project("Blog", color="blue")["color"] == "blue"
