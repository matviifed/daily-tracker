import os
from pathlib import Path


def _load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEFAULT_TZ = os.getenv("DEFAULT_TZ", "Europe/Kyiv")
DB_PATH = os.getenv("DB_PATH", "data/tracker.db")
ALLOWED_USERS = {int(x) for x in os.getenv("ALLOWED_USERS", "").split(",") if x.strip()}

# Vercel / serverless: база Turso, секрети вебхука та пінгера нагадувань
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")

# Чат (Google Gemini, безкоштовний тариф). Без ключа кнопка «Чат» повідомляє, що чат не налаштовано.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CHAT_DAILY_LIMIT = int(os.getenv("CHAT_DAILY_LIMIT", "30"))
