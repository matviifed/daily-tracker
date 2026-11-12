import asyncio

import pytest

from bot import actions, db, handlers, llm, logic


def _ts(day, hhmm):
    from datetime import datetime
    d = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=logic.tzinfo("Europe/Kyiv"))
    return int(d.timestamp())


def ex(tool, **args):
    return actions.execute(1, tool, args)


def test_task_lifecycle():
    r = ex("add_task", text="Купити хліб", top=True)
    assert r["ok"] and "Купити хліб" in r["summary"]
    tid = r["task_id"]
    assert db.open_tasks(1, logic.day_of(__import__("time").time(), "Europe/Kyiv"))[0]["top"] == 1
    assert ex("complete_task", task_id=tid)["ok"]
    r2 = ex("delete_task", task_id=tid)
    assert r2["ok"]
    assert not ex("complete_task", task_id=tid)["ok"]


def test_cannot_touch_other_users_task():
    db.ensure_user(2, "Europe/Kyiv")
    tid = db.add_task(2, "чужа", "2026-11-12")
    assert not actions.execute(1, "complete_task", {"task_id": tid})["ok"]
    assert not actions.execute(1, "delete_task", {"task_id": tid})["ok"]
    assert db.task(2, tid) is not None


def test_habits_and_validation():
    assert ex("log_water", glasses=2)["total_today"] == 2
    assert ex("log_water")["total_today"] == 3
    assert not ex("log_water", glasses=99)["ok"]
    assert ex("log_move", minutes=30)["ok"] and ex("log_read", minutes=20)["ok"]
    assert not ex("log_move", minutes=1)["ok"]
    assert not ex("log_move", minutes="багато")["ok"]


def test_energy_and_meal():
    assert ex("log_energy", level="low")["ok"]
    assert not ex("log_energy", level="turbo")["ok"]
    assert ex("log_meal", name="борщ")["ok"] and ex("log_meal")["ok"]


def test_plan_items_show_up_in_plan_and_context(monkeypatch):
    monkeypatch.setattr("time.time", lambda: _ts("2026-11-12", "10:00"))
    c = handlers.Ctx(1)
    db.add_event(1, c.ts - 2 * 3600, c.day, "wake")
    r = ex("add_plan_item", time="17:00", text="Прогулянка <з> собакою")
    assert r["ok"]
    assert not ex("add_plan_item", time="25:00", text="x")["ok"]
    assert "#%d" % r["item_id"] in handlers.day_context(handlers.Ctx(1))
    plan = handlers.plan_text(handlers.Ctx(1))
    assert "📌 Прогулянка &lt;з&gt; собакою" in plan
    assert ex("remove_plan_item", item_id=r["item_id"])["ok"]
    assert "📌" not in handlers.plan_text(handlers.Ctx(1))


def test_wake_time_rules():
    assert not ex("set_wake_time", time="23:59")["ok"] or handlers.Ctx(1).now.hour == 23
    assert not ex("set_wake_time", time="abc")["ok"]
    assert ex("set_wake_time", time="00:00")["ok"]


def test_focus_start_stop():
    r = ex("start_focus", minutes=45)
    assert r["ok"] and db.running_focus(1)
    assert not ex("start_focus", minutes=45)["ok"]
    assert ex("stop_focus")["ok"] and db.running_focus(1) is None
    assert not ex("stop_focus")["ok"]


def test_settings_tools():
    assert ex("set_review_time", time="22:15")["ok"] and db.user(1)["review_time"] == "22:15"
    assert not ex("set_review_time", time="99:99")["ok"]
    assert ex("set_quiet", on=True)["ok"] and db.user(1)["quiet"] == 1


def test_unknown_tool():
    assert not ex("drop_database")["ok"]


# ---------- цикл function calling ----------
def _scripted(monkeypatch, responses):
    sent = []

    async def fake_post(payload):
        sent.append(__import__("copy").deepcopy(payload))
        return responses.pop(0)

    monkeypatch.setattr(llm, "_post", fake_post)
    return sent


def test_llm_loop_executes_tool_and_returns_text(monkeypatch):
    sig_part = {"functionCall": {"name": "add_task", "args": {"text": "Позвонити мамі"}}, "thoughtSignature": "SIG"}
    sent = _scripted(monkeypatch, [
        {"candidates": [{"content": {"role": "model", "parts": [sig_part]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Додав."}]}}]},
    ])
    text, done = asyncio.run(llm.ask([], "додай задачу подзвонити мамі", "ctx",
                                     executor=lambda n, a: actions.execute(1, n, a)))
    assert text == "Додав." and done == ["Додано задачу: Позвонити мамі"]
    second = sent[1]["contents"]
    assert second[-2] == {"role": "model", "parts": [sig_part]}  # thoughtSignature збережено
    fr = second[-1]["parts"][0]["functionResponse"]
    assert fr["name"] == "add_task" and fr["response"]["ok"] is True and "summary" not in fr["response"]
    assert "tools" in sent[0]


def test_llm_without_executor_has_no_tools(monkeypatch):
    sent = _scripted(monkeypatch, [{"candidates": [{"content": {"parts": [{"text": "Привіт"}]}}]}])
    text, done = asyncio.run(llm.ask([], "привіт", "ctx"))
    assert text == "Привіт" and done == [] and "tools" not in sent[0]


def test_llm_call_limit(monkeypatch):
    call = {"functionCall": {"name": "log_water", "args": {}}}
    loop = {"candidates": [{"content": {"parts": [call]}}]}
    _scripted(monkeypatch, [loop] * 10)
    text, done = asyncio.run(llm.ask([], "вода", "ctx", executor=lambda n, a: actions.execute(1, n, a)))
    assert len(done) <= llm.MAX_CALLS and done  # не нескінченний цикл
    assert text


def test_llm_empty_final_text_after_actions(monkeypatch):
    _scripted(monkeypatch, [
        {"candidates": [{"content": {"parts": [{"functionCall": {"name": "log_water", "args": {}}}]}}]},
        {"candidates": [{"content": {"parts": []}}]},
    ])
    text, done = asyncio.run(llm.ask([], "вода", "ctx", executor=lambda n, a: actions.execute(1, n, a)))
    assert text == "Готово." and done == ["Вода: +1"]


@pytest.fixture(autouse=True)
def _user(db_backend):
    db.ensure_user(1, "Europe/Kyiv")
