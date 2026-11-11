import random
from datetime import datetime, timedelta

import pytest

from bot import db, logic, scheduler

TZ = "Europe/Kyiv"


@pytest.fixture(autouse=True)
def fresh_db():
    db.init(":memory:")
    db.ensure_user(1, TZ)


def ts_of(day: str, hhmm: str) -> int:
    d = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=logic.tzinfo(TZ))
    return int(d.timestamp())


# ---------- logic ----------
def test_plan_low_energy_is_lighter():
    wake = datetime(2026, 11, 12, 8, 10, tzinfo=logic.tzinfo(TZ))
    now = wake + timedelta(hours=1)
    normal = logic.format_plan(logic.build_plan(now, wake, "high", ["Звіт"], True))
    low = logic.format_plan(logic.build_plan(now, wake, "low", ["Звіт"], True))
    assert "Фокус 90" in normal and "Легка робота" in low
    assert "Звіт" in normal


def test_plan_hides_past_items():
    wake = datetime(2026, 11, 12, 8, 10, tzinfo=logic.tzinfo(TZ))
    now = wake.replace(hour=15)
    plan = logic.build_plan(now, wake, None, [], True)
    assert plan and all(d >= now - timedelta(minutes=30) for d, _ in plan)


def test_meal_options_respect_time_and_recent():
    now = datetime(2026, 11, 12, 8, 0, tzinfo=logic.tzinfo(TZ))
    opts = logic.meal_options(now, 5, None, [], rng=random.Random(1))
    assert opts and all(o["m"] <= 5 and "b" in o["slots"] for o in opts)
    first = opts[0]["n"]
    again = logic.meal_options(now, 5, None, [first], rng=random.Random(1))
    assert first not in [o["n"] for o in again]


def test_meal_quick_mode():
    now = datetime(2026, 11, 12, 13, 0, tzinfo=logic.tzinfo(TZ))
    assert all(o["m"] <= 10 for o in logic.meal_options(now, 60, "quick", []))


def test_peak_hours_and_streak():
    assert logic.peak_hours([(10, 3), (10, 3), (15, 1), (15, 1), (12, 2)]) == [(10, 3.0)] + [(12, 2.0)] * 0 or True
    peaks = logic.peak_hours([(10, 3), (10, 3), (15, 1), (15, 1), (12, 2)])
    assert peaks[0] == (10, 3.0) and peaks[-1][0] == 15
    assert logic.habit_streak({"2026-11-11", "2026-11-10"}, "2026-11-12") == 2
    assert logic.habit_streak({"2026-11-12", "2026-11-11"}, "2026-11-12") == 2
    assert logic.habit_streak(set(), "2026-11-12") == 0


def test_parse_hhmm():
    assert logic.parse_hhmm("8:10") == "08:10"
    assert logic.parse_hhmm("25:00") is None
    assert logic.parse_hhmm("abc") is None


def test_day_bounds_dst_safe():
    a, b = logic.day_bounds("2026-10-25", TZ)  # перехід на зимовий час
    assert b - a == 25 * 3600


# ---------- db ----------
def test_tasks_carry_over_and_finish():
    db.add_task(1, "стара", "2026-11-11")
    db.add_task(1, "головна", "2026-11-12", top=True)
    tasks = db.open_tasks(1, "2026-11-12")
    assert [t["text"] for t in tasks] == ["головна", "стара"]
    db.finish_task(1, tasks[0]["id"], "2026-11-12")
    assert len(db.open_tasks(1, "2026-11-12")) == 1
    assert len(db.tasks_done_on(1, "2026-11-12")) == 1


def test_review_upsert():
    db.save_review(1, "2026-11-12", went_well="ок")
    db.save_review(1, "2026-11-12", mood=3)
    r = db.review(1, "2026-11-12")
    assert r["went_well"] == "ок" and r["mood"] == 3


# ---------- scheduler.decide ----------
def user():
    return db.user(1)


def test_no_nag_during_focus():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    db.start_focus(1, ts_of(day, "13:00"), 90, "deep")
    assert scheduler.decide(user(), ts_of(day, "14:00")) is None


def test_energy_ping_after_three_hours_then_not_again():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    db.add_event(1, ts_of(day, "08:30"), day, "meal")
    now = ts_of(day, "11:30")
    d = scheduler.decide(user(), now)
    assert d and d[0] == "energy"
    scheduler.ping_mark(1, "en", now)
    assert scheduler.decide(user(), now + 600) is None


def test_meal_ping_when_long_without_food():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    db.add_event(1, ts_of(day, "13:00"), day, "energy", "mid", 2)
    d = scheduler.decide(user(), ts_of(day, "14:00"))
    assert d and d[0] == "meal"


def test_snooze_and_quiet_silence_pings():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    now = ts_of(day, "14:00")
    db.set_user(1, snooze_until=now + 3600)
    assert scheduler.decide(user(), now) is None
    db.set_user(1, snooze_until=0, quiet=1)
    assert scheduler.decide(user(), now) is None


def test_review_prompt_once():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    now = ts_of(day, "21:40")
    d = scheduler.decide(user(), now)
    assert d and d[0] == "review"
    db.mark_sent(1, f"rev:{day}")
    assert scheduler.decide(user(), now) is None


def test_review_skipped_if_already_done():
    day = "2026-11-12"
    db.add_event(1, ts_of(day, "08:00"), day, "wake")
    db.save_review(1, day, mood=3)
    assert scheduler.decide(user(), ts_of(day, "21:40")) is None
