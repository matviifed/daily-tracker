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
