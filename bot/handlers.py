"""Telegram-обробники. Майже все — через кнопки."""
from __future__ import annotations

import html
import json
import time
from datetime import timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton as B, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

from . import config, db, llm, logic

router = Router()
esc = html.escape

# ---------------- меню ----------------
BTN_WAKE, BTN_PLAN, BTN_ENERGY, BTN_FOCUS = "☀️ Прокинувся", "📋 План", "⚡ Енергія", "🎯 Фокус"
BTN_HABITS, BTN_MEAL, BTN_TASKS = "💧 Звички", "🍽 Їжа", "📝 Задачі"
BTN_EVENING, BTN_STATS = "🌙 Вечір", "📊 Статистика"
BTN_CHAT = "💬 Чат"

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_WAKE), KeyboardButton(text=BTN_PLAN), KeyboardButton(text=BTN_ENERGY)],
        [KeyboardButton(text=BTN_FOCUS), KeyboardButton(text=BTN_HABITS), KeyboardButton(text=BTN_MEAL)],
        [KeyboardButton(text=BTN_TASKS), KeyboardButton(text=BTN_EVENING), KeyboardButton(text=BTN_STATS)],
        [KeyboardButton(text=BTN_CHAT)],
    ],
    resize_keyboard=True,
)
MENU_TEXTS = {BTN_WAKE, BTN_PLAN, BTN_ENERGY, BTN_FOCUS, BTN_HABITS, BTN_MEAL, BTN_TASKS, BTN_EVENING, BTN_STATS, BTN_CHAT}

HELP = (
    "Я — твоя операційна система дня. Майже все робиться кнопками внизу.\n\n"
    "<b>Команди</b>\n"
    "/wake [8:10] — прокинувся (можна вказати час)\n"
    "/plan — план на день (адаптується до енергії)\n"
    "/focus [хв] — фокус-сесія, напр. /focus 90\n"
    "/task текст — додати задачу, /top текст — головна\n"
    "/review — вечірній огляд\n"
    "/stats — статистика за тиждень\n"
    "/chat — розмова з ШІ (Gemini), /ask питання — разове запитання, /endchat — вийти\n"
    "/tz Europe/Kyiv — часова зона\n"
    "/reviewtime 21:30 — час вечірнього огляду\n"
    "/quiet on|off — тихий режим (без нагадувань про енергію й їжу)\n\n"
    "Будь-який текст без команди стане задачею (поза режимом чату)."
)


def allowed(obj) -> bool:
    return not config.ALLOWED_USERS or obj.from_user.id in config.ALLOWED_USERS


router.message.filter(allowed)
router.callback_query.filter(allowed)


# ---------------- контекст ----------------
class Ctx:
    def __init__(self, uid: int):
        db.ensure_user(uid, config.DEFAULT_TZ)
        self.uid = uid
        self.user = db.user(uid)
        self.tz = self.user["tz"]
        self.ts = int(time.time())
        self.now = logic.local(self.ts, self.tz)
        self.day = self.now.strftime("%Y-%m-%d")

    def yesterday(self) -> str:
        return (self.now - timedelta(days=1)).strftime("%Y-%m-%d")


def energy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        B(text="🟢 Висока", callback_data="e:high"),
        B(text="🟡 Середня", callback_data="e:mid"),
        B(text="🔴 Низька", callback_data="e:low"),
    ]])


def snooze_row() -> list[B]:
    return [B(text="⏰ Не зараз (1 год)", callback_data="z:60"), B(text="🤫 До завтра", callback_data="z:720")]


# ---------------- старт ----------------
@router.message(Command("start", "help"))
async def start(m: Message):
    Ctx(m.from_user.id)
    await m.answer(HELP, reply_markup=MENU, parse_mode="HTML")


# ---------------- ранок ----------------
def wake_event(c: Ctx):
    return db.last_event(c.uid, "wake", c.day)


