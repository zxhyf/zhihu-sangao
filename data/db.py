# -*- coding: utf-8 -*-
"""SQLite 数据层：连接管理、建表、通用查询封装。

所有健康数据落在本地 data/health.db，不上传任何服务器。
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from config import DB_PATH, DATA_DIR

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    user_id      TEXT PRIMARY KEY,
    name         TEXT,
    birth_year   INTEGER,
    sex          TEXT,
    height_cm    REAL,
    target_weight REAL,
    conditions   TEXT,          -- JSON 数组：高血压/糖尿病/血脂异常/高尿酸...
    allergies    TEXT,
    can_cook     INTEGER DEFAULT 1,
    budget       TEXT DEFAULT 'normal',   -- low / normal / high
    taste        TEXT DEFAULT 'normal',   -- light / normal / salty / spicy
    wake_time    TEXT DEFAULT '06:30',
    sleep_time   TEXT DEFAULT '22:30',
    family_support INTEGER DEFAULT 0,
    note         TEXT,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,   -- bp / glucose / lipid / weight / waist / hba1c
    sub_kind    TEXT,            -- fasting / postprandial / random / tc / tg / ldl / hdl
    val1        REAL NOT NULL,
    val2        REAL,
    unit        TEXT,
    measured_at TEXT NOT NULL,   -- ISO 本地时间
    source      TEXT DEFAULT 'chat',  -- chat / manual / ocr / device
    note        TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_meas_user_kind ON measurements(user_id, kind, measured_at);

CREATE TABLE IF NOT EXISTS medications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    dose        TEXT,
    frequency   TEXT,            -- 每日1次/每日2次...
    times       TEXT,            -- JSON 数组 ["08:00"]
    purpose     TEXT,
    prescriber  TEXT,
    active      INTEGER DEFAULT 1,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS med_logs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   TEXT NOT NULL,
    med_id    INTEGER,
    med_name  TEXT,
    status    TEXT,              -- taken / skipped / missed
    taken_at  TEXT,
    note      TEXT,
    slot      TEXT,              -- 计划时段，如 08:00
    day       TEXT               -- YYYY-MM-DD，便于按日去重
);
-- 唯一索引在 _migrate() 中创建：旧库需要先补列，再建索引

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    day        TEXT,             -- YYYY-MM-DD
    slot       TEXT,             -- morning / noon / evening / night
    time_text  TEXT,
    category   TEXT,             -- meal / exercise / med / measure / education
    content    TEXT,
    done       INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,    -- user / assistant
    content    TEXT,
    blocks     TEXT,             -- JSON
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS risk_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    level      TEXT,
    title      TEXT,
    detail     TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS kb_files (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT UNIQUE,
    size       INTEGER,
    chunks     INTEGER,
    added_at   TEXT,
    note       TEXT
);
"""


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _LOCK:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA)
            _migrate(conn)
            conn.commit()
        finally:
            conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """就地升级旧库：给 med_logs 补 slot / day 列与唯一索引（不丢历史数据）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(med_logs)")}
    if "slot" not in cols:
        conn.execute("ALTER TABLE med_logs ADD COLUMN slot TEXT")
    if "day" not in cols:
        conn.execute("ALTER TABLE med_logs ADD COLUMN day TEXT")
    conn.execute("UPDATE med_logs SET day = substr(taken_at, 1, 10) WHERE day IS NULL AND taken_at IS NOT NULL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_med_log_slot ON med_logs(user_id, med_name, day, slot)")


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with _LOCK:
        conn = get_conn()
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()


def query_one(sql: str, params: Iterable[Any] = ()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """执行写入语句，返回 lastrowid。"""
    with _LOCK:
        conn = get_conn()
        try:
            cur = conn.execute(sql, tuple(params))
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()


def reset_user_data(user_id: str) -> None:
    with _LOCK:
        for table in ("measurements", "medications", "med_logs", "tasks", "chat_messages", "risk_events"):
            execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))


def purge_inactive_demo_users(hours: int = 48) -> int:
    """清理超过 N 小时没有活动的演示用户，避免评委体验模式的数据库无限膨胀。"""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    last: dict[str, str] = {}
    for table, col in (("measurements", "created_at"), ("chat_messages", "created_at"),
                       ("med_logs", "taken_at"), ("tasks", "created_at")):
        try:
            rows = query(
                f"SELECT user_id, MAX(COALESCE({col}, '')) AS t FROM {table} "
                "WHERE user_id LIKE 'u_demo_%' GROUP BY user_id")
        except Exception:
            continue
        for r in rows:
            last[r["user_id"]] = max(last.get(r["user_id"], ""), r["t"] or "")
    stale = [uid for uid, t in last.items() if (t or "") < cutoff]
    for uid in stale:
        reset_user_data(uid)
        execute("DELETE FROM profile WHERE user_id = ?", (uid,))
    return len(stale)


def demo_user_count() -> int:
    row = query_one(
        "SELECT COUNT(DISTINCT user_id) AS c FROM measurements WHERE user_id LIKE 'u_demo_%'")
    return int(row["c"]) if row else 0


def db_path() -> Path:
    return DB_PATH
