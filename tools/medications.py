# -*- coding: utf-8 -*-
"""用药计划与打卡。

三条硬规则（对应评审意见 P3 / P4）：
1. 打卡按「药物 + 日期 + 计划时段」唯一，重复点击不会重复计数；
2. 不在当前用药清单里的药，不允许打卡（临时用药请先登记）；
3. 依从率做边界保护，永远不会超过 100%。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from config import DEFAULT_USER
from data import db


def add_med(user_id: str, name: str, dose: str = "", frequency: str = "每日 1 次",
            times: list[str] | None = None, purpose: str = "") -> dict:
    name = (name or "").strip()[:40]
    if not name:
        return {"ok": False, "error": "药名不能为空"}
    times = [t for t in (times or ["08:00"]) if t][:8] or ["08:00"]
    existing = db.query_one(
        "SELECT * FROM medications WHERE user_id=? AND name=? AND active=1", (user_id, name))
    times_json = json.dumps(times, ensure_ascii=False)
    if existing:
        # 只改时间时不要把已有剂量清空
        dose = (dose or "").strip() or (existing["dose"] or "")
        db.execute("UPDATE medications SET dose=?, frequency=?, times=?, purpose=? WHERE id=?",
                   (dose[:40], frequency[:20], times_json, purpose[:60], existing["id"]))
        mid = existing["id"]
    else:
        mid = db.execute(
            """INSERT INTO medications (user_id, name, dose, frequency, times, purpose, active, created_at)
               VALUES (?,?,?,?,?,?,1,?)""",
            (user_id, name, (dose or "").strip()[:40], frequency[:20], times_json, purpose[:60], db.now_iso()),
        )
    return {"ok": True, "id": mid, "name": name, "dose": dose, "frequency": frequency,
            "times": times, "purpose": purpose}


def list_meds(user_id: str = DEFAULT_USER) -> list[dict]:
    rows = db.query("SELECT * FROM medications WHERE user_id=? AND active=1 ORDER BY id", (user_id,))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["times"] = json.loads(d.get("times") or "[]")
        except Exception:
            d["times"] = []
        if not d["times"]:
            d["times"] = ["08:00"]
        out.append(d)
    return out


def stop_med(user_id: str, name: str) -> bool:
    row = db.query_one("SELECT id FROM medications WHERE user_id=? AND name=?", (user_id, name))
    if not row:
        return False
    db.execute("UPDATE medications SET active=0 WHERE id=?", (row["id"],))
    return True


def _today_slots(user_id: str, med_name: str, day: str) -> set:
    rows = db.query(
        "SELECT slot FROM med_logs WHERE user_id=? AND med_name=? AND day=? AND status='taken'",
        (user_id, med_name, day))
    return {r["slot"] for r in rows if r["slot"]}


def log_dose(user_id: str, med_name: str, status: str = "taken", note: str = "",
             taken_at: str | None = None, slot: str | None = None) -> dict:
    med_name = (med_name or "").strip()
    med = db.query_one("SELECT * FROM medications WHERE user_id=? AND name=? AND active=1",
                       (user_id, med_name))
    if not med:
        return {
            "ok": False,
            "error": f"“{med_name}”不在当前用药清单中，不能打卡。请先在「用药清单」里登记（或说“我在吃 {med_name}”），再打卡。",
            "code": "unknown_med",
        }

    try:
        times = json.loads(med["times"] or "[]") or ["08:00"]
    except Exception:
        times = ["08:00"]

    ts = taken_at or db.now_iso()
    day = ts[:10]

    if status == "taken":
        if slot is None:
            taken = _today_slots(user_id, med_name, day)
            free = [t for t in times if t not in taken]
            if not free:
                return {
                    "ok": False,
                    "error": f"今天的“{med_name}”已经全部打卡（计划 {len(times)} 次），为避免重复计数，本次不计入。",
                    "code": "already_done",
                    "done_today": sorted(taken),
                }
            slot = free[0]
        elif slot not in times:
            return {"ok": False,
                    "error": f"“{med_name}”的计划时段是 {'/'.join(times)}，{slot} 不在计划内。",
                    "code": "bad_slot"}
    else:
        slot = slot or (times[0] if times else "08:00")

    # 指定时段重复打卡：幂等但不重复计数，并如实告知
    if status == "taken":
        exist = db.query_one(
            "SELECT id FROM med_logs WHERE user_id=? AND med_name=? AND day=? AND slot=? AND status='taken'",
            (user_id, med_name, day, slot))
        if exist:
            return {"ok": False, "code": "already_done",
                    "error": f"“{med_name}”{slot} 这个时段已经打过卡了，本次不计入。",
                    "slot": slot}

    db.execute(
        """INSERT INTO med_logs (user_id, med_id, med_name, status, taken_at, note, slot, day)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id, med_name, day, slot)
           DO UPDATE SET status=excluded.status, taken_at=excluded.taken_at, note=excluded.note""",
        (user_id, med["id"], med_name, status, ts, note[:80], slot, day),
    )
    return {"ok": True, "med_name": med_name, "status": status, "slot": slot,
            "taken_at": ts, "day": day,
            "remaining": len([t for t in times if t not in _today_slots(user_id, med_name, day)])}


def upsert_times(user_id: str, name: str, dose: str = "", times: list[str] | None = None,
                 op: str = "merge") -> dict:
    """统一入口：按「去重合并」或「整体替换」更新某个药的时段。

    - op="merge"（默认）：保留原有安排，只补充没有重复的时段
    - op="replace"：整体替换（用户在「改时段」里显式选择）
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "药名不能为空"}
    new_times = [t for t in (times or []) if t][:8]
    cur = db.query_one("SELECT * FROM medications WHERE user_id=? AND name=? AND active=1",
                       (user_id, name))
    try:
        prev = json.loads(cur["times"]) if cur else []
    except Exception:
        prev = []

    if op == "replace":
        final = sorted(dict.fromkeys(new_times))[:8] or ["08:00"]
    else:
        final = sorted(dict.fromkeys(list(prev) + new_times))[:8] or ["08:00"]

    added = [t for t in final if t not in prev]
    freq = f"每日 {len(final)} 次" if len(final) > 1 else "每日 1 次"
    add_med(user_id, name, dose, freq, final, "")

    if not cur:
        mode = "add"
        message = f"已添加「{name}」：{'、'.join(final)}"
    elif not added:
        mode = "none"
        message = f"「{name}」这些时段已经存在，未做修改"
    elif op == "replace":
        mode = "update"
        message = f"已把「{name}」的时段改为 {'、'.join(final)}"
    else:
        mode = "append"
        message = f"已为「{name}」追加 {'、'.join(added)}（原有 {'、'.join(prev)} 保留）"

    return {"ok": True, "name": name, "times": final, "added": added,
            "prev": prev, "mode": mode, "message": message}


