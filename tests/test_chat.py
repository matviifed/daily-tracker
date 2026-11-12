import asyncio
import json

import pytest

from bot import config, db, handlers, llm




def test_payload_shape_and_history_trim():
    history = [{"role": "user" if i % 2 == 0 else "model", "text": f"m{i}"} for i in range(30)]
    p = llm.build_payload(history, "привіт", "Локальний час: 10:00")
    assert len(p["contents"]) == 11  # 10 з історії + нове повідомлення
    assert p["contents"][-1] == {"role": "user", "parts": [{"text": "привіт"}]}
    assert "Локальний час" in p["system_instruction"]["parts"][0]["text"]


def test_parse_response():
    data = {"candidates": [{"content": {"parts": [{"text": "Ось "}, {"text": "відповідь"}]}}]}
    assert llm.parse_response(data) == "Ось відповідь"
    with pytest.raises(llm.LLMError):
        llm.parse_response({"candidates": []})
    with pytest.raises(llm.LLMError):
        llm.parse_response({"promptFeedback": {"blockReason": "SAFETY"}})


def test_ask_without_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(llm.LLMError):
        asyncio.run(llm.ask([], "hi", "", executor=lambda n, a: {}))


def test_chat_state_roundtrip():
    assert db.chat_get(1)["active"] == 0
    db.chat_set(1, active=1, history=json.dumps([{"role": "user", "text": "x"}]), day="2026-11-12", used=3)
    row = db.chat_get(1)
    assert row["active"] == 1 and row["used"] == 3 and json.loads(row["history"])[0]["text"] == "x"


def test_day_context_mentions_tasks_and_habits():
    c = handlers.Ctx(1)
    db.add_task(1, "Написати звіт", c.day, top=True)
    db.add_event(1, c.ts, c.day, "water", None, 1)
    text = handlers.day_context(c)
    assert "Написати звіт" in text and "[головна]" in text
    assert "вода 1/" in text
