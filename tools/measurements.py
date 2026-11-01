# -*- coding: utf-8 -*-
"""测量数据工具：校验、入库、查询、快照。

所有数值在入库前必须通过与生理边界比对，越界数据一律拒绝入库并提示，
避免“小数点打错”污染整条趋势。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from config import DEFAULT_USER
from data import db
from tools import risks

# 生理边界：(最小值, 最大值)
BOUNDS = {
    ("bp", None): ((60, 260), (30, 160)),
    ("glucose", None): ((1.0, 35.0), None),
    ("hba1c", None): ((3.0, 20.0), None),
    ("lipid", "tc"): ((1.0, 20.0), None),
    ("lipid", "tg"): ((0.2, 30.0), None),
    ("lipid", "ldl"): ((0.3, 15.0), None),
    ("lipid", "hdl"): ((0.2, 6.0), None),
    ("weight", None): ((20.0, 250.0), None),
    ("waist", None): ((40.0, 200.0), None),
}


def validate(kind: str, sub: str | None, val1: float, val2: float | None) -> tuple[bool, str]:
    key = (kind, sub) if (kind, sub) in BOUNDS else (kind, None)
    if key not in BOUNDS:
        return False, f"暂不支持记录该指标：{kind}"
    b = BOUNDS[key]
    lo, hi = b[0]
    if not (lo <= val1 <= hi):
        return False, f"数值 {val1} 超出可记录范围（{lo}–{hi}），请检查是否输错单位或小数点"
    if b[1] is not None:
        if val2 is None:
            return False, "血压需要同时提供收缩压和舒张压"
        lo2, hi2 = b[1]
        if not (lo2 <= val2 <= hi2):
            return False, f"舒张压 {val2} 超出可记录范围（{lo2}–{hi2}）"
        if val1 <= val2:
            return False, "收缩压应高于舒张压，请检查输入顺序（例如 135/85）"
    return True, ""


def record(user_id: str, kind: str, sub_kind: str | None, val1: float,
           val2: float | None = None, unit: str | None = None,
           measured_at: str | None = None, source: str = "chat", note: str = "") -> dict:
    ok, msg = validate(kind, sub_kind, val1, val2)
    if not ok:
        return {"ok": False, "error": msg}

    if not measured_at:
        measured_at = db.now_iso()
    mid = db.execute(
        """INSERT INTO measurements (user_id, kind, sub_kind, val1, val2, unit, measured_at, source, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (user_id, kind, sub_kind, val1, val2, unit, measured_at, source, note, db.now_iso()),
    )
    from tools import profile as profile_tool
    p = profile_tool.get_profile(user_id)
    risk = risks.classify(kind, sub_kind, val1, val2, p)
    if risk["level"] in ("danger", "emergency"):
        db.execute(
            "INSERT INTO risk_events (user_id, level, title, detail, created_at) VALUES (?,?,?,?,?)",
            (user_id, risk["level"], f"{risks.KIND_LABEL.get(kind, kind)} {risks.fmt_value(kind, sub_kind, val1, val2)}",
             risk.get("detail", ""), db.now_iso()),
        )
    return {
        "ok": True,
        "id": mid,
        "kind": kind,
        "sub_kind": sub_kind,
        "val1": val1,
        "val2": val2,
        "unit": unit,
        "measured_at": measured_at,
        "label": risks.KIND_LABEL.get(kind, kind),
        "value_text": risks.fmt_value(kind, sub_kind, val1, val2, unit),
        "risk": risk,
    }


