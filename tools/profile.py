# -*- coding: utf-8 -*-
"""健康档案工具。"""
from __future__ import annotations

import json
from datetime import datetime

from config import DEFAULT_USER
from data import db

DEFAULT_PROFILE = {
    "name": "体验用户",
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


# ---------------------------------------------------------------- 字段校验
TIME_RE = None
ENUMS = {
    "sex": {"男", "女", "其他"},
    "budget": {"low", "normal", "high"},
    "taste": {"light", "normal", "salty", "spicy"},
}


def update_profile_checked(user_id: str, payload: dict) -> dict:
    """带校验的档案更新：拒绝不合理身高、出生年份、作息与超长文本（对应评审意见 P7）。"""
    import re
    errors: dict[str, str] = {}
    clean: dict = {}
    now_year = datetime.now().year

    def _num(key, lo, hi, label):
        if key not in payload or payload[key] in ("", None):
            return
        try:
            v = float(payload[key])
        except (TypeError, ValueError):
            errors[key] = f"{label}必须是数字"
            return
        if not (lo <= v <= hi):
            errors[key] = f"{label}应在 {lo:g}–{hi:g} 之间"
            return
        clean[key] = v

    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            errors["name"] = "称呼不能为空"
        elif len(name) > 20:
            errors["name"] = "称呼不超过 20 个字"
        else:
            clean["name"] = name

    if payload.get("birth_year") not in (None, ""):
        try:
            by = int(payload["birth_year"])
            if not (now_year - 110 <= by <= now_year - 10):
                errors["birth_year"] = f"出生年份应在 {now_year - 110}–{now_year - 10} 之间"
            else:
                clean["birth_year"] = by
        except (TypeError, ValueError):
            errors["birth_year"] = "出生年份必须是整数"

    _num("height_cm", 100, 220, "身高（cm）")
    _num("target_weight", 30, 200, "目标体重（kg）")

    for key, allowed in ENUMS.items():
        if key in payload and payload[key] not in (None, ""):
            if str(payload[key]) not in allowed:
                errors[key] = f"{key} 只能是 {'/'.join(sorted(allowed))}"
            else:
                clean[key] = str(payload[key])

    if "conditions" in payload:
        conds = payload.get("conditions") or []
        if isinstance(conds, str):
            conds = [c.strip() for c in conds.split(",") if c.strip()]
        conds = [str(c).strip()[:20] for c in conds][:8]
        if len(conds) > 8:
            errors["conditions"] = "共病最多填 8 项"
        clean["conditions"] = conds

    for key in ("wake_time", "sleep_time"):
        if payload.get(key):
            val = str(payload[key]).strip()
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", val):
                errors[key] = "时间格式应为 HH:MM（如 06:30）"
            else:
                clean[key] = val

    for key in ("can_cook", "family_support"):
        if payload.get(key) is not None:
            clean[key] = 1 if str(payload[key]) in ("1", "True", "true", "是") else 0

    if payload.get("allergies") is not None:
        clean["allergies"] = str(payload.get("allergies"))[:100]
    if payload.get("note") is not None:
        clean["note"] = str(payload.get("note"))[:200]

    if errors:
        return {"ok": False, "error": "；".join(errors.values()), "fields": errors}

    if not clean:
        return {"ok": False, "error": "没有可更新的字段"}

    return {"ok": True, "profile": update_profile(user_id, **clean), "updated": sorted(clean)}