def plan_text(c: Ctx) -> str:
    w = wake_event(c)
    if not w:
        return "Я ще не знаю, коли ти прокинувся. Натисни «☀️ Прокинувся»."
    wake = logic.local(w["ts"], c.tz)
    en = db.last_event(c.uid, "energy", c.day)
    tasks = [t["text"] for t in db.open_tasks(c.uid, c.day)][:3]
    had_meal = db.last_event(c.uid, "meal", c.day) is not None
    items = logic.build_plan(c.now, wake, en["value"] if en else None, tasks, had_meal, c.user["review_time"])
    head = f"📋 <b>План на сьогодні</b>"
    if en and en["value"] == "low":
        head += "  (полегшений: енергія низька)"
    foot = f"\n\n{logic.habit_line(*habit_numbers(c))}"
    return head + "\n\n" + logic.format_plan(items) + foot


@router.message(Command("wake"))
@router.message(F.text == BTN_WAKE)
async def wake(m: Message, command: CommandObject | None = None):
    c = Ctx(m.from_user.id)
    ts = c.ts
    arg = command.args.strip() if command and command.args else ""
    if arg:
        t = logic.parse_wake_time(arg, c.now)
        if not t or t > c.now:
            return await m.answer("Не розумію час. Напиши, наприклад: /wake 8:10 (не пізніше за поточний).")
        ts = int(t.timestamp())
        db.c().execute("DELETE FROM events WHERE user_id=? AND day=? AND kind='wake'", (c.uid, c.day))
        db.c().commit()
    elif wake_event(c):
        w = logic.local(wake_event(c)["ts"], c.tz)
        age = (c.now - w).total_seconds() / 60
        await m.answer(f"Ти вже прокинувся о {logic.hm(w)} (день триває {logic.fmt_ago(age)}).")
        return await m.answer(plan_text(c), parse_mode="HTML")
    db.add_event(c.uid, ts, c.day, "wake")
    c = Ctx(m.from_user.id)
    await m.answer("Доброго ранку! ☀️ Старт без поспіху: склянка води, світло, потягнись.", reply_markup=MENU)
    await m.answer(plan_text(c), parse_mode="HTML")
    await m.answer("Як енергія зараз?", reply_markup=energy_kb())


@router.message(Command("plan"))
@router.message(F.text == BTN_PLAN)
async def plan(m: Message):
    await m.answer(plan_text(Ctx(m.from_user.id)), parse_mode="HTML")


@router.callback_query(F.data == "plan")
async def plan_cb(cb: CallbackQuery):
    await cb.message.answer(plan_text(Ctx(cb.from_user.id)), parse_mode="HTML")
    await cb.answer()


# ---------------- енергія ----------------
@router.message(F.text == BTN_ENERGY)
async def ask_energy(m: Message):
    await m.answer("Як енергія зараз?", reply_markup=energy_kb())


@router.callback_query(F.data.startswith("e:"))
async def energy_cb(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    level = cb.data.split(":")[1]
    icon, name, score = logic.ENERGY[level]
    db.add_event(c.uid, c.ts, c.day, "energy", level, score)
    text = f"{icon} Записав: {name}.\n{logic.energy_advice(level, c.now)}"
    lm = db.last_event(c.uid, "meal", c.day)
    ago = (c.ts - lm["ts"]) / 60 if lm else None
    nudge = logic.wellbeing_nudge(level, ago, len(db.events(c.uid, c.day, "water")))
    if nudge:
        text += f"\n\n💡 {nudge}"
    rows = []
    if level == "low":
        rows.append([B(text="🍽 Що поїсти", callback_data="m:any:10"), B(text="💧 +склянка", callback_data="h:water")])
    rows.append([B(text="📋 Оновити план", callback_data="plan")])
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer("Зафіксовано")


@router.callback_query(F.data.startswith("z:"))
async def snooze(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    minutes = int(cb.data.split(":")[1])
    db.set_user(c.uid, snooze_until=c.ts + minutes * 60)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Ок, не турбую" + (" до завтра" if minutes >= 600 else ""))


@router.message(Command("quiet"))
async def quiet(m: Message, command: CommandObject):
    c = Ctx(m.from_user.id)
    arg = (command.args or "").strip().lower()
    if arg not in ("on", "off"):
        return await m.answer("Напиши /quiet on або /quiet off. Зараз: " + ("увімкнено" if c.user["quiet"] else "вимкнено"))
    db.set_user(c.uid, quiet=int(arg == "on"))
    await m.answer("Тихий режим " + ("увімкнено 🤫" if arg == "on" else "вимкнено"))


# ---------------- фокус ----------------
def focus_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=f"{name} · {mins} хв", callback_data=f"fs:{mins}:{key}")]
        for key, (name, mins) in logic.FOCUS_MODES.items()
    ])


