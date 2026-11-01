# -*- coding: utf-8 -*-
"""共病药物联动检查（本项目核心创新点之一）。

读取 knowledge/med_rules.json：药名/别名 → 药物档案；药物对 → 联动规则。
输出只提示“需要注意什么 / 需要监测什么 / 该向医生问什么”，不给剂量建议。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import KNOWLEDGE_DIR
from tools import medications
from config import DEFAULT_USER

RULES_FILE = KNOWLEDGE_DIR / "med_rules.json"
_cache: dict = {"mtime": 0.0, "data": None}


def load_rules() -> dict:
    try:
        st = RULES_FILE.stat()
    except FileNotFoundError:
        return {"drugs": [], "interactions": [], "meta": {}}
    if _cache["data"] is None or _cache["mtime"] != st.st_mtime:
        _cache["data"] = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        _cache["mtime"] = st.st_mtime
    return _cache["data"]


def all_drugs() -> list[dict]:
    return load_rules().get("drugs", [])


def resolve(token: str) -> dict | None:
    token = (token or "").strip()
    if not token:
        return None
    for d in all_drugs():
        if token == d["name"] or token in (d.get("aliases") or []):
            return d
    for d in all_drugs():
        if token in d["name"] or any(token in a for a in (d.get("aliases") or [])):
            return d
    return None


def infer_from_text(text: str) -> list[dict]:
    """从自由文本中识别药物（名称或别名），返回去重后的药物档案列表。"""
    found: list[dict] = []
    seen = set()
    for d in all_drugs():
        keys = [d["name"]] + list(d.get("aliases") or [])
        if any(k and k in text for k in keys):
            if d["id"] not in seen:
                seen.add(d["id"])
                found.append(d)
    return found


def check(drug_names: list[str] | None = None, text: str = "",
          user_id: str = DEFAULT_USER, include_current: bool = True) -> dict:
    """检查药物组合。drug_names 为空时，自动使用当前用药计划。"""
    drugs: list[dict] = []
    ids = set()

    for name in (drug_names or []):
        d = resolve(name)
        if d and d["id"] not in ids:
            ids.add(d["id"])
            drugs.append(d)

    if text:
        for d in infer_from_text(text):
            if d["id"] not in ids:
                ids.add(d["id"])
                drugs.append(d)

    current_names = []
    if include_current:
        for m in medications.list_meds(user_id):
            current_names.append(m["name"])
            d = resolve(m["name"])
            if d and d["id"] not in ids:
                ids.add(d["id"])
                drugs.append(d)

    rules = load_rules().get("interactions", [])
    pairs: list[dict] = []
    for d in drugs:
        for rule in rules:
            a, b = rule["a"], rule["b"]
            if d["id"] == a:
                other = resolve_by_id(b)
            elif d["id"] == b:
                other = resolve_by_id(a)
            else:
                continue
            if other and other["id"] in ids:
                key = tuple(sorted([d["id"], other["id"]]))
                if not any(tuple(sorted([x["drug_a_id"], x["drug_b_id"]])) == key for x in pairs):
                    pairs.append({
                        "drug_a": d["name"], "drug_a_id": d["id"],
                        "drug_b": other["name"], "drug_b_id": other["id"],
                        "level": rule.get("level", "caution"),
                        "title": rule["title"],
                        "detail": rule["detail"],
                        "action": rule.get("action", ""),
                        "source": rule.get("source", ""),
                    })
    # 去重（同一对药物只保留一条）
    seen = set()
    uniq = []
    for p in pairs:
        k = tuple(sorted([p["drug_a_id"], p["drug_b_id"]]))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    order = {"high": 0, "caution": 1, "info": 2}
    uniq.sort(key=lambda x: order.get(x["level"], 3))

    notes = []
    for d in drugs:
        notes.append({
            "name": d["name"],
            "class": d["class"],
            "effects": d.get("effects", []),
            "watch": d.get("watch", []),
            "monitor": d.get("monitor", ""),
            "source": d.get("source", ""),
        })

    high = [p for p in uniq if p["level"] == "high"]
    summary = (
        f"已在你的药物清单中识别到 {len(drugs)} 种药物，匹配到 {len(uniq)} 条需要关注的联动规则"
        + (f"，其中 {len(high)} 条属于高风险（建议尽快与医生核对）。" if high else "。")
    ) if drugs else "没有识别到具体药物。可以说出药名（例如“我在吃氨氯地平、二甲双胍”）。"

    return {
        "ok": True,
        "drugs": drugs,
        "drug_names": [d["name"] for d in drugs],
        "current_meds": current_names,
        "interactions": uniq,
        "notes": notes,
        "summary": summary,
        "disclaimer": "以上为知识库规则提示，不构成用药建议；能否同时服用必须由医生或药师判断。",
    }


def resolve_by_id(drug_id: str) -> dict | None:
    for d in all_drugs():
        if d["id"] == drug_id:
            return d
    return None


def stats() -> dict:
    data = load_rules()
    return {
        "drug_count": len(data.get("drugs", [])),
        "rule_count": len(data.get("interactions", [])),
        "version": data.get("meta", {}).get("version", ""),
        "basis": data.get("meta", {}).get("basis", []),
    }
