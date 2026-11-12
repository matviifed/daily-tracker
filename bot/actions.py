"""Інструменти, якими Gemini може змінювати розпорядок дня. Усі аргументи від моделі валідуються тут.

execute(uid, name, args) -> {"ok": bool, "summary": "<для користувача>", ...поля для моделі}
"""
from __future__ import annotations

import logging
import time

from . import config, db, logic

log = logging.getLogger("actions")

MAX_PLAN_ITEMS_PER_DAY = 30

_STR = "string"
_INT = "integer"

TOOLS = [{"functionDeclarations": [
    {"name": "add_task", "description": "Додати задачу в список користувача.",
     "parameters": {"type": "object", "properties": {
         "text": {"type": _STR, "description": "Текст задачі"},
         "top": {"type": "boolean", "description": "true, якщо це головна задача дня"}},
         "required": ["text"]}},
    {"name": "complete_task", "description": "Відмітити задачу виконаною за її id з контексту.",
     "parameters": {"type": "object", "properties": {"task_id": {"type": _INT}}, "required": ["task_id"]}},
    {"name": "delete_task", "description": "Видалити задачу за її id з контексту.",
     "parameters": {"type": "object", "properties": {"task_id": {"type": _INT}}, "required": ["task_id"]}},
    {"name": "log_water", "description": "Записати випиті склянки води.",
     "parameters": {"type": "object", "properties": {"glasses": {"type": _INT, "description": "1–10, за замовчуванням 1"}}}},
    {"name": "log_move", "description": "Записати рух/прогулянку/спорт у хвилинах.",
     "parameters": {"type": "object", "properties": {"minutes": {"type": _INT, "description": "5–240"}}, "required": ["minutes"]}},
    {"name": "log_read", "description": "Записати читання у хвилинах.",
     "parameters": {"type": "object", "properties": {"minutes": {"type": _INT, "description": "5–240"}}, "required": ["minutes"]}},
    {"name": "log_energy", "description": "Записати поточний рівень енергії.",
     "parameters": {"type": "object", "properties": {
         "level": {"type": _STR, "enum": ["high", "mid", "low"], "description": "high=висока, mid=середня, low=низька"}},
         "required": ["level"]}},
    {"name": "log_meal", "description": "Записати прийом їжі зараз.",
     "parameters": {"type": "object", "properties": {"name": {"type": _STR, "description": "Що з'їв (необов'язково)"}}}},
    {"name": "set_wake_time", "description": "Виправити сьогоднішній час пробудження (не пізніше за поточний час).",
     "parameters": {"type": "object", "properties": {"time": {"type": _STR, "description": "HH:MM"}}, "required": ["time"]}},
    {"name": "add_plan_item", "description": "Додати власний пункт у розпорядок СЬОГОДНІ на вказаний час.",
     "parameters": {"type": "object", "properties": {
         "time": {"type": _STR, "description": "HH:MM"}, "text": {"type": _STR, "description": "Що робити"}},
         "required": ["time", "text"]}},
    {"name": "remove_plan_item", "description": "Видалити власний пункт розпорядку за його id з контексту.",
     "parameters": {"type": "object", "properties": {"item_id": {"type": _INT}}, "required": ["item_id"]}},
    {"name": "start_focus", "description": "Запустити фокус-сесію з таймером.",
     "parameters": {"type": "object", "properties": {
         "minutes": {"type": _INT, "description": "5–180"},
         "mode": {"type": _STR, "enum": ["deep", "light", "creative"]}}, "required": ["minutes"]}},
    {"name": "stop_focus", "description": "Зупинити поточну фокус-сесію.", "parameters": {"type": "object", "properties": {}}},
    {"name": "set_review_time", "description": "Змінити час вечірнього огляду.",
     "parameters": {"type": "object", "properties": {"time": {"type": _STR, "description": "HH:MM"}}, "required": ["time"]}},
    {"name": "set_quiet", "description": "Увімкнути або вимкнути тихий режим (без нагадувань про енергію й їжу).",
     "parameters": {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]}},
]}]


def _ctx(uid: int):
    db.ensure_user(uid, config.DEFAULT_TZ)
    u = db.user(uid)
    ts = int(time.time())
    now = logic.local(ts, u["tz"])
    return u, ts, now, now.strftime("%Y-%m-%d")


def _int(a: dict, key: str, lo: int, hi: int, default: int | None = None) -> int:
    v = a.get(key, default)
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"Параметр {key} має бути числом")
    if not lo <= v <= hi:
        raise ValueError(f"Параметр {key} має бути від {lo} до {hi}")
    return v


def _text(a: dict, key: str, maxlen: int, required: bool = True) -> str | None:
    v = a.get(key)
    v = str(v).strip() if v is not None else ""
    if not v:
        if required:
            raise ValueError(f"Параметр {key} порожній")
        return None
    return v[:maxlen]


def _hhmm(a: dict, key: str) -> str:
    t = logic.parse_hhmm(str(a.get(key, "")))
    if not t:
        raise ValueError("Час має бути у форматі HH:MM")
    return t


# ---------- реалізації ----------
def add_task(uid, a, u, ts, now, day):
    text = _text(a, "text", 200)
    top = bool(a.get("top"))
    tid = db.add_task(uid, text, day, top=top)
    return {"ok": True, "task_id": tid, "summary": f"Додано {'головну ' if top else ''}задачу: {text}"}


