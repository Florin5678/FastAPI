from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.widgets import budget, gym, notes, weight

CPH = ZoneInfo("Europe/Copenhagen")


def test_local_widgets_load(client):
    for widget in ("nutrition", "notes", "gym", "weight", "budget"):
        r = client.get(f"/widgets/{widget}/data", params={"tz": "Europe/Copenhagen"})
        assert r.status_code == 200 and r.json()["status"] == "ok", (widget, r.text)


# ---- Reminders ----

def test_monthly_reminder_keeps_its_day_and_is_clamped_in_short_months(db, user):
    with patch.object(notes, "_now", return_value=datetime(2026, 1, 30, 12, tzinfo=timezone.utc)):
        r = notes.add_reminder(notes.ReminderIn(text="Rent", due=datetime(2026, 1, 31, 9, tzinfo=CPH), repeat="monthly",
                                                tz="Europe/Copenhagen"), user=user, db=db)
    dues = []
    for _ in range(3):
        with patch.object(notes, "_now", return_value=datetime.fromisoformat(r["due"])):
            r = notes.update_reminder(r["id"], notes.ReminderPatch(done=True, tz="Europe/Copenhagen"), user=user, db=db)
        dues.append(datetime.fromisoformat(r["due"]).astimezone(CPH).strftime("%d %b %H:%M"))
    assert dues == ["28 Feb 09:00", "31 Mar 09:00", "30 Apr 09:00"]
    assert r["done"] is False


def test_repeating_reminder_needs_a_due_time(db, user):
    with pytest.raises(HTTPException) as e:
        notes.add_reminder(notes.ReminderIn(text="x", repeat="daily"), user=user, db=db)
    assert e.value.status_code == 422


def test_reminder_can_be_edited(client):
    r = client.post("/widgets/notes/reminders", json={"text": "Laundry"}).json()
    due = datetime(2030, 5, 1, 18, tzinfo=CPH).isoformat()
    edited = client.patch(f"/widgets/notes/reminders/{r['id']}", json={"text": "Laundry + dishes", "due": due, "repeat": "weekly"}).json()
    assert edited["text"] == "Laundry + dishes" and edited["repeat"] == "weekly"


# ---- Budget ----

def test_expense_sub_categories_are_fixed(db, user):
    assert budget._check_categories(["expenses", "restaurant/café", "Wolt"]) == ["Expenses", "Restaurant/Café", "Wolt"]
    assert budget._check_categories(["Income", "Anything", "Free text"]) == ["Income", "Anything", "Free text"]
    for bad in (["Expenses", "Coffee"], ["Expenses"], ["Savings", "X"]):
        with pytest.raises(HTTPException):
            budget._check_categories(bad)


def test_csv_import_skips_unknown_sub_categories(client):
    csv = "Month,Category,Sub-category,Amount\n2026-10,Expenses,Groceries,10\n2026-10,Expenses,Coffee,5\n2026-10,Income,SU,100\n"
    r = client.post("/widgets/budget/import", json={"csv": csv}).json()
    assert r["imported"] == 2 and r["skipped"] == 1


# ---- Gym ----

def test_active_days_count_days_not_workouts(client):
    today = date.today().isoformat()
    for kind in ("Abs", "Legs"):
        assert client.post("/widgets/gym/workouts", json={"day": today, "kind": kind, "minutes": 30}).status_code == 200
    data = client.get("/widgets/gym/data", params={"tz": "Europe/Copenhagen"}).json()["data"]
    assert data["active_days"] == 1 and data["workouts_done"] == 2
    assert "weeks" not in data  # the tile's weekly chart was removed


def test_workout_can_be_edited(client):
    w = client.post("/widgets/gym/workouts", json={"day": date.today().isoformat(), "kind": "Abs", "minutes": 30}).json()
    edited = client.patch(f"/widgets/gym/workouts/{w['id']}", json={"kind": "Legs", "minutes": 45, "note": "heavy"}).json()
    assert (edited["kind"], edited["minutes"], edited["note"]) == ("Legs", 45, "heavy")


