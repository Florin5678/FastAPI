from datetime import date, timedelta

from app.connector import tools
from app.models import NutritionEntry
from app.widgets import nutrition


def _entry(client, day, name, **values):
    nutrients = {k: 0 for k in ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sat_fat", "salt")}
    nutrients.update(values)
    r = client.post("/widgets/nutrition/entries", json={"day": day, "name": name, "grams": 100, "nutrients": nutrients})
    assert r.status_code == 200, r.text
    return r.json()


def test_salt_is_tracked_like_the_other_nutrients(client):
    today = date.today().isoformat()
    _entry(client, today, "Pizza", calories=900, salt=4.7)
    day = client.get(f"/widgets/nutrition/days/{today}").json()
    salt = next(n for n in day["nutrients"] if n["key"] == "salt")
    assert salt == {"key": "salt", "label": "Salt", "unit": "g", "kind": "limit", "goal": 6, "actual": 4.7}


def test_usda_sodium_becomes_salt():
    values = nutrition._per_100g({"foodNutrients": [{"nutrientNumber": "307", "value": 400}]})
    assert values["salt"] == 1.0
    assert nutrition._off_value({"sodium_100g": 0.4}, "salt") == 1.0


def test_brief_lists_every_nutrient_and_food_for_today_and_yesterday(db, user, client):
    today = date.today()
    for d, name in [(today, "Skyr"), (today - timedelta(days=1), "Lentil curry"), (today - timedelta(days=1), "Banana")]:
        db.add(NutritionEntry(user_id=user.id, day=d, name=name, grams=100, source="manual", calories=100, protein=10,
                              carbs=1, fat=1, fiber=1, sugar=1, sat_fat=1, salt=0.5))
    db.commit()
    text = nutrition.brief(client.get("/widgets/nutrition/data", params={"tz": "Europe/Copenhagen"}).json()["data"], 2)
    assert "Today" in text and "Yesterday" in text
    for label in ("Calories", "Protein", "Carbs", "Fat", "Fiber", "Sugar", "Sat. fat", "Salt"):
        assert text.count(f"- {label}:") == 2
    assert "Skyr" in text and "Lentil curry" in text and "Banana" in text  # all foods, even beyond the old limit


def test_history_tool_returns_the_14_days_before_today(db, user, claude):
    today = tools._today()
    for days_ago in (0, 1, 14, 15):
        db.add(NutritionEntry(user_id=user.id, day=today - timedelta(days=days_ago), name=f"food-{days_ago}", grams=100,
                              source="manual", calories=100, protein=10))
    db.commit()
    history = tools.get_nutrition_history()
    assert len(history["days"]) == 14
    assert history["days"][0]["day"] == (today - timedelta(days=1)).isoformat()
    foods = [f["name"] for d in history["days"] for f in d["foods"]]
    assert foods == ["food-1", "food-14"]
    assert tools.get_nutrition()["entries"][0]["name"] == "food-0"


def test_pantry_receipt_takes_items_off_the_shopping_list_and_undo_restores(db, user, claude):
    tools.add_shopping_items([nutrition.ShoppingItemIn(name="Eggs"), nutrition.ShoppingItemIn(name="Milk")])
    result = tools.add_pantry_items([nutrition.PantryItemIn(name="eggs", amount="10")])
    assert result["removed_from_shopping_list"] == ["Eggs"]
    assert result["shopping_list_now"] == ["Milk"]
    claude.undo_last(db, user)
    lists = tools.get_pantry()
    assert lists["items"] == [] and [i["name"] for i in lists["shopping"]] == ["Eggs", "Milk"]


def test_pantry_priority_and_moving_between_lists(db, user, claude):
    tools.add_pantry_items([nutrition.PantryItemIn(name="Rice"), nutrition.PantryItemIn(name="Beans")])
    ids = {i["name"]: i["id"] for i in tools.get_pantry()["items"]}
    tools.set_pantry_priority([ids["Beans"]], True)
    assert [i["name"] for i in tools.get_pantry()["items"] if i["priority"]] == ["Beans"]
    tools.move_to_shopping_list([ids["Rice"]])
    lists = tools.get_pantry()
    assert [i["name"] for i in lists["items"]] == ["Beans"] and [i["name"] for i in lists["shopping"]] == ["Rice"]
    claude.undo_last(db, user)
    assert {i["name"] for i in tools.get_pantry()["items"]} == {"Beans", "Rice"}


def test_my_foods_add_update_delete_and_ui_patch(db, user, client, claude):
    food = tools.add_saved_food("Rugbrød", calories=200, protein=6, salt=1.1, grams=77)
    assert tools.log_saved_food("rugbrød")["nutrients"]["salt"] == 0.8  # 1.1 g per 100 g x 77 g
    tools.update_saved_food("Rugbrød", salt=1.3)
    claude.undo_last(db, user)
    assert nutrition._saved_foods(nutrition.widget_row(db, user, "nutrition"))[0]["per_100g"]["salt"] == 1.1
    r = client.patch(f"/widgets/nutrition/saved-foods/{food['id']}", json={"name": "Kohberg rugbrød", "grams": 41})
    assert r.status_code == 200 and r.json()["name"] == "Kohberg rugbrød" and r.json()["grams"] == 41
    tools.delete_saved_food("kohberg")
    assert client.get("/widgets/nutrition/saved-foods").json()["foods"] == []


def test_starred_pantry_items_are_pinned_at_the_top(client):
    ids = {name: client.post("/widgets/nutrition/pantry", json={"name": name}).json()["id"] for name in ("Apples", "Rice", "Beans")}
    client.patch(f"/widgets/nutrition/pantry/{ids['Rice']}", json={"priority": True})
    assert [i["name"] for i in client.get("/widgets/nutrition/pantry").json()["items"]] == ["Rice", "Apples", "Beans"]


def test_nutrition_tile_counts_the_shopping_list(client):
    for name in ("Milk", "Eggs"):
        client.post("/widgets/nutrition/shopping", json={"name": name})
    data = client.get("/widgets/nutrition/data", params={"tz": "Europe/Copenhagen"}).json()["data"]
    assert data["shopping_count"] == 2
