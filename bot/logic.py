"""Чиста логіка без Telegram і БД: час, план дня, їжа, поради за енергією, статистика."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ---------------- час ----------------

def tzinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Europe/Kyiv")


def local(ts: float, tz: str) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tzinfo(tz))


def day_of(ts: float, tz: str) -> str:
    return local(ts, tz).strftime("%Y-%m-%d")


def day_bounds(day: str, tz: str) -> tuple[int, int]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tzinfo(tz))
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())


def hm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def at(base: datetime, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return base.replace(hour=h, minute=m, second=0, microsecond=0)


def parse_hhmm(s: str) -> str | None:
    s = s.strip().replace(".", ":")
    try:
        h, m = s.split(":")
        h, m = int(h), int(m)
    except ValueError:
        return None
    if 0 <= h < 24 and 0 <= m < 60:
        return f"{h:02d}:{m:02d}"
    return None


def parse_wake_time(s: str, now: datetime) -> datetime | None:
    """'8:10' -> сьогодні о 08:10 (локально)."""
    t = parse_hhmm(s)
    return at(now, t) if t else None


def fmt_ago(minutes: float) -> str:
    minutes = int(minutes)
    if minutes < 60:
        return f"{minutes} хв"
    h, m = divmod(minutes, 60)
    return f"{h} год {m:02d} хв" if m else f"{h} год"


# ---------------- енергія ----------------

ENERGY = {"high": ("🟢", "Висока", 3), "mid": ("🟡", "Середня", 2), "low": ("🔴", "Низька", 1)}


def energy_advice(level: str, now: datetime) -> str:
    h = now.hour
    if level == "high":
        if h < 18:
            return "Саме час для важкої задачі. Запускай фокус 90 хв — /focus 90."
        return "Енергія є, але вечір близько — добий щось важливе і не починай марафон."
    if level == "mid":
        return "Нормальний стан для рутини й середніх задач. Фокус на 45 хв піде добре — /focus 45."
    if h >= 20:
        return "Енергія низька, вечір — це нормально. Залиш лише мінімум, далі відпочинок і сон."
    return "Енергія низька → важке відсуваю. Склянка води, 10 хв прогулянки або перекус, потім легкі задачі."


def wellbeing_nudge(level: str, last_meal_min_ago: float | None, water: int) -> str | None:
    """Додаткова підказка при низькій енергії: часто причина — їжа/вода."""
    if level != "low":
        return None
    if last_meal_min_ago is None or last_meal_min_ago > 270:
        return "Ти давно не їв — можливо, причина в цьому. Натисни «🍽 Їжа»."
    if water < 3:
        return "Води сьогодні мало — випий склянку."
    return None


def peak_hours(samples: list[tuple[int, int]], top: int = 3, min_samples: int = 2) -> list[tuple[int, float]]:
    """samples: (година, оцінка 1..3). Повертає найкращі години за середньою оцінкою."""
    by: dict[int, list[int]] = {}
    for h, s in samples:
        by.setdefault(h, []).append(s)
    avg = [(h, sum(v) / len(v)) for h, v in by.items() if len(v) >= min_samples]
    avg.sort(key=lambda x: (-x[1], x[0]))
    return avg[:top]


# ---------------- фокус ----------------

FOCUS_MODES = {
    "deep": ("🧠 Deep Work", 90),
    "light": ("🪶 Light Work", 45),
    "creative": ("🎨 Creative", 60),
}


def clamp_minutes(n: int) -> int:
    return max(5, min(180, n))


def break_suggestion(minutes: int) -> str:
    if minutes >= 75:
        return "Зроби перерву 15 хв: відійди від екрана, вода, трохи руху."
    if minutes >= 40:
        return "Перерва 10 хв: розтяжка або вода."
    return "Перерва 5 хв — подивись у вікно, випий води."


# ---------------- звички ----------------

WATER_GOAL = 6
MOVE_GOAL = 1
READ_GOAL = 20


def habit_line(water: int, move_min: float, move_cnt: int, read_min: float) -> str:
    mv = f"{int(move_min)} хв ✓" if move_cnt else "✗"
    rd = f"{int(read_min)} хв ✓" if read_min >= READ_GOAL else (f"{int(read_min)}/{READ_GOAL} хв" if read_min else "✗")
    return f"💧 вода {water}/{WATER_GOAL} · 🚶 рух {mv} · 📖 читання {rd}"


def habit_streak(days_met: set[str], today: str) -> int:
    """Скільки днів поспіль (закінчуючи вчора або сьогодні) мета виконана."""
    d = datetime.strptime(today, "%Y-%m-%d")
    if today not in days_met:
        d -= timedelta(days=1)
    n = 0
    while d.strftime("%Y-%m-%d") in days_met:
        n += 1
        d -= timedelta(days=1)
    return n


# ---------------- їжа ----------------

# slot: b=сніданок, l=обід, d=вечеря, s=перекус; tags: pantry (з того, що є), healthy, tasty
MEALS = [
    {"n": "Вівсянка з бананом і горіхами", "m": 10, "slots": "b", "tags": {"healthy", "pantry"}},
    {"n": "Омлет з сиром і помідором", "m": 10, "slots": "bl", "tags": {"healthy", "pantry"}},
    {"n": "Йогурт, гранола, ягоди", "m": 3, "slots": "bs", "tags": {"healthy"}},
    {"n": "Бутерброд з яйцем і авокадо", "m": 8, "slots": "bl", "tags": {"tasty", "healthy"}},
    {"n": "Сирники з сметаною", "m": 25, "slots": "b", "tags": {"tasty"}},
    {"n": "Гречка з курячою грудкою й овочами", "m": 25, "slots": "ld", "tags": {"healthy"}},
    {"n": "Паста з томатним соусом і сиром", "m": 15, "slots": "ld", "tags": {"tasty", "pantry"}},
    {"n": "Рис з яйцем і соєвим соусом", "m": 12, "slots": "ld", "tags": {"pantry"}},
    {"n": "Салат з тунцем і кукурудзою", "m": 8, "slots": "ld", "tags": {"healthy"}},
    {"n": "Борщ (розігріти) + хліб", "m": 5, "slots": "ld", "tags": {"tasty", "pantry"}},
    {"n": "Курка в духовці з картоплею", "m": 60, "slots": "ld", "tags": {"tasty"}},
    {"n": "Запечена риба з овочами", "m": 35, "slots": "ld", "tags": {"healthy"}},
    {"n": "Піца або бургер (замовити)", "m": 5, "slots": "ld", "tags": {"tasty"}},
    {"n": "Тости з арахісовою пастою", "m": 4, "slots": "bs", "tags": {"pantry", "tasty"}},
    {"n": "Яблуко + жменя горіхів", "m": 2, "slots": "s", "tags": {"healthy", "pantry"}},
    {"n": "Сир і крекери", "m": 3, "slots": "s", "tags": {"pantry"}},
    {"n": "Банан і кефір", "m": 2, "slots": "s", "tags": {"healthy", "pantry"}},
    {"n": "Шоколад і чай", "m": 3, "slots": "s", "tags": {"tasty"}},
    {"n": "Суп-крем з овочів", "m": 30, "slots": "ld", "tags": {"healthy"}},
    {"n": "Вареники з картоплею (з морозилки)", "m": 12, "slots": "ld", "tags": {"pantry", "tasty"}},
]

MEAL_MODES = {"quick": "⚡ Швидко", "pantry": "🥫 З того, що є", "healthy": "🥗 Корисно", "tasty": "😋 Смачно"}


def meal_slot(hour: int) -> str:
    if 4 <= hour < 11:
        return "b"
    if 11 <= hour < 16:
        return "l"
    if 16 <= hour < 18:
        return "s"
    if 18 <= hour < 23:
        return "d"
    return "s"


def meal_options(now: datetime, minutes: int, mode: str | None, recent: list[str],
                 k: int = 3, rng: random.Random | None = None) -> list[dict]:
    rng = rng or random
    slot = meal_slot(now.hour)

    def ok(m, use_slot=True, use_recent=True):
        if m["m"] > minutes:
            return False
        if use_slot and slot not in m["slots"]:
            return False
        if use_recent and m["n"] in recent:
            return False
        if mode == "quick" and m["m"] > 10:
            return False
        if mode in ("pantry", "healthy", "tasty") and mode not in m["tags"]:
            return False
        return True

    for use_slot, use_recent in ((True, True), (True, False), (False, False)):
        pool = [m for m in MEALS if ok(m, use_slot, use_recent)]
        if pool:
            break
    return rng.sample(pool, min(k, len(pool)))


# ---------------- план дня ----------------

def build_plan(now: datetime, wake: datetime, energy: str | None, tasks: list[str],
               had_meal_today: bool, review_time: str = "21:30") -> list[tuple[datetime, str]]:
    """Гнучкий план: показує лише те, що ще попереду; низька енергія зсуває важке на легке."""
    low = energy == "low"
    items: list[tuple[datetime, str]] = []
    t = list(tasks)

    def task(default: str) -> str:
        return f"«{t.pop(0)}»" if t else default

    if not had_meal_today:
        items.append((wake + timedelta(minutes=30), "🍳 Сніданок"))

    f1 = max(wake + timedelta(minutes=60), at(wake, "08:00"))
    if low:
        items.append((f1, f"🪶 Легка робота 45 хв: {task('дрібні задачі, листи')}"))
    else:
        items.append((f1, f"🧠 Фокус 90 хв: {task('головна задача дня')}"))
    f1_end = f1 + timedelta(minutes=45 if low else 90)
    items.append((f1_end + timedelta(minutes=5), "🚶 Перерва: вода + 10 хв руху"))

    lunch = min(max(wake + timedelta(hours=5), at(wake, "12:30")), at(wake, "14:00"))
    items.append((lunch, "🍲 Обід"))
    f2 = lunch + timedelta(minutes=60)
    if low:
        items.append((f2, f"🪶 Легка робота 45 хв: {task('рутина')}"))
    else:
        items.append((f2, f"🎯 Фокус 60 хв: {task('друга задача')}"))
    items.append((max(at(wake, "16:30"), f2 + timedelta(minutes=75)), "🚶 Прогулянка / спорт"))
    items.append((at(wake, "19:00"), "🍽 Вечеря"))
    items.append((at(wake, "20:00"), "📖 Читання 20 хв"))
    items.append((at(wake, review_time), "🌙 Вечірній огляд і план на завтра"))

    items = [(d, s) for d, s in items if d >= now - timedelta(minutes=30)]
    items.sort(key=lambda x: x[0])
    return items


def format_plan(items: list[tuple[datetime, str]]) -> str:
    if not items:
        return "На сьогодні запланованого більше немає. Відпочивай 🌿"
    return "\n".join(f"<b>{hm(d)}</b>  {s}" for d, s in items)


def sleep_hint(hours: float) -> str:
    if hours < 6:
        return "Сну було небагато — план полегшую: більше пауз, менше важкого."
    if hours > 9.5:
        return "Виспався на повну — гарний старт."
    return "Сон у нормі."


# ---------------- вечірній огляд ----------------

def tomorrow_draft(top: str | None, prep: str | None, mood: int | None, undone: list[str]) -> str:
    lines = []
    if top:
        lines.append(f"🎯 Головне на завтра: <b>{top}</b>")
    if undone:
        lines.append("↪️ Перенесено: " + "; ".join(undone[:3]))
    if prep:
        lines.append(f"🧺 З вечора підготувати: {prep}")
    if mood is not None and mood <= 2:
        lines.append("🫶 Настрій низький — на завтра лише одна важлива справа, решта за бажанням.")
    lines.append("\nПрокинувшись, натисни «☀️ Прокинувся» — я збудую план.")
    return "\n".join(lines)
