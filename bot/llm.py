"""Чат із Google Gemini через REST (безкоштовний тариф) з викликом інструментів (function calling).
Без додаткових залежностей: використовує aiohttp з aiogram."""
from __future__ import annotations

import asyncio
from typing import Callable

import aiohttp

from . import actions, config

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_ROUNDS = 4          # скільки разів модель може викликати інструменти за одне повідомлення
MAX_CALLS = 8           # загальний ліміт викликів інструментів за повідомлення

SYSTEM = (
    "Ти — лаконічний, теплий асистент усередині Telegram-бота «операційна система дня». "
    "Допомагаєш користувачу з планом дня, енергією, фокусом, задачами, їжею та звичками. "
    "Відповідай українською, коротко (до 6 речень), конкретно й без повчань. "
    "Використовуй контекст дня нижче, але не переказуй його без потреби. "
    "Ти не лікар: при проблемах зі здоров'ям радь звернутись до фахівця. "
    "Не вигадуй даних, яких немає в контексті.\n\n"
    "Ти можеш змінювати розпорядок дня через інструменти (додати/виконати/видалити задачу, записати воду, рух, "
    "читання, енергію, їжу, виправити час пробудження, додати власний пункт розпорядку на сьогодні, запустити "
    "або зупинити фокус, змінити час вечірнього огляду, тихий режим). "
    "Викликай інструмент ЛИШЕ коли користувач прямо просить щось змінити чи записати. "
    "Для прохань на кшталт «порадь» чи «що мені робити» лише відповідай текстом. "
    "Для задач і пунктів розпорядку бери id тільки з контексту, ніколи не вигадуй їх. "
    "Не видаляй нічого без прямого прохання. Якщо інструмент повернув помилку, скажи про це чесно. "
    "Після змін коротко підтвердь, що саме зроблено."
)


class LLMError(Exception):
    """Помилка, текст якої можна показати користувачу."""


def build_payload(history: list[dict], user_text: str, context: str, tools: bool = False) -> dict:
    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history[-10:]]
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    payload = {
        "system_instruction": {"parts": [{"text": f"{SYSTEM}\n\nКонтекст дня:\n{context}"}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 700, "temperature": 0.7},
    }
    if tools:
        payload["tools"] = actions.TOOLS
    return payload


def _parts(data: dict) -> list[dict]:
    try:
        return data["candidates"][0]["content"]["parts"] or []
    except (KeyError, IndexError, TypeError):
        return []


def parse_response(data: dict) -> str:
    text = "".join(p.get("text", "") for p in _parts(data) if isinstance(p, dict)).strip()
    if not text:
        raise LLMError("Не вдалося отримати відповідь (можливо, запит заблоковано фільтром). Спробуй переформулювати.")
    return text[:4000]


async def _post(payload: dict) -> dict:
    if not config.GEMINI_API_KEY:
        raise LLMError("Чат не налаштовано: на сервері немає GEMINI_API_KEY.")
    url = API.format(model=config.GEMINI_MODEL)
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(url, json=payload, headers=headers) as r:
                if r.status == 429:
                    raise LLMError("Безкоштовна квота Gemini тимчасово вичерпана. Спробуй за кілька хвилин.")
                if r.status in (400, 401, 403, 404):
                    raise LLMError("Gemini відхилив запит. Перевір GEMINI_API_KEY і GEMINI_MODEL на сервері.")
                if r.status != 200:
                    raise LLMError(f"Сервіс Gemini тимчасово недоступний ({r.status}). Спробуй пізніше.")
                return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise LLMError("Немає зв'язку з Gemini. Спробуй пізніше.")


async def ask(history: list[dict], user_text: str, context: str,
              executor: Callable[[str, dict], dict] | None = None) -> tuple[str, list[str]]:
    """Повертає (відповідь, список зроблених змін). executor(name, args) виконує інструмент."""
    payload = build_payload(history, user_text, context, tools=executor is not None)
    done: list[str] = []
    calls_made = 0
    for _ in range(MAX_ROUNDS):
        data = await _post(payload)
        parts = _parts(data)
        calls = [p for p in parts if isinstance(p, dict) and "functionCall" in p]
        if not calls or executor is None:
            try:
                return parse_response(data), done
            except LLMError:
                if done:
                    return "Готово.", done
                raise
        # Частини моделі повертаємо як є (разом із thoughtSignature, якщо модель її надіслала)
        payload["contents"].append({"role": "model", "parts": parts})
        responses = []
        for p in calls:
            fc = p["functionCall"]
            if calls_made >= MAX_CALLS:
                result = {"ok": False, "error": "Забагато дій за одне повідомлення"}
            else:
                calls_made += 1
                result = executor(fc.get("name", ""), fc.get("args") or {})
            if result.get("ok") and result.get("summary"):
                done.append(result["summary"])
            body = {k: v for k, v in result.items() if k != "summary"}
            responses.append({"functionResponse": {"name": fc.get("name", ""), "response": body}})
        payload["contents"].append({"role": "user", "parts": responses})
    return "Виконав кілька дій; перевір результат у плані та задачах.", done
