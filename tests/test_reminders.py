import pytest

from bot import actions, db, scheduler
from .test_actions import _ts

DAY = "2026-11-12"


@pytest.fixture(autouse=True)
def _user(db_backend):
    db.ensure_user(1, "Europe/Kyiv")
    db.add_event(1, _ts(DAY, "08:00"), DAY, "wake")


def user():
    return db.user(1)


def test_reminder_fires_at_time_not_before(monkeypatch):
    monkeypatch.setattr("time.time", lambda: _ts(DAY, "10:00"))
    r = actions.execute(1, "add_plan_item", {"time": "10:30", "text": "Подзвонити лікарю"})
    assert r["ok"]
    assert scheduler.decide(user(), _ts(DAY, "10:29")) is None or scheduler.decide(user(), _ts(DAY, "10:29"))[0] != "plan_item"
    d = scheduler.decide(user(), _ts(DAY, "10:31"))
    assert d and d[0] == "plan_item" and d[1]["text"] == "Подзвонити лікарю"


def test_reminder_sent_only_once():
    iid = db.add_plan_item(1, DAY, "11:00", "x")
    assert scheduler.decide(user(), _ts(DAY, "11:01"))[0] == "plan_item"
    db.mark_sent(1, f"pi:{iid}")
    d = scheduler.decide(user(), _ts(DAY, "11:02"))
    assert not d or d[0] != "plan_item"


def test_stale_reminder_skipped_and_marked():
    iid = db.add_plan_item(1, DAY, "09:00", "стара")
    d = scheduler.decide(user(), _ts(DAY, "14:00"))
    assert not d or d[0] != "plan_item"
    assert db.was_sent(1, f"pi:{iid}")


def test_reminder_ignores_quiet_and_snooze():
    db.add_plan_item(1, DAY, "11:00", "важливе")
    now = _ts(DAY, "11:05")
    db.set_user(1, quiet=1, snooze_until=now + 3600)
    d = scheduler.decide(user(), now)
    assert d and d[0] == "plan_item"


def test_reminder_deferred_during_focus_then_fires():
    db.add_plan_item(1, DAY, "11:00", "після фокусу")
    fid = db.start_focus(1, _ts(DAY, "10:30"), 60, "deep")
    assert scheduler.decide(user(), _ts(DAY, "11:10")) is None
    db.set_focus(fid, status="finished")
    d = scheduler.decide(user(), _ts(DAY, "11:31"))
    assert d and d[0] == "plan_item"


def test_snooze_moves_time_and_rearms():
    iid = db.add_plan_item(1, DAY, "11:00", "x")
    db.mark_sent(1, f"pi:{iid}")
    db.set_plan_item_time(1, iid, "11:20")
    assert db.plan_item(1, iid)["hhmm"] == "11:20" and not db.was_sent(1, f"pi:{iid}")
    assert scheduler.decide(user(), _ts(DAY, "11:10")) is None or scheduler.decide(user(), _ts(DAY, "11:10"))[0] != "plan_item"
    assert scheduler.decide(user(), _ts(DAY, "11:21"))[0] == "plan_item"


def test_add_task_with_time_creates_reminder(monkeypatch):
    monkeypatch.setattr("time.time", lambda: _ts(DAY, "10:00"))
    r = actions.execute(1, "add_task", {"text": "Оплатити рахунок", "time": "15:00"})
    assert r["ok"] and "нагадаю о 15:00" in r["summary"]
    assert [i["text"] for i in db.plan_items(1, DAY)] == ["Оплатити рахунок"]
    assert db.open_tasks(1, DAY)[0]["text"] == "Оплатити рахунок"


def test_past_time_rejected_and_no_orphan_task(monkeypatch):
    monkeypatch.setattr("time.time", lambda: _ts(DAY, "10:00"))
    r = actions.execute(1, "add_task", {"text": "Минуле", "time": "09:00"})
    assert not r["ok"] and "минув" in r["error"]
    assert db.open_tasks(1, DAY) == [] and db.plan_items(1, DAY) == []
    assert not actions.execute(1, "add_plan_item", {"time": "09:00", "text": "x"})["ok"]


def test_add_task_without_time_has_no_reminder(monkeypatch):
    monkeypatch.setattr("time.time", lambda: _ts(DAY, "10:00"))
    assert actions.execute(1, "add_task", {"text": "Без часу"})["ok"]
    assert db.plan_items(1, DAY) == []
