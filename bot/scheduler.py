"""Фоновий цикл: завершення фокусу, м'які нагадування, вечірній огляд. Нічого не шле під час фокусу."""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup

from . import db, logic
from .handlers import energy_kb, snooze_row

log = logging.getLogger("scheduler")

ENERGY_EVERY = 3 * 3600   # не частіше ніж раз на 3 години
MEAL_GAP = 5 * 3600       # нагадати про їжу, якщо не їв 5 год
MEAL_EVERY = 2 * 3600


def last_ping(uid: int, kind: str) -> int:
    row = db.one("SELECT key FROM sent WHERE user_id=? AND key LIKE ? ORDER BY key DESC LIMIT 1", (uid, f"{kind}:%"))
    return int(row["key"].split(":")[1]) if row else 0


def ping_mark(uid: int, kind: str, now: int):
    db.mark_sent(uid, f"{kind}:{now}")


def decide(u, now: int) -> tuple[str, dict] | None:
    """Чиста функція рішення: яке нагадування (якщо треба) надіслати користувачу зараз."""
    uid, tz = u["id"], u["tz"]
    loc = logic.local(now, tz)
    day = loc.strftime("%Y-%m-%d")

    if db.running_focus(uid):
        return None

    wake = db.last_event(uid, "wake", day)
    review_due = (loc >= logic.at(loc, u["review_time"]) and wake is not None
                  and not db.was_sent(uid, f"rev:{day}") and not db.review(uid, day))
    if review_due:
        return "review", {"day": day}

    if u["snooze_until"] > now or u["quiet"]:
        return None

    if not wake:
        if loc.hour >= 10 and loc.hour < 20 and not db.was_sent(uid, f"wakeping:{day}"):
            return "wakeping", {"day": day}
        return None

    if 10 <= loc.hour < 20:
        en = db.last_event(uid, "energy", day)
        ref = max(en["ts"] if en else 0, wake["ts"], last_ping(uid, "en"))
        if now - ref >= ENERGY_EVERY:
            return "energy", {}

    if 9 <= loc.hour < 21:
        meal = db.last_event(uid, "meal", day)
        ref = meal["ts"] if meal else wake["ts"]
        if now - ref >= MEAL_GAP and now - last_ping(uid, "meal") >= MEAL_EVERY:
            return "meal", {"ago": (now - ref) // 60}
    return None


async def tick(bot: Bot, now: int | None = None):
    now = now or int(time.time())

    for f in db.due_focus(now):
        db.set_focus(f["id"], status="finished")
        try:
            await bot.send_message(
                f["user_id"], f"⏰ Фокус {f['minutes']} хв завершено! Зробив, що планував?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    B(text="✅ Так", callback_data=f"fr:{f['id']}:yes"),
                    B(text="🟡 Частково", callback_data=f"fr:{f['id']}:part"),
                    B(text="🔴 Ні", callback_data=f"fr:{f['id']}:no")]]))
        except Exception:
            log.exception("focus notify failed")

    for u in db.all_users():
        try:
            d = decide(u, now)
            if not d:
                continue
            kind, info = d
            uid = u["id"]
            if kind == "review":
                db.mark_sent(uid, f"rev:{info['day']}")
                await bot.send_message(uid, "🌙 Час підбити підсумки дня?", reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[B(text="Почати (1–2 хв)", callback_data="rv:start"),
                                      B(text="Не сьогодні", callback_data="rv:skip")]]))
            elif kind == "wakeping":
                db.mark_sent(uid, f"wakeping:{info['day']}")
                await bot.send_message(uid, "Доброго дня! Не бачу відмітки про пробудження. Якщо вже на ногах — "
                                            "натисни «☀️ Прокинувся», і я збудую план.")
            elif kind == "energy":
                ping_mark(uid, "en", now)
                kb = energy_kb()
                kb.inline_keyboard.append(snooze_row())
                await bot.send_message(uid, "Як енергія зараз?", reply_markup=kb)
            elif kind == "meal":
                ping_mark(uid, "meal", now)
                await bot.send_message(
                    uid, f"🍽 Остання їжа була {logic.fmt_ago(info['ago'])} тому. Швидкий варіант?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [B(text="⚡ Покажи варіанти", callback_data="m:quick:10")], snooze_row()]))
        except Exception:
            log.exception("reminder failed for %s", u["id"])


async def run(bot: Bot, interval: int = 30):
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(interval)
