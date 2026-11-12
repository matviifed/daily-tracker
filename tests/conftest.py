import pytest

from bot import db

from .fake_turso import make_client


@pytest.fixture(autouse=True, params=["local", "turso"])
def db_backend(request):
    """Усі тести проганяються і на локальному SQLite, і на Turso-бекенді (фейковому)."""
    if request.param == "local":
        db.init(":memory:")
    else:
        db.init(turso_url="libsql://fake.turso.io", turso_token="tok", client=make_client("tok"))
    yield request.param