def list_measurements(user_id: str = DEFAULT_USER, kind: str | None = None,
                      sub_kind: str | None = None, days: int | None = None,
                      limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM measurements WHERE user_id = ?"
    params: list = [user_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if sub_kind:
        sql += " AND (sub_kind = ? OR sub_kind IS NULL)"
        params.append(sub_kind)
    if days:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " AND measured_at >= ?"
        params.append(since)
    sql += " ORDER BY measured_at ASC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.query(sql, params)]


def latest(user_id: str = DEFAULT_USER, kind: str = "bp", sub_kind: str | None = None) -> dict | None:
    rows = list_measurements(user_id, kind, sub_kind, limit=500)
    return rows[-1] if rows else None


def count(user_id: str = DEFAULT_USER, days: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS c FROM measurements WHERE user_id = ?"
    params: list = [user_id]
    if days:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " AND measured_at >= ?"
        params.append(since)
    row = db.query_one(sql, params)
    return int(row["c"]) if row else 0


def snapshot(user_id: str = DEFAULT_USER) -> dict:
    """仪表盘用的三高快照。"""
    from tools import profile as profile_tool
    p = profile_tool.get_profile(user_id)
    out: dict = {"profile": p, "items": []}

    bp = latest(user_id, "bp")
    if bp:
        out["items"].append({
            "kind": "bp", "label": "血压",
            "value": risks.fmt_value("bp", None, bp["val1"], bp["val2"]),
            "at": bp["measured_at"],
            "risk": risks.classify("bp", None, bp["val1"], bp["val2"], p),
        })
    for sub, label in (("fasting", "空腹血糖"), ("postprandial", "餐后血糖")):
        g = latest(user_id, "glucose", sub)
        if g:
            out["items"].append({
                "kind": "glucose", "sub": sub, "label": label,
                "value": risks.fmt_value("glucose", sub, g["val1"], None),
                "at": g["measured_at"],
                "risk": risks.classify("glucose", sub, g["val1"], None, p),
            })
    for sub, label in (("ldl", "LDL-C"), ("tg", "甘油三酯"), ("tc", "总胆固醇"), ("hdl", "HDL-C")):
        row = latest(user_id, "lipid", sub)
        if row:
            out["items"].append({
                "kind": "lipid", "sub": sub, "label": label,
                "value": risks.fmt_value("lipid", sub, row["val1"], None),
                "at": row["measured_at"],
                "risk": risks.classify("lipid", sub, row["val1"], None, p),
            })
    w = latest(user_id, "weight")
    if w:
        out["items"].append({
            "kind": "weight", "label": "体重",
            "value": risks.fmt_value("weight", None, w["val1"], None),
            "at": w["measured_at"],
            "risk": risks.classify("weight", None, w["val1"], None, p),
        })
    h = latest(user_id, "hba1c")
    if h:
        out["items"].append({
            "kind": "hba1c", "label": "糖化血红蛋白",
            "value": risks.fmt_value("hba1c", None, h["val1"], None),
            "at": h["measured_at"],
            "risk": risks.classify("hba1c", None, h["val1"], None, p),
        })
    if p.get("bmi"):
        out["bmi"] = p["bmi"]
    return out


def clear(user_id: str = DEFAULT_USER) -> None:
    db.reset_user_data(user_id)


def clear_demo(user_id: str = DEFAULT_USER) -> int:
    """只清除演示数据（source='demo'），保留用户自己录入的记录。"""
    demo_ids = [r["id"] for r in db.query(
        "SELECT id FROM measurements WHERE user_id=? AND source='demo'", (user_id,))]
    for mid in demo_ids:
        db.execute("DELETE FROM measurements WHERE id=?", (mid,))
    return len(demo_ids)


def seed_demo(user_id: str = DEFAULT_USER) -> int:
    """写入一组演示数据，覆盖近 30 天，便于展示趋势图。

    幂等：该用户已有演示数据时直接返回 0，避免重复点击「演示数据」把曲线堆成两层。
    """
    existing = db.query_one(
        "SELECT id FROM measurements WHERE user_id=? AND source='demo' LIMIT 1", (user_id,))
    if existing:
        return 0

    now = datetime.now()
    rows: list[tuple] = []
    plan = []

    # 30 天，每 2 天一次血压，缓慢下降并带波动
    sys_seq = [158, 152, 155, 148, 146, 150, 143, 141, 145, 138,
               140, 136, 142, 135, 133, 137, 132, 134, 129, 131,
               128, 130, 126, 129, 124, 127, 123, 125, 121, 122]
    dia_seq = [96, 94, 95, 92, 90, 93, 89, 88, 90, 86,
               87, 85, 88, 84, 83, 86, 82, 84, 80, 82,
               79, 81, 78, 80, 77, 79, 76, 78, 75, 76]
    for i in range(30):
        day = now - timedelta(days=29 - i)
        plan.append((day.replace(hour=7, minute=10, second=0, microsecond=0), "bp",
                     sys_seq[i], dia_seq[i], None))
        if i % 5 == 4:
            plan.append((day.replace(hour=21, minute=30, second=0, microsecond=0), "bp",
                         sys_seq[i] + 5, dia_seq[i] + 3, None))

    gluc = [8.4, 7.9, 8.1, 7.6, 7.8, 7.4, 7.6, 7.2, 7.5, 7.1,
            7.3, 7.0, 7.2, 6.9, 7.1, 6.8, 7.0, 6.7, 6.9, 6.6,
            6.8, 6.5, 6.7, 6.4, 6.6, 6.3, 6.5, 6.4, 6.2, 6.3]
    for i in range(0, 30, 2):
        day = now - timedelta(days=29 - i)
        plan.append((day.replace(hour=7, minute=0, second=0, microsecond=0), "glucose",
                     gluc[i], None, "fasting"))
        if i % 6 == 0:
            plan.append((day.replace(hour=13, minute=30, second=0, microsecond=0), "glucose",
                         round(gluc[i] + 3.1, 1), None, "postprandial"))

    plan.append(((now - timedelta(days=88)).replace(hour=9, minute=0), "lipid", 6.2, None, "tc"))
    plan.append(((now - timedelta(days=88)).replace(hour=9, minute=0), "lipid", 2.4, None, "tg"))
    plan.append(((now - timedelta(days=88)).replace(hour=9, minute=0), "lipid", 3.9, None, "ldl"))
    plan.append(((now - timedelta(days=88)).replace(hour=9, minute=0), "lipid", 1.0, None, "hdl"))
    plan.append(((now - timedelta(days=18)).replace(hour=9, minute=0), "lipid", 5.4, None, "tc"))
    plan.append(((now - timedelta(days=18)).replace(hour=9, minute=0), "lipid", 2.0, None, "tg"))
    plan.append(((now - timedelta(days=18)).replace(hour=9, minute=0), "lipid", 3.3, None, "ldl"))
    plan.append(((now - timedelta(days=18)).replace(hour=9, minute=0), "lipid", 1.1, None, "hdl"))
    plan.append(((now - timedelta(days=45)).replace(hour=7, minute=30), "hba1c", 7.8, None, None))
    plan.append(((now - timedelta(days=5)).replace(hour=7, minute=30), "hba1c", 7.0, None, None))

    for i in range(0, 30, 7):
        day = now - timedelta(days=29 - i)
        plan.append((day.replace(hour=6, minute=40, second=0, microsecond=0), "weight",
                     73.5 - i * 0.12, None, None))

    for dt, kind, v1, v2, sub in plan:
        rows.append((user_id, kind, sub, round(float(v1), 1), None if v2 is None else round(float(v2), 1),
                     "mmHg" if kind == "bp" else ("%" if kind == "hba1c" else ("kg" if kind == "weight" else "mmol/L")),
                     dt.strftime("%Y-%m-%d %H:%M:%S"), "demo", "", db.now_iso()))

    conn = db.get_conn()
    try:
        conn.executemany(
            """INSERT INTO measurements (user_id, kind, sub_kind, val1, val2, unit, measured_at, source, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    # 演示用药
    from tools import medications
    if not medications.list_meds(user_id):
        medications.add_med(user_id, "氨氯地平", "5 mg", "每日 1 次", ["08:00"], "降压")
        medications.add_med(user_id, "二甲双胍", "0.5 g", "每日 2 次", ["08:00", "18:00"], "降糖")
        medications.add_med(user_id, "阿托伐他汀", "20 mg", "每晚 1 次", ["21:00"], "降脂")
    return len(rows)
