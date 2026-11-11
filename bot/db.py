"""SQLite-сховище. Усі часи — UTC epoch (секунди); локальний день рахується за tz користувача."""
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  tz TEXT NOT NULL,
  review_time TEXT NOT NULL DEFAULT '21:30',
  snooze_until INTEGER NOT NULL DEFAULT 0,
  quiet INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  ts INTEGER NOT NULL,
  day TEXT NOT NULL,
  kind TEXT NOT NULL,      -- wake | energy | meal | water | move | read
  value TEXT,
  num REAL
);
CREATE INDEX IF NOT EXISTS ev_user_day ON events(user_id, day, kind);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  top INTEGER NOT NULL DEFAULT 0,
  day TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  done_day TEXT
);
CREATE TABLE IF NOT EXISTS focus(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  start_ts INTEGER NOT NULL,
  end_ts INTEGER NOT NULL,
  minutes INTEGER NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',  -- running | finished | cancelled
  result TEXT                              -- yes | part | no
);
CREATE TABLE IF NOT EXISTS reviews(
  user_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  went_well TEXT, not_well TEXT, top_priority TEXT, prep TEXT, mood INTEGER,
  PRIMARY KEY(user_id, day)
);
CREATE TABLE IF NOT EXISTS sent(
  user_id INTEGER NOT NULL,
  key TEXT NOT NULL,
  PRIMARY KEY(user_id, key)
);
"""

_conn: sqlite3.Connection | None = None


def init(path: str) -> sqlite3.Connection:
    global _conn
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
    _conn.commit()
    return _conn


def c() -> sqlite3.Connection:
    assert _conn is not None, "db.init() не викликано"
    return _conn


def q(sql: str, args=()) -> list[sqlite3.Row]:
    return c().execute(sql, args).fetchall()


def one(sql: str, args=()):
    return c().execute(sql, args).fetchone()


def run(sql: str, args=()) -> int:
    cur = c().execute(sql, args)
    c().commit()
    return cur.lastrowid


# ---------- users ----------
def ensure_user(uid: int, tz: str):
    if not one("SELECT 1 FROM users WHERE id=?", (uid,)):
        run("INSERT INTO users(id,tz,created) VALUES(?,?,?)", (uid, tz, int(time.time())))


def user(uid: int):
    return one("SELECT * FROM users WHERE id=?", (uid,))


def all_users():
    return q("SELECT * FROM users")


def set_user(uid: int, **kw):
    cols = ",".join(f"{k}=?" for k in kw)
    run(f"UPDATE users SET {cols} WHERE id=?", (*kw.values(), uid))


# ---------- events ----------
def add_event(uid, ts, day, kind, value=None, num=None):
    return run("INSERT INTO events(user_id,ts,day,kind,value,num) VALUES(?,?,?,?,?,?)",
               (uid, ts, day, kind, value, num))


def events(uid, day, kind=None):
    if kind:
        return q("SELECT * FROM events WHERE user_id=? AND day=? AND kind=? ORDER BY ts", (uid, day, kind))
    return q("SELECT * FROM events WHERE user_id=? AND day=? ORDER BY ts", (uid, day))


def last_event(uid, kind, day=None):
    if day:
        return one("SELECT * FROM events WHERE user_id=? AND kind=? AND day=? ORDER BY ts DESC, id DESC LIMIT 1",
                   (uid, kind, day))
    return one("SELECT * FROM events WHERE user_id=? AND kind=? ORDER BY ts DESC, id DESC LIMIT 1", (uid, kind))


def events_since(uid, kind, since_day):
    return q("SELECT * FROM events WHERE user_id=? AND kind=? AND day>=? ORDER BY ts", (uid, kind, since_day))


def undo_last(uid, day, kind):
    row = last_event(uid, kind, day)
    if row:
        run("DELETE FROM events WHERE id=?", (row["id"],))
    return row


# ---------- tasks ----------
def add_task(uid, text, day, top=False):
    return run("INSERT INTO tasks(user_id,text,top,day) VALUES(?,?,?,?)", (uid, text, int(top), day))


def open_tasks(uid, day):
    """Невиконані задачі: сьогоднішні та перенесені з минулих днів."""
    return q("SELECT * FROM tasks WHERE user_id=? AND done=0 AND day<=? ORDER BY top DESC, id", (uid, day))


def tasks_done_on(uid, day):
    return q("SELECT * FROM tasks WHERE user_id=? AND done=1 AND done_day=? ORDER BY id", (uid, day))


def finish_task(uid, task_id, day):
    run("UPDATE tasks SET done=1, done_day=? WHERE id=? AND user_id=?", (day, task_id, uid))


def delete_task(uid, task_id):
    run("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, uid))


# ---------- focus ----------
def start_focus(uid, start, minutes, mode):
    return run("INSERT INTO focus(user_id,start_ts,end_ts,minutes,mode) VALUES(?,?,?,?,?)",
               (uid, start, start + minutes * 60, minutes, mode))


def running_focus(uid):
    return one("SELECT * FROM focus WHERE user_id=? AND status='running' ORDER BY id DESC LIMIT 1", (uid,))


def due_focus(now):
    return q("SELECT * FROM focus WHERE status='running' AND end_ts<=?", (now,))


def set_focus(fid, **kw):
    cols = ",".join(f"{k}=?" for k in kw)
    run(f"UPDATE focus SET {cols} WHERE id=?", (*kw.values(), fid))


def focus_between(uid, start_ts, end_ts):
    return q("SELECT * FROM focus WHERE user_id=? AND start_ts>=? AND start_ts<? AND status!='cancelled'",
             (uid, start_ts, end_ts))


# ---------- reviews ----------
def save_review(uid, day, **kw):
    run("INSERT OR IGNORE INTO reviews(user_id,day) VALUES(?,?)", (uid, day))
    cols = ",".join(f"{k}=?" for k in kw)
    run(f"UPDATE reviews SET {cols} WHERE user_id=? AND day=?", (*kw.values(), uid, day))


def review(uid, day):
    return one("SELECT * FROM reviews WHERE user_id=? AND day=?", (uid, day))


def recent_reviews(uid, since_day):
    return q("SELECT * FROM reviews WHERE user_id=? AND day>=? ORDER BY day", (uid, since_day))


# ---------- sent (дедуплікація нагадувань) ----------
def was_sent(uid, key) -> bool:
    return one("SELECT 1 FROM sent WHERE user_id=? AND key=?", (uid, key)) is not None


def mark_sent(uid, key):
    run("INSERT OR IGNORE INTO sent(user_id,key) VALUES(?,?)", (uid, key))