def test_any_workout_type_and_list_types_keep_their_spelling(client):
    today = date.today().isoformat()
    other = client.post("/widgets/gym/workouts", json={"day": today, "kind": "  Calisthenics ", "minutes": 40}).json()
    listed = client.post("/widgets/gym/workouts", json={"day": today, "kind": "shoulders", "minutes": 40}).json()
    assert other["kind"] == "Calisthenics" and listed["kind"] == "Shoulders"
    assert client.post("/widgets/gym/workouts", json={"day": today, "kind": "   ", "minutes": 40}).status_code == 422


def test_each_type_keeps_one_colour_in_every_month_and_chart(client):
    routines = gym.DEFAULT_TYPES
    assert routines[-1] == "Shoulders"
    for day, kind in [("2026-08-03", "Calisthenics"), ("2026-09-07", "Yoga"), ("2026-10-05", "Abs")]:
        client.post("/widgets/gym/workouts", json={"day": day, "kind": kind, "minutes": 30})
    months = [client.get("/widgets/gym/month", params={"month": m}).json()["colors"] for m in ("2026-08", "2026-09", "2026-10")]
    stats = client.get("/widgets/gym/stats", params={"level": "year", "anchor": "2026-10-05"}).json()["colors"]
    assert months[0] == months[1] == months[2] == stats
    colours = months[0]
    assert [colours[k] for k in routines] == list(range(1, len(routines) + 1))  # the list in order
    assert colours["Calisthenics"] == len(routines) + 1 and colours["Yoga"] == len(routines) + 2  # then added via "Other"
    assert len(set(colours.values())) == min(len(colours), gym.COLOR_SLOTS)


def test_other_types_join_the_list_and_only_the_first_nine_are_buttons(client):
    today = date.today().isoformat()
    for kind in ("Calisthenics", "calisthenics", "Yoga"):
        client.post("/widgets/gym/workouts", json={"day": today, "kind": kind, "minutes": 30})
    data = client.get("/widgets/gym/data", params={"tz": "Europe/Copenhagen"}).json()["data"]
    assert data["kinds"] == gym.DEFAULT_TYPES[:gym.SHOWN_TYPES]
    assert data["other_kinds"] == gym.DEFAULT_TYPES[gym.SHOWN_TYPES:] + ["Calisthenics", "Yoga"]


def test_editing_the_list_changes_buttons_and_colours(client):
    client.post("/widgets/gym/workouts", json={"day": "2026-10-05", "kind": "Abs", "minutes": 30})
    saved = client.put("/widgets/gym/types", json={"types": ["Yoga", " abs ", "Abs", "Legs", ""]}).json()["types"]
    assert saved == ["Yoga", "abs", "Legs"]  # trimmed, duplicates (any case) and blanks dropped
    month = client.get("/widgets/gym/month", params={"month": "2026-10"}).json()
    assert month["kinds"] == saved and month["colors"]["Yoga"] == 1 and month["colors"]["Legs"] == 3
    assert client.put("/widgets/gym/types", json={"types": [" "]}).status_code == 422


# ---- Weight ----

def test_weight_change_is_measured_from_a_real_earlier_entry(db, user):
    for d, kg in [("2026-08-20", 64.8), ("2026-09-02", 65.4), ("2026-09-26", 65.9), ("2026-10-01", 66.3)]:
        weight.log_weight(db, user, date.fromisoformat(d), kg)
    weight.log_weight(db, user, date(2026, 10, 1), 66.4)  # replaces that day's value
    s = weight.summary(weight._entries(weight.widget_row(db, user, "weight")), date(2026, 10, 3), 70)
    assert s["latest"] == {"day": "2026-10-01", "kg": 66.4}
    assert s["change_week"] == {"kg": 1.0, "since": "2026-09-02"}
    assert s["change_month"] == {"kg": 1.6, "since": "2026-08-20"}
    assert s["to_goal"] == 3.6
