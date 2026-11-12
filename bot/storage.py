"""Сховище FSM у БД: у serverless пам'ять між запитами не зберігається."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

from . import db


def _k(key: StorageKey) -> str:
    return f"{key.chat_id}:{key.user_id}:{key.destiny}"


class DbStorage(BaseStorage):
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        name = state.state if isinstance(state, State) else state
        row = db.fsm_get(_k(key))
        db.fsm_set(_k(key), name, row["data"] if row else "{}")

    async def get_state(self, key: StorageKey) -> Optional[str]:
        row = db.fsm_get(_k(key))
        return row["state"] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        row = db.fsm_get(_k(key))
        db.fsm_set(_k(key), row["state"] if row else None, json.dumps(data))

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        row = db.fsm_get(_k(key))
        return json.loads(row["data"]) if row else {}

    async def close(self) -> None:
        return None
