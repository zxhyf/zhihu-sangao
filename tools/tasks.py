# -*- coding: utf-8 -*-
"""每日任务卡：把 7 日方案拆成今天可勾选的清单。"""
from __future__ import annotations

import json
from datetime import datetime

from config import DEFAULT_USER
from data import db


def ensure_today(user_id: str = DEFAULT_USER) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.query("SELECT * FROM tasks WHERE user_id=? AND day=? ORDER BY time_text", (user_id, today))
    if rows:
        return [dict(r) for r in rows]

    from tools import plan as plan_tool
    data = plan_tool.generate(user_id, days=1)
    items = data["days"][0]["items"] if data.get("days") else []
    for it in items:
        db.execute(
            """INSERT INTO tasks (user_id, day, slot, time_text, category, content, done, created_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (user_id, today, it["time"][:2], it["time"], it["category"],
             f"{it['title']}：{it['content']}" + (f"（{it.get('note')}）" if it.get("note") else ""),
             db.now_iso()),
        )
    rows = db.query("SELECT * FROM tasks WHERE user_id=? AND day=? ORDER BY time_text", (user_id, today))
    return [dict(r) for r in rows]


def toggle(user_id: str, task_id: int) -> dict:
    row = db.query_one("SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    if not row:
        return {"ok": False, "error": "任务不存在"}
    new_done = 0 if row["done"] else 1
    db.execute("UPDATE tasks SET done=? WHERE id=?", (new_done, task_id))
    return {"ok": True, "id": task_id, "done": new_done}


def stats_today(user_id: str = DEFAULT_USER) -> dict:
    rows = ensure_today(user_id)
    total = len(rows)
    done = len([r for r in rows if r["done"]])
    return {"total": total, "done": done, "rate": round(done / total * 100) if total else 0}
