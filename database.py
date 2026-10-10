import sqlite3
import time
from contextlib import contextmanager

import config


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    with conn() as c:
        try:
            c.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass  # some network filesystems don't support WAL
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                username TEXT, first_name TEXT,
                premium_until INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                joined INTEGER
            );
            CREATE TABLE IF NOT EXISTS files(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                workdir TEXT, entry TEXT,
                uploaded INTEGER,
                pid INTEGER,
                autostart INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_files_user ON files(user_id);
            """
        )


# ---------- users ----------
def upsert_user(uid, username, first_name):
    with conn() as c:
        c.execute(
            """INSERT INTO users(user_id, username, first_name, joined)
               VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name""",
            (uid, username, first_name, int(time.time())),
        )
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()


def _ensure_user(c, uid):
    c.execute(
        "INSERT OR IGNORE INTO users(user_id, joined) VALUES(?,?)",
        (uid, int(time.time())),
    )


def get_user(uid):
    with conn() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()


def is_premium(row):
    return bool(row) and (row["premium_until"] or 0) > time.time()


def add_premium(uid, days):
    with conn() as c:
        _ensure_user(c, uid)
        cur = c.execute("SELECT premium_until FROM users WHERE user_id=?", (uid,)).fetchone()
        base = max(int(time.time()), cur["premium_until"] or 0)
        until = base + days * 86400
        c.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, uid))
        return until


def remove_premium(uid):
    with conn() as c:
        c.execute("UPDATE users SET premium_until=0 WHERE user_id=?", (uid,))


def set_ban(uid, flag):
    with conn() as c:
        _ensure_user(c, uid)
        c.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if flag else 0, uid))


def all_user_ids():
    with conn() as c:
        return [r["user_id"] for r in c.execute("SELECT user_id FROM users WHERE banned=0")]


# ---------- files ----------
def count_user_files(uid):
    with conn() as c:
        return c.execute("SELECT COUNT(*) n FROM files WHERE user_id=?", (uid,)).fetchone()["n"]


def add_file(uid, name):
    with conn() as c:
        cur = c.execute(
            "INSERT INTO files(user_id, name, uploaded) VALUES(?,?,?)",
            (uid, name, int(time.time())),
        )
        return cur.lastrowid


def update_file(fid, workdir, entry):
    with conn() as c:
        c.execute("UPDATE files SET workdir=?, entry=? WHERE id=?", (workdir, entry, fid))


def get_file(fid):
    with conn() as c:
        return c.execute("SELECT * FROM files WHERE id=?", (fid,)).fetchone()


def list_files(uid):
    with conn() as c:
        return c.execute("SELECT * FROM files WHERE user_id=? ORDER BY id", (uid,)).fetchall()


def delete_file(fid):
    with conn() as c:
        c.execute("DELETE FROM files WHERE id=?", (fid,))


def set_state(fid, pid, autostart):
    with conn() as c:
        c.execute("UPDATE files SET pid=?, autostart=? WHERE id=?", (pid, autostart, fid))


def autostart_files():
    with conn() as c:
        return c.execute(
            "SELECT * FROM files WHERE autostart=1 AND workdir IS NOT NULL"
        ).fetchall()


def stats():
    with conn() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        prem = c.execute(
            "SELECT COUNT(*) n FROM users WHERE premium_until>?", (int(time.time()),)
        ).fetchone()["n"]
        files = c.execute("SELECT COUNT(*) n FROM files").fetchone()["n"]
        return users, prem, files
