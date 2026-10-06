import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.models import Integration
from app.widgets import assistant, assistant_chat

CPH = ZoneInfo("Europe/Copenhagen")


def test_prompt_order_and_editable_rules():
    s = assistant.AssistantSettings(instructions="Hi {when}", extras=[assistant.ExtraInstruction(name="Email", text="Check mail.")],
                                    rules="Rules:\n- Be brief.", claude_prompt="Plan my day.")
    prompt = assistant.compose_prompt(s, [{"name": "Today", "text": "x"}])
    order = [prompt.index(part) for part in ("Hi {when}", "# My dashboard briefing", "## Today", "# How to answer",
                                             "1. Email: Check mail.", "Rules:\n- Be brief.", "# My question", "Plan my day.")]
    assert order == sorted(order)


def test_empty_rules_and_claude_prompt_fall_back_to_the_defaults():
    s = assistant.AssistantSettings(instructions="x", rules="", claude_prompt="")
    prompt = assistant.compose_prompt(s, [])
    assert assistant.DEFAULT_RULES in prompt and assistant.DEFAULT_CLAUDE_PROMPT in prompt


def test_old_saved_settings_still_load():
    old = {"instructions": "x", "default_question": "Brief me.", "context": "cabin trip",
           "extras": [{"name": "DO NOT MENTION", "text": "x", "enabled": True, "rule": True}]}
    s = assistant.AssistantSettings.model_validate(old)
    assert s.extras[0].name == "DO NOT MENTION" and s.claude_prompt == assistant.DEFAULT_CLAUDE_PROMPT


def test_morning_brief_is_written_once_a_day_after_its_time(db, user):
    row = db.query(Integration).filter_by(user_id=user.id, app_name="assistant").first()
    row.config = {"assistant": {"instructions": "x", "morning_brief": True, "morning_brief_time": "07:00"}}
    db.commit()
    calls = []

    async def fake_converse(db_, user_, messages):
        calls.append(messages)
        return {"reply": "Your brief", "actions": [], "started": datetime.utcnow(), "model": "m", "budget": 5}

    class Clock(datetime):
        moment = None

        @classmethod
        def now(cls, tz=None):
            return cls.moment.astimezone(tz) if tz else cls.moment

    with patch.object(assistant_chat, "converse", fake_converse), patch.object(assistant_chat, "get_client", return_value=object()), \
            patch.object(assistant_chat, "datetime", Clock):
        for hh, mm, expected in [(6, 50, 0), (7, 5, 1), (7, 15, 1)]:
            Clock.moment = datetime(2026, 10, 3, hh, mm, tzinfo=CPH)
            asyncio.run(assistant_chat.maybe_morning_brief(user.id))
            assert len(calls) == expected, (hh, mm)
        Clock.moment = datetime(2026, 10, 4, 7, 1, tzinfo=CPH)
        asyncio.run(assistant_chat.maybe_morning_brief(user.id))
        assert len(calls) == 2
