"""Мінімальний фейковий Turso (Hrana over HTTP) поверх SQLite — щоб перевіряти _Turso без реальної бази."""
import json
import sqlite3

import httpx


def _cell(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _arg(a):
    t = a["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(a["value"])
    if t == "float":
        return float(a["value"])
    return a["value"]


def make_client(token: str = "tok") -> httpx.Client:
    conn = sqlite3.connect(":memory:", check_same_thread=False)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/pipeline"
        assert request.headers["authorization"] == f"Bearer {token}"
        body = json.loads(request.content)
        results = []
        for req in body["requests"]:
            if req["type"] == "close":
                results.append({"type": "ok", "response": {"type": "close"}})
                continue
            stmt = req["stmt"]
            try:
                cur = conn.execute(stmt["sql"], [_arg(a) for a in stmt.get("args", [])])
                conn.commit()
            except sqlite3.Error as e:
                results.append({"type": "error", "error": {"message": str(e)}})
                continue
            cols = [{"name": d[0]} for d in (cur.description or [])]
            rows = [[_cell(v) for v in row] for row in cur.fetchall()]
            results.append({"type": "ok", "response": {"type": "execute", "result": {
                "cols": cols, "rows": rows, "affected_row_count": max(cur.rowcount, 0),
                "last_insert_rowid": str(cur.lastrowid) if cur.lastrowid else None}}})
        return httpx.Response(200, json={"results": results})

    return httpx.Client(transport=httpx.MockTransport(handler))
