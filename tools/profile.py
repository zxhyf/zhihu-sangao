# -*- coding: utf-8 -*-
"""健康档案工具。"""
from __future__ import annotations

import json
from datetime import datetime

from config import DEFAULT_USER
from data import db

DEFAULT_PROFILE = {
    "name": "演示用户",
    "birth_year": 1962,
    "sex": "男",
    "height_cm": 170.0,
    "target_weight": 68.0,
    "conditions": ["高血压", "2型糖尿病", "血脂异常"],
    "allergies": "",
    "can_cook": 1,
    "budget": "normal",
    "taste": "normal",
    "wake_time": "06:30",
    "sleep_time": "22:30",
    "family_support": 1,
    "note": "演示数据，可在界面中清除后录入真实数据",
}


def ensure_profile(user_id: str = DEFAULT_USER) -> dict:
    row = db.query_one("SELECT * FROM profile WHERE user_id = ?", (user_id,))
    if row is None:
        cond = json.dumps(DEFAULT_PROFILE["conditions"], ensure_ascii=False)
        db.execute(
            """INSERT INTO profile (user_id, name, birth_year, sex, height_cm, target_weight,
                   conditions, allergies, can_cook, budget, taste, wake_time, sleep_time,
                   family_support, note, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, DEFAULT_PROFILE["name"], DEFAULT_PROFILE["birth_year"], DEFAULT_PROFILE["sex"],
             DEFAULT_PROFILE["height_cm"], DEFAULT_PROFILE["target_weight"], cond,
             DEFAULT_PROFILE["allergies"], DEFAULT_PROFILE["can_cook"], DEFAULT_PROFILE["budget"],
             DEFAULT_PROFILE["taste"], DEFAULT_PROFILE["wake_time"], DEFAULT_PROFILE["sleep_time"],
             DEFAULT_PROFILE["family_support"], DEFAULT_PROFILE["note"], db.now_iso()),
        )
        row = db.query_one("SELECT * FROM profile WHERE user_id = ?", (user_id,))
    return _decorate(dict(row), user_id)


def _decorate(p: dict, user_id: str) -> dict:
    try:
        p["conditions"] = json.loads(p.get("conditions") or "[]")
    except Exception:
        p["conditions"] = []
    p["age"] = (datetime.now().year - int(p["birth_year"])) if p.get("birth_year") else None
    last_w = db.query_one(
        "SELECT val1, measured_at FROM measurements WHERE user_id=? AND kind='weight' ORDER BY measured_at DESC LIMIT 1",
        (user_id,),
    )
    weight = last_w["val1"] if last_w else None
    p["weight"] = weight
    if weight and p.get("height_cm"):
        p["bmi"] = round(weight / ((p["height_cm"] / 100) ** 2), 1)
    else:
        p["bmi"] = None
    p["user_id"] = user_id
    return p


def get_profile(user_id: str = DEFAULT_USER) -> dict:
    return ensure_profile(user_id)


def update_profile(user_id: str, **fields) -> dict:
    ensure_profile(user_id)
    allowed = {"name", "birth_year", "sex", "height_cm", "target_weight", "conditions",
               "allergies", "can_cook", "budget", "taste", "wake_time", "sleep_time",
               "family_support", "note"}
    sets, params = [], []
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        if key == "conditions" and isinstance(val, (list, tuple)):
            val = json.dumps(list(val), ensure_ascii=False)
        sets.append(f"{key} = ?")
        params.append(val)
    if sets:
        params.append(db.now_iso())
        params.append(user_id)
        db.execute(f"UPDATE profile SET {', '.join(sets)}, updated_at = ? WHERE user_id = ?", params)
    return get_profile(user_id)


def add_condition(user_id: str, cond: str) -> dict:
    p = get_profile(user_id)
    conds = [c for c in p["conditions"] if c]
    if cond not in conds:
        conds.append(cond)
    return update_profile(user_id, conditions=conds)
