"""Чат із Google Gemini через REST (безкоштовний тариф). Без додаткових залежностей: використовує aiohttp з aiogram."""
from __future__ import annotations

import asyncio

import aiohttp

from . import config

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM = (
    "Ти — лаконічний, теплий асистент усередині Telegram-бота «операційна система дня». "
    "Допомагаєш користувачу з планом дня, енергією, фокусом, задачами, їжею та звичками. "
    "Відповідай українською, коротко (до 6 речень), конкретно й без повчань. "
    "Використовуй контекст дня нижче, але не переказуй його без потреби. "
    "Ти не лікар: при проблемах зі здоров'ям радь звернутись до фахівця. "
    "Не вигадуй даних, яких немає в контексті."
)


class LLMError(Exception):
    """Помилка, текст якої можна показати користувачу."""


def build_payload(history: list[dict], user_text: str, context: str) -> dict:
    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history[-10:]]
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    return {
        "system_instruction": {"parts": [{"text": f"{SYSTEM}\n\nКонтекст дня:\n{context}"}]},
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 700, "temperature": 0.7},
    }


def parse_response(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        raise LLMError("Не вдалося отримати відповідь (можливо, запит заблоковано фільтром). Спробуй переформулювати.")
    return text[:4000]


async def ask(history: list[dict], user_text: str, context: str) -> str:
    if not config.GEMINI_API_KEY:
        raise LLMError("Чат не налаштовано: на сервері немає GEMINI_API_KEY.")
    url = API.format(model=config.GEMINI_MODEL)
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.post(url, json=build_payload(history, user_text, context), headers=headers) as r:
                if r.status == 429:
                    raise LLMError("Безкоштовна квота Gemini тимчасово вичерпана. Спробуй за кілька хвилин.")
                if r.status in (400, 401, 403, 404):
                    raise LLMError("Gemini відхилив запит. Перевір GEMINI_API_KEY і GEMINI_MODEL на сервері.")
                if r.status != 200:
                    raise LLMError(f"Сервіс Gemini тимчасово недоступний ({r.status}). Спробуй пізніше.")
                data = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        raise LLMError("Немає зв'язку з Gemini. Спробуй пізніше.")
    return parse_response(data)
