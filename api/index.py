"""Точка входу Vercel (ASGI). Маршрути: /api/webhook, /api/tick, /api/health."""
import hmac
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402

from bot import app as bot_app  # noqa: E402
from bot import config  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.post("/api/webhook")
async def webhook(request: Request):
    if not _same(config.WEBHOOK_SECRET, request.headers.get("x-telegram-bot-api-secret-token", "")):
        raise HTTPException(status_code=403, detail="forbidden")
    await bot_app.process_update(await request.json())
    return {"ok": True}


@app.api_route("/api/tick", methods=["GET", "POST"])
async def tick(request: Request):
    """Викликається зовнішнім пінгером раз на хвилину: завершення фокусу, нагадування, вечірній огляд."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("key", "")
    if not _same(config.CRON_SECRET, token):
        raise HTTPException(status_code=403, detail="forbidden")
    await bot_app.run_tick()
    return {"ok": True}