async def begin_focus(target: Message, c: Ctx, minutes: int, mode: str):
    run = db.running_focus(c.uid)
    if run:
        left = max(0, (run["end_ts"] - c.ts) // 60)
        return await target.answer(f"Фокус уже триває, ще {left} хв.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[B(text="⏹ Зупинити", callback_data=f"fx:{run['id']}")]]))
    fid = db.start_focus(c.uid, c.ts, minutes, mode)
    end = logic.local(c.ts + minutes * 60, c.tz)
    name = logic.FOCUS_MODES.get(mode, ("🎯 Фокус", 0))[0]
    await target.answer(
        f"{name} запущено на {minutes} хв — до <b>{logic.hm(end)}</b>.\nТелефон убік, я мовчу (крім завершення).",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="⏹ Зупинити", callback_data=f"fx:{fid}")]]))


@router.message(Command("focus"))
async def focus_cmd(m: Message, command: CommandObject):
    c = Ctx(m.from_user.id)
    arg = (command.args or "").strip()
    if arg.isdigit():
        mins = logic.clamp_minutes(int(arg))
        mode = "deep" if mins >= 75 else "light" if mins <= 45 else "creative"
        return await begin_focus(m, c, mins, mode)
    await m.answer("Який режим?", reply_markup=focus_start_kb())


@router.message(F.text == BTN_FOCUS)
async def focus_btn(m: Message):
    c = Ctx(m.from_user.id)
    if db.running_focus(c.uid):
        return await begin_focus(m, c, 0, "deep")
    await m.answer("Який режим?", reply_markup=focus_start_kb())


@router.callback_query(F.data.startswith("fs:"))
async def focus_start_cb(cb: CallbackQuery):
    _, mins, mode = cb.data.split(":")
    await begin_focus(cb.message, Ctx(cb.from_user.id), int(mins), mode)
    await cb.answer()


@router.callback_query(F.data.startswith("fx:"))
async def focus_cancel(cb: CallbackQuery):
    fid = int(cb.data.split(":")[1])
    row = db.one("SELECT * FROM focus WHERE id=? AND user_id=?", (fid, cb.from_user.id))
    if row and row["status"] == "running":
        db.set_focus(fid, status="cancelled")
        await cb.message.edit_text("⏹ Фокус зупинено. Нічого страшного — спробуємо ще раз, коли будеш готовий.")
    await cb.answer()


@router.callback_query(F.data.startswith("fr:"))
async def focus_result(cb: CallbackQuery):
    _, fid, res = cb.data.split(":")
    row = db.one("SELECT * FROM focus WHERE id=? AND user_id=?", (int(fid), cb.from_user.id))
    if not row:
        return await cb.answer()
    db.set_focus(int(fid), result=res)
    label = {"yes": "✅ Супер!", "part": "🟡 Частково — теж результат.", "no": "🔴 Буває. Розбий задачу на менші шматки."}[res]
    text = f"{label}\n{logic.break_suggestion(row['minutes'])}"
    markup = None
    if res == "no":
        text += "\nЯк енергія?"
        markup = energy_kb()
    await cb.message.edit_text(text, reply_markup=markup)
    await cb.answer()


# ---------------- звички ----------------
def habit_numbers(c: Ctx, day: str | None = None):
    day = day or c.day
    water = len(db.events(c.uid, day, "water"))
    mv = db.events(c.uid, day, "move")
    rd = db.events(c.uid, day, "read")
    return water, sum(e["num"] or 0 for e in mv), len(mv), sum(e["num"] or 0 for e in rd)


def habits_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="💧 +склянка", callback_data="h:water")],
        [B(text="🚶 +15 хв", callback_data="h:move:15"), B(text="🏃 +30 хв", callback_data="h:move:30")],
        [B(text="📖 +10 хв", callback_data="h:read:10"), B(text="📖 +20 хв", callback_data="h:read:20")],
        [B(text="↩️ Скасувати останнє", callback_data="h:undo")],
    ])