def logs(user_id: str = DEFAULT_USER, days: int = 14) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.query(
        "SELECT * FROM med_logs WHERE user_id=? AND COALESCE(day, substr(taken_at,1,10)) >= ? "
        "ORDER BY taken_at DESC",
        (user_id, since))
    return [dict(r) for r in rows]


def adherence(user_id: str = DEFAULT_USER, days: int = 7) -> dict:
    """依从率：分子按「药名 + 日期 + 时段」去重，分母为计划次数，结果上限 100%。"""
    meds = list_meds(user_id)
    expect_per_day = sum(len(m.get("times") or ["08:00"]) for m in meds) or 0
    expected = expect_per_day * days

    rows = logs(user_id, days)
    taken_keys = {(r.get("med_name"), r.get("day") or (r.get("taken_at") or "")[:10], r.get("slot"))
                  for r in rows if r.get("status") == "taken"}
    taken = len(taken_keys)
    rate = round(min(100.0, taken / expected * 100)) if expected else 0

    by_med: dict = {}
    for m in meds:
        slots = m.get("times") or ["08:00"]
        exp = len(slots) * days
        cnt = len([k for k in taken_keys if k[0] == m["name"]])
        by_med[m["name"]] = {"taken": min(cnt, exp), "expected": exp,
                             "rate": round(min(100.0, cnt / exp * 100)) if exp else 0,
                             "slots": slots}
    return {"days": days, "expected": expected, "taken": taken, "rate": rate,
            "med_count": len(meds), "by_med": by_med}


def today_schedule(user_id: str = DEFAULT_USER) -> list[dict]:
    """今日服药时间表：每个时段一条，完成状态按「药名 + 时段」判断。"""
    items = []
    today = datetime.now().strftime("%Y-%m-%d")
    for m in list_meds(user_id):
        done = _today_slots(user_id, m["name"], today)
        for t in (m.get("times") or ["08:00"]):
            items.append({
                "time": t, "category": "med",
                "content": f"{m['name']} {m['dose']}".strip(),
                "med_name": m["name"], "slot": t, "done": t in done,
            })
    items.sort(key=lambda x: x["time"])
    return items