def _own_task(uid, a):
    t = db.task(uid, _int(a, "task_id", 1, 10**9))
    if not t:
        raise ValueError("Задачі з таким id немає")
    return t


def complete_task(uid, a, u, ts, now, day):
    t = _own_task(uid, a)
    db.finish_task(uid, t["id"], day)
    return {"ok": True, "summary": f"Виконано: {t['text']}"}


def delete_task(uid, a, u, ts, now, day):
    t = _own_task(uid, a)
    db.delete_task(uid, t["id"])
    return {"ok": True, "summary": f"Видалено задачу: {t['text']}"}


def log_water(uid, a, u, ts, now, day):
    n = _int(a, "glasses", 1, 10, 1)
    for _ in range(n):
        db.add_event(uid, ts, day, "water", None, 1)
    return {"ok": True, "total_today": len(db.events(uid, day, "water")), "summary": f"Вода: +{n}"}


def _log_minutes(kind, label):
    def fn(uid, a, u, ts, now, day):
        m = _int(a, "minutes", 5, 240)
        db.add_event(uid, ts, day, kind, None, m)
        return {"ok": True, "summary": f"{label}: {m} хв"}
    return fn


def log_energy(uid, a, u, ts, now, day):
    level = a.get("level")
    if level not in logic.ENERGY:
        raise ValueError("level має бути high, mid або low")
    icon, name, score = logic.ENERGY[level]
    db.add_event(uid, ts, day, "energy", level, score)
    return {"ok": True, "summary": f"Енергія: {icon} {name}"}


def log_meal(uid, a, u, ts, now, day):
    name = _text(a, "name", 80, required=False)
    db.add_event(uid, ts, day, "meal", name)
    return {"ok": True, "summary": f"Записано їжу{': ' + name if name else ''}"}


def set_wake_time(uid, a, u, ts, now, day):
    t = logic.parse_wake_time(str(a.get("time", "")), now)
    if not t:
        raise ValueError("Час має бути у форматі HH:MM")
    if t > now:
        raise ValueError("Час пробудження не може бути в майбутньому")
    db.run("DELETE FROM events WHERE user_id=? AND day=? AND kind='wake'", (uid, day))
    db.add_event(uid, int(t.timestamp()), day, "wake")
    return {"ok": True, "summary": f"Пробудження: {logic.hm(t)}"}


def add_plan_item(uid, a, u, ts, now, day):
    hhmm = _hhmm(a, "time")
    text = _text(a, "text", 120)
    if len(db.plan_items(uid, day)) >= MAX_PLAN_ITEMS_PER_DAY:
        raise ValueError("Забагато власних пунктів на сьогодні")
    iid = db.add_plan_item(uid, day, hhmm, text)
    return {"ok": True, "item_id": iid, "summary": f"У розпорядок додано: {hhmm} — {text}"}


def remove_plan_item(uid, a, u, ts, now, day):
    it = db.plan_item(uid, _int(a, "item_id", 1, 10**9))
    if not it:
        raise ValueError("Пункту з таким id немає")
    db.delete_plan_item(uid, it["id"])
    return {"ok": True, "summary": f"З розпорядку прибрано: {it['hhmm']} — {it['text']}"}


def start_focus(uid, a, u, ts, now, day):
    minutes = logic.clamp_minutes(_int(a, "minutes", 5, 180))
    mode = a.get("mode") if a.get("mode") in logic.FOCUS_MODES else (
        "deep" if minutes >= 75 else "light" if minutes <= 45 else "creative")
    if db.running_focus(uid):
        raise ValueError("Фокус уже триває")
    db.start_focus(uid, ts, minutes, mode)
    end = logic.local(ts + minutes * 60, u["tz"])
    return {"ok": True, "ends_at": logic.hm(end), "summary": f"Фокус {minutes} хв запущено, до {logic.hm(end)}"}


def stop_focus(uid, a, u, ts, now, day):
    f = db.running_focus(uid)
    if not f:
        raise ValueError("Активного фокусу немає")
    db.set_focus(f["id"], status="cancelled")
    return {"ok": True, "summary": "Фокус зупинено"}


def set_review_time(uid, a, u, ts, now, day):
    t = _hhmm(a, "time")
    db.set_user(uid, review_time=t)
    return {"ok": True, "summary": f"Вечірній огляд о {t}"}


def set_quiet(uid, a, u, ts, now, day):
    on = bool(a.get("on"))
    db.set_user(uid, quiet=int(on))
    return {"ok": True, "summary": "Тихий режим " + ("увімкнено" if on else "вимкнено")}


_HANDLERS = {
    "add_task": add_task, "complete_task": complete_task, "delete_task": delete_task,
    "log_water": log_water, "log_move": _log_minutes("move", "Рух"), "log_read": _log_minutes("read", "Читання"),
    "log_energy": log_energy, "log_meal": log_meal, "set_wake_time": set_wake_time,
    "add_plan_item": add_plan_item, "remove_plan_item": remove_plan_item,
    "start_focus": start_focus, "stop_focus": stop_focus,
    "set_review_time": set_review_time, "set_quiet": set_quiet,
}


def execute(uid: int, name: str, args: dict | None) -> dict:
    fn = _HANDLERS.get(name)
    if not fn:
        return {"ok": False, "error": f"Невідомий інструмент {name}"}
    try:
        return fn(uid, args or {}, *_ctx(uid))
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception:
        log.exception("tool %s failed", name)
        return {"ok": False, "error": "Внутрішня помилка"}
