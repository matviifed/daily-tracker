import asyncio
import json

import pytest
from aiogram.fsm.storage.base import StorageKey
from fastapi.testclient import TestClient

from bot import app as bot_app
from bot import config, db
from bot.storage import DbStorage


def test_turso_roundtrip_types_and_rowid():
    rid = db.add_event(1, 1700000000, "2026-11-12", "energy", "high", 3.0)
    assert isinstance(rid, int) and rid > 0
    row = db.one("SELECT * FROM events WHERE id=?", (rid,))
    assert row["ts"] == 1700000000 and row["value"] == "high" and row["num"] == 3.0
    assert db.one("SELECT * FROM events WHERE id=?", (rid + 100,)) is None


def test_turso_null_and_unicode():
    db.add_task(1, "Купити хліб 🍞", "2026-11-12")
    t = db.open_tasks(1, "2026-11-12")[0]
    assert t["text"] == "Купити хліб 🍞" and t["done_day"] is None


def test_turso_sql_error_raises():
    with pytest.raises(Exception):
        db.q("SELECT * FROM no_such_table")


def test_fsm_storage_persists():
    st = DbStorage()
    key = StorageKey(bot_id=1, chat_id=5, user_id=5)

    async def go():
        assert await st.get_state(key) is None
        await st.set_state(key, "Review:well")
        await st.set_data(key, {"a": "б"})
        assert await st.get_state(key) == "Review:well"
        assert await st.get_data(key) == {"a": "б"}
        await st.set_state(key, None)
        assert await st.get_state(key) is None
        assert await st.get_data(key) == {"a": "б"}

    asyncio.run(go())


def _client(monkeypatch):
    sec = "wh-secret"
    monkeypatch.setattr(config, "WEBHOOK_SECRET", sec)
    monkeypatch.setattr(config, "CRON_SECRET", "cron-secret")
    from api.index import app
    return TestClient(app), sec


def test_health(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.get("/api/health").json() == {"ok": True}


def test_webhook_rejects_bad_secret(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.post("/api/webhook", json={}).status_code == 403
    assert c.post("/api/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}).status_code == 403


def test_webhook_accepts_good_secret(monkeypatch):
    c, sec = _client(monkeypatch)
    seen = []

    async def fake(data):
        seen.append(data)

    monkeypatch.setattr(bot_app, "process_update", fake)
    r = c.post("/api/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": sec})
    assert r.status_code == 200 and seen == [{"update_id": 1}]


def test_webhook_closed_without_configured_secret(monkeypatch):
    c, _ = _client(monkeypatch)
    monkeypatch.setattr(config, "WEBHOOK_SECRET", "")
    assert c.post("/api/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": ""}).status_code == 403


def test_tick_auth(monkeypatch):
    c, _ = _client(monkeypatch)
    calls = []

    async def fake():
        calls.append(1)

    monkeypatch.setattr(bot_app, "run_tick", fake)
    assert c.get("/api/tick").status_code == 403
    assert c.get("/api/tick?key=wrong").status_code == 403
    assert c.get("/api/tick?key=cron-secret").status_code == 200
    assert c.post("/api/tick", headers={"Authorization": "Bearer cron-secret"}).status_code == 200
    assert len(calls) == 2