def habits_text(c: Ctx) -> str:
    return "<b>Звички сьогодні</b>\n" + logic.habit_line(*habit_numbers(c))


@router.message(F.text == BTN_HABITS)
async def habits(m: Message):
    await m.answer(habits_text(Ctx(m.from_user.id)), parse_mode="HTML", reply_markup=habits_kb())


@router.callback_query(F.data.startswith("h:"))
async def habit_cb(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    parts = cb.data.split(":")
    kind = parts[1]
    if kind == "undo":
        row = db.one("SELECT * FROM events WHERE user_id=? AND day=? AND kind IN ('water','move','read') "
                     "ORDER BY ts DESC, id DESC LIMIT 1", (c.uid, c.day))
        if row:
            db.run("DELETE FROM events WHERE id=?", (row["id"],))
        note = "Скасовано"
    else:
        num = float(parts[2]) if len(parts) > 2 else 1
        db.add_event(c.uid, c.ts, c.day, kind, None, num)
        note = "Записано ✓"
    try:
        await cb.message.edit_text(habits_text(Ctx(c.uid)), parse_mode="HTML", reply_markup=habits_kb())
    except Exception:
        await cb.message.answer(habits_text(Ctx(c.uid)), parse_mode="HTML", reply_markup=habits_kb())
    await cb.answer(note)


# ---------------- їжа ----------------
def meal_kb(mode: str, minutes: int, picks: list[int]) -> InlineKeyboardMarkup:
    rows = [[B(text=f"✅ З'їв №{i + 1}", callback_data=f"ml:{idx}") for i, idx in enumerate(picks)]]
    rows.append([B(text=("• " if mode == k else "") + v, callback_data=f"m:{k}:{minutes}")
                 for k, v in logic.MEAL_MODES.items()][:2])
    rows.append([B(text=("• " if mode == k else "") + v, callback_data=f"m:{k}:{minutes}")
                 for k, v in list(logic.MEAL_MODES.items())[2:]])
    rows.append([B(text=("• " if minutes == t else "") + f"{t} хв", callback_data=f"m:{mode}:{t}") for t in (10, 20, 60)])
    rows.append([B(text="🔄 Інші варіанти", callback_data=f"m:{mode}:{minutes}"),
                 B(text="✅ Поїв інше", callback_data="ml:x")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_meals(c: Ctx, mode: str, minutes: int, target: Message, edit: bool):
    recent_rows = db.q("SELECT value FROM events WHERE user_id=? AND kind='meal' AND value IS NOT NULL "
                       "ORDER BY ts DESC LIMIT 12", (c.uid,))
    recent = [r["value"] for r in recent_rows]
    opts = logic.meal_options(c.now, minutes, None if mode == "any" else mode, recent)
    if not opts:
        text, picks = "Під ці умови нічого не знайшов — збільш час або зміни режим.", []
    else:
        picks = [logic.MEALS.index(o) for o in opts]
        lm = db.last_event(c.uid, "meal", c.day)
        since = f"Остання їжа {logic.fmt_ago((c.ts - lm['ts']) / 60)} тому.\n" if lm else ""
        lines = "\n".join(f"{i + 1}. {o['n']} (~{o['m']} хв)" for i, o in enumerate(opts))
        text = f"🍽 <b>Що поїсти</b>\n{since}{lines}"
    kb = meal_kb(mode, minutes, picks)
    if edit:
        try:
            await target.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            pass
    await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(F.text == BTN_MEAL)
async def meal_btn(m: Message):
    await show_meals(Ctx(m.from_user.id), "any", 20, m, edit=False)


@router.callback_query(F.data.startswith("m:"))
async def meal_cb(cb: CallbackQuery):
    _, mode, mins = cb.data.split(":")
    await show_meals(Ctx(cb.from_user.id), mode, int(mins), cb.message, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("ml:"))
async def meal_log(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    idx = cb.data.split(":")[1]
    name = None if idx == "x" else logic.MEALS[int(idx)]["n"]
    db.add_event(c.uid, c.ts, c.day, "meal", name)
    await cb.message.edit_text(f"✅ Записав: {esc(name) if name else 'прийом їжі'}. Смачного!")
    await cb.answer()


# ---------------- задачі ----------------
def tasks_view(c: Ctx) -> tuple[str, InlineKeyboardMarkup | None]:
    ts = db.open_tasks(c.uid, c.day)
    if not ts:
        return "Задач немає. Напиши будь-який текст — і він стане задачею.", None
    lines, rows = [], []
    for t in ts:
        mark = "🎯" if t["top"] else "•"
        carry = " ↪️" if t["day"] < c.day else ""
        lines.append(f"{mark} {esc(t['text'])}{carry}")
        rows.append([B(text=f"✅ {t['text'][:28]}", callback_data=f"t:done:{t['id']}"),
                     B(text="🗑", callback_data=f"t:del:{t['id']}")])
    return "<b>Задачі</b>\n" + "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == BTN_TASKS)
@router.message(Command("tasks"))
async def tasks(m: Message):
    text, kb = tasks_view(Ctx(m.from_user.id))
    await m.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("task", "top"))
async def add_task_cmd(m: Message, command: CommandObject):
    text = (command.args or "").strip()
    if not text:
        return await m.answer(f"Напиши текст: /{command.command} Купити квитки")
    c = Ctx(m.from_user.id)
    db.add_task(c.uid, text, c.day, top=command.command == "top")
    await m.answer("🎯 Головна задача додана." if command.command == "top" else "➕ Додано.")


@router.callback_query(F.data.startswith("t:"))
async def task_cb(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    _, action, tid = cb.data.split(":")
    if action == "done":
        db.finish_task(c.uid, int(tid), c.day)
    else:
        db.delete_task(c.uid, int(tid))
    text, kb = tasks_view(c)
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("Готово ✓" if action == "done" else "Видалено")


# ---------------- вечірній огляд ----------------
class Review(StatesGroup):
    well = State()
    notwell = State()
    top = State()
    prep = State()


MOODS = [("😫", 1), ("😕", 2), ("🙂", 3), ("😄", 4)]


async def begin_review(target: Message, state: FSMContext):
    await state.set_state(Review.well)
    await target.answer("🌙 <b>Вечірній огляд</b> (відповідай коротко, «-» щоб пропустити)\n\n"
                        "1/4. Що вийшло сьогодні?", parse_mode="HTML")


@router.message(Command("review"))
@router.message(F.text == BTN_EVENING)
async def review_cmd(m: Message, state: FSMContext):
    await begin_review(m, state)


@router.callback_query(F.data == "rv:start")
async def review_cb(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup(reply_markup=None)
    await begin_review(cb.message, state)
    await cb.answer()


@router.callback_query(F.data == "rv:skip")
async def review_skip(cb: CallbackQuery):
    await cb.message.edit_text("Ок, сьогодні без огляду. Добраніч 🌙")
    await cb.answer()


def clean(s: str) -> str | None:
    s = (s or "").strip()
    return None if s in ("", "-", "—") else s


@router.message(Review.well, F.text)
async def rv_well(m: Message, state: FSMContext):
    c = Ctx(m.from_user.id)
    db.save_review(c.uid, c.day, went_well=clean(m.text))
    await state.set_state(Review.notwell)
    await m.answer("2/4. Що не вийшло і чому?")


@router.message(Review.notwell, F.text)
async def rv_notwell(m: Message, state: FSMContext):
    c = Ctx(m.from_user.id)
    db.save_review(c.uid, c.day, not_well=clean(m.text))
    await state.set_state(Review.top)
    await m.answer("3/4. Який ОДИН головний пріоритет на завтра?")


@router.message(Review.top, F.text)
async def rv_top(m: Message, state: FSMContext):
    c = Ctx(m.from_user.id)
    top = clean(m.text)
    db.save_review(c.uid, c.day, top_priority=top)
    if top:
        tomorrow = (c.now + timedelta(days=1)).strftime("%Y-%m-%d")
        db.add_task(c.uid, top, tomorrow, top=True)
    await state.set_state(Review.prep)
    await m.answer("4/4. Що підготувати з вечора? (одяг, сумка, документи…)")


@router.message(Review.prep, F.text)
async def rv_prep(m: Message, state: FSMContext):
    c = Ctx(m.from_user.id)
    db.save_review(c.uid, c.day, prep=clean(m.text))
    await state.clear()
    await m.answer("І наостанок: як минув день?", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [B(text=e, callback_data=f"rm:{v}") for e, v in MOODS]]))


@router.callback_query(F.data.startswith("rm:"))
async def rv_mood(cb: CallbackQuery):
    c = Ctx(cb.from_user.id)
    mood = int(cb.data.split(":")[1])
    db.save_review(c.uid, c.day, mood=mood)
    r = db.review(c.uid, c.day)
    undone = [t["text"] for t in db.open_tasks(c.uid, c.day) if t["text"] != r["top_priority"]]
    draft = logic.tomorrow_draft(r["top_priority"], r["prep"], mood, undone)
    await cb.message.edit_text("✅ Огляд збережено.\n\n<b>Чернетка на завтра</b>\n" + draft, parse_mode="HTML")
    await cb.answer()


# ---------------- статистика ----------------
@router.message(F.text == BTN_STATS)
@router.message(Command("stats"))
async def stats(m: Message):
    c = Ctx(m.from_user.id)
    since = (c.now - timedelta(days=6)).strftime("%Y-%m-%d")
    lines = ["📊 <b>Останні 7 днів</b>"]

    samples = [(logic.local(e["ts"], c.tz).hour, int(e["num"])) for e in db.events_since(c.uid, "energy", since)]
    peaks = logic.peak_hours(samples)
    if peaks:
        lines.append("⚡ Пік енергії: " + ", ".join(f"{h:02d}:00 ({a:.1f}/3)" for h, a in peaks))
    else:
        lines.append("⚡ Ще мало даних про енергію (потрібно ≥2 записи на годину).")

    start_ts = logic.day_bounds(since, c.tz)[0]
    f = db.focus_between(c.uid, start_ts, c.ts + 1)
    done = [x for x in f if x["status"] == "finished"]
    mins = sum(x["minutes"] for x in done)
    ok = sum(1 for x in done if x["result"] == "yes")
    lines.append(f"🎯 Фокус: {len(done)} сесій, {mins // 60} год {mins % 60} хв; ціль досягнута у {ok}")

    wakes = db.events_since(c.uid, "wake", since)
    if wakes:
        mins_of_day = [logic.local(w["ts"], c.tz).hour * 60 + logic.local(w["ts"], c.tz).minute for w in wakes]
        avg = sum(mins_of_day) // len(mins_of_day)
        lines.append(f"☀️ Середнє пробудження: {avg // 60:02d}:{avg % 60:02d}")

    met = set()
    for i in range(30):
        d = (c.now - timedelta(days=i)).strftime("%Y-%m-%d")
        if len(db.events(c.uid, d, "water")) >= logic.WATER_GOAL:
            met.add(d)
    lines.append(f"💧 Серія води (≥{logic.WATER_GOAL}): {logic.habit_streak(met, c.day)} дн.")

    revs = [r for r in db.recent_reviews(c.uid, since) if r["mood"]]
    if revs:
        lines.append(f"🌙 Середній настрій: {sum(r['mood'] for r in revs) / len(revs):.1f}/4")
    await m.answer("\n".join(lines), parse_mode="HTML")


# ---------------- налаштування ----------------
@router.message(Command("tz"))
async def set_tz(m: Message, command: CommandObject):
    name = (command.args or "").strip()
    try:
        ZoneInfo(name)
    except Exception:
        return await m.answer("Вкажи зону, напр.: /tz Europe/Kyiv")
    Ctx(m.from_user.id)
    db.set_user(m.from_user.id, tz=name)
    await m.answer(f"Часова зона: {name}")


@router.message(Command("reviewtime"))
async def set_review_time(m: Message, command: CommandObject):
    t = logic.parse_hhmm(command.args or "")
    if not t:
        return await m.answer("Вкажи час, напр.: /reviewtime 21:30")
    Ctx(m.from_user.id)
    db.set_user(m.from_user.id, review_time=t)
    await m.answer(f"Вечірній огляд о {t}")


# ---------------- чат із Gemini ----------------
CHAT_KB = InlineKeyboardMarkup(inline_keyboard=[[B(text="🚪 Вийти з чату", callback_data="chat:end")]])


def day_context(c: Ctx) -> str:
    lines = [f"Локальний час: {c.now:%Y-%m-%d %H:%M}"]
    w = wake_event(c)
    lines.append(f"Прокинувся о {logic.hm(logic.local(w['ts'], c.tz))}" if w else "Пробудження ще не відмічено")
    en = db.last_event(c.uid, "energy", c.day)
    if en:
        lines.append(f"Остання енергія: {logic.ENERGY[en['value']][1]} о {logic.hm(logic.local(en['ts'], c.tz))}")
    lm = db.last_event(c.uid, "meal", c.day)
    lines.append(f"Остання їжа: {logic.hm(logic.local(lm['ts'], c.tz))}" if lm else "Сьогодні їжу ще не відмічено")
    lines.append("Звички: " + logic.habit_line(*habit_numbers(c)))
    tasks_ = db.open_tasks(c.uid, c.day)[:7]
    if tasks_:
        lines.append("Відкриті задачі: " + "; ".join(("[головна] " if t["top"] else "") + t["text"] for t in tasks_))
    start_ts, end_ts = logic.day_bounds(c.day, c.tz)
    f = [x for x in db.focus_between(c.uid, start_ts, end_ts) if x["status"] == "finished"]
    if f:
        lines.append(f"Фокус-сесій сьогодні: {len(f)} ({sum(x['minutes'] for x in f)} хв)")
    return "\n".join(lines)


async def chat_reply(m: Message, text: str):
    c = Ctx(m.from_user.id)
    st = db.chat_get(c.uid)
    used = st["used"] if st["day"] == c.day else 0
    if used >= config.CHAT_DAILY_LIMIT:
        return await m.answer(f"Ліміт чату на сьогодні вичерпано ({config.CHAT_DAILY_LIMIT} повідомлень). Завтра знову.")
    history = json.loads(st["history"]) if st["history"] else []
    await m.bot.send_chat_action(m.chat.id, "typing")
    try:
        answer = await llm.ask(history, text, day_context(c))
    except llm.LLMError as e:
        return await m.answer(str(e))
    history += [{"role": "user", "text": text}, {"role": "model", "text": answer}]
    db.chat_set(c.uid, history=json.dumps(history[-12:], ensure_ascii=False), day=c.day, used=used + 1)
    await m.answer(answer, reply_markup=CHAT_KB if st["active"] else None)


@router.message(Command("chat"))
@router.message(F.text == BTN_CHAT)
async def chat_start(m: Message):
    c = Ctx(m.from_user.id)
    db.chat_set(c.uid, active=1, history="[]")
    await m.answer(
        "💬 Режим чату увімкнено — пиши вільним текстом, я знаю твій день (план, енергію, задачі).\n"
        "Кнопки меню працюють як завжди.\n\n"
        "⚠️ Повідомлення й короткий контекст дня надсилаються в Google Gemini (безкоштовний тариф "
        "може використовувати їх для покращення моделей). Не пиши паролі й чутливі дані.",
        reply_markup=CHAT_KB)


@router.message(Command("ask"))
async def ask_cmd(m: Message, command: CommandObject):
    text = (command.args or "").strip()
    if not text:
        return await m.answer("Напиши питання після команди: /ask Що мені зробити першим сьогодні?")
    await chat_reply(m, text)


@router.message(Command("endchat"))
async def chat_end_cmd(m: Message):
    db.chat_set(m.from_user.id, active=0, history="[]")
    await m.answer("Чат вимкнено. Текст без команди знову стане задачею.")


@router.callback_query(F.data == "chat:end")
async def chat_end_cb(cb: CallbackQuery):
    db.chat_set(cb.from_user.id, active=0, history="[]")
    await cb.message.answer("Чат вимкнено. Текст без команди знову стане задачею.")
    await cb.answer()


def chat_active(m: Message) -> bool:
    return bool(db.chat_get(m.from_user.id)["active"])


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS), chat_active)
async def chat_text(m: Message):
    await chat_reply(m, m.text.strip())


# ---------------- вільний текст = задача (має бути останнім) ----------------
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_TEXTS))
async def free_text(m: Message):
    c = Ctx(m.from_user.id)
    db.add_task(c.uid, m.text.strip(), c.day)
    await m.answer(f"➕ Додав задачу: {esc(m.text.strip())}", parse_mode="HTML")
