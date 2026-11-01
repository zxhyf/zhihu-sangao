# -*- coding: utf-8 -*-
"""用药计划与打卡。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from config import DEFAULT_USER
from data import db


def add_med(user_id: str, name: str, dose: str = "", frequency: str = "每日 1 次",
            times: list[str] | None = None, purpose: str = "") -> dict:
    existing = db.query_one(
        "SELECT * FROM medications WHERE user_id=? AND name=? AND active=1", (user_id, name))
    times_json = json.dumps(times or ["08:00"], ensure_ascii=False)
    if existing:
        db.execute("UPDATE medications SET dose=?, frequency=?, times=?, purpose=? WHERE id=?",
                   (dose, frequency, times_json, purpose, existing["id"]))
        mid = existing["id"]
    else:
        mid = db.execute(
            """INSERT INTO medications (user_id, name, dose, frequency, times, purpose, active, created_at)
               VALUES (?,?,?,?,?,?,1,?)""",
            (user_id, name, dose, frequency, times_json, purpose, db.now_iso()),
        )
    return {"ok": True, "id": mid, "name": name, "dose": dose, "frequency": frequency,
            "times": times or ["08:00"], "purpose": purpose}


def list_meds(user_id: str = DEFAULT_USER) -> list[dict]:
    rows = db.query("SELECT * FROM medications WHERE user_id=? AND active=1 ORDER BY id", (user_id,))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["times"] = json.loads(d.get("times") or "[]")
        except Exception:
            d["times"] = []
        out.append(d)
    return out


def stop_med(user_id: str, name: str) -> bool:
    row = db.query_one("SELECT id FROM medications WHERE user_id=? AND name=?", (user_id, name))
    if not row:
        return False
    db.execute("UPDATE medications SET active=0 WHERE id=?", (row["id"],))
    return True


def log_dose(user_id: str, med_name: str, status: str = "taken", note: str = "",
             taken_at: str | None = None) -> dict:
    row = db.query_one("SELECT id FROM medications WHERE user_id=? AND name=?",
                       (user_id, med_name))
    ts = taken_at or db.now_iso()
    db.execute(
        "INSERT INTO med_logs (user_id, med_id, med_name, status, taken_at, note) VALUES (?,?,?,?,?,?)",
        (user_id, row["id"] if row else None, med_name, status, ts, note),
    )
    return {"ok": True, "med_name": med_name, "status": status, "taken_at": ts}


def logs(user_id: str = DEFAULT_USER, days: int = 14) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.query(
        "SELECT * FROM med_logs WHERE user_id=? AND taken_at>=? ORDER BY taken_at DESC",
        (user_id, since))
    return [dict(r) for r in rows]


def adherence(user_id: str = DEFAULT_USER, days: int = 7) -> dict:
    """依从性统计：以“应服次数”为分母（每日次数 × 天数）。"""
    meds = list_meds(user_id)
    expect_per_day = 0
    for m in meds:
        n = len(m.get("times") or []) or 1
        expect_per_day += n
    expected = expect_per_day * days
    rows = logs(user_id, days)
    taken = len([r for r in rows if r.get("status") == "taken"])
    rate = round(taken / expected * 100, 0) if expected else 0
    by_med: dict = {}
    for m in meds:
        cnt = len([r for r in rows if r.get("med_name") == m["name"] and r.get("status") == "taken"])
        exp = (len(m.get("times") or []) or 1) * days
        by_med[m["name"]] = {"taken": cnt, "expected": exp,
                             "rate": round(cnt / exp * 100) if exp else 0}
    return {"days": days, "expected": expected, "taken": taken, "rate": rate,
            "med_count": len(meds), "by_med": by_med}


def today_schedule(user_id: str = DEFAULT_USER) -> list[dict]:
    items = []
    for m in list_meds(user_id):
        for t in m.get("times") or ["08:00"]:
            items.append({"time": t, "category": "med", "content": f"{m['name']} {m['dose']}".strip(),
                          "med_name": m["name"]})
    today = datetime.now().strftime("%Y-%m-%d")
    done = {r["med_name"] for r in db.query(
        "SELECT med_name FROM med_logs WHERE user_id=? AND taken_at LIKE ? AND status='taken'",
        (user_id, today + "%"))}
    for it in items:
        it["done"] = it["med_name"] in done
    items.sort(key=lambda x: x["time"])
    return items
