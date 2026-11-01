# -*- coding: utf-8 -*-
"""检验单录入：把粘贴进来的化验单文本解析成结构化指标，逐项核对后再入库。

设计要点（对应方案「数据接入与结构化」与「OCR 暂存 + 人工确认」的思路）：
1. 解析结果只作为“候选”，不直接写库；
2. 每一项都显示原文行、识别到的数值、单位与风险等级，用户取消勾选即可丢弃；
3. 数值仍然走 measurements.record 的同一套生理边界校验，避免脏数据；
4. 来源标记为 lab / ocr，可回溯这条数据是怎么来的。
"""
from __future__ import annotations

import re
from datetime import datetime

from tools import measurements, risks

# (匹配用的别名正则, kind, sub, 展示名, 默认单位)
LAB_ITEMS = [
    (r"糖化血红蛋白|糖化|HbA1c|HBA1C", "hba1c", None, "糖化血红蛋白", "%"),
    (r"餐后2?\s*小时血糖|餐后血糖|2hPG|PBG", "glucose", "postprandial", "餐后 2 小时血糖", "mmol/L"),
    (r"空腹血糖|空腹葡萄糖|FPG|GLU|葡萄糖", "glucose", "fasting", "空腹血糖", "mmol/L"),
    (r"甘油三酯|三酰甘油|TG\b|TRIG", "lipid", "tg", "甘油三酯", "mmol/L"),
    (r"低密度脂蛋白|LDL", "lipid", "ldl", "低密度脂蛋白胆固醇", "mmol/L"),
    (r"高密度脂蛋白|HDL", "lipid", "hdl", "高密度脂蛋白胆固醇", "mmol/L"),
    (r"总胆固醇|胆固醇|TC\b|CHOL", "lipid", "tc", "总胆固醇", "mmol/L"),
    (r"随机血糖|即刻血糖|血糖", "glucose", "random", "随机血糖", "mmol/L"),
]

DATE_PAT = re.compile(r"(\d{4})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})")
NUM_PAT = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3})?)(?![\d.])")
TIME_PAT = re.compile(r"\b\d{1,2}:\d{2}\b")
RANGE_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~—]\s*(\d+(?:\.\d+)?)")
PAREN_PAT = re.compile(r"[（(][^）)]{0,24}[）)]")
ABBR_PAT = re.compile(r"\b(?:HBA1C|2HPG|LDL-?C|HDL-?C|TC|TG|GLU|FPG|PBG|CHOL)\b", re.I)


def _clean(line: str) -> str:
    """去掉括号里的英文缩写、常见英文代号与日期时间，避免把 HbA1c 的 1、餐后2小时的 2 当成数值。"""
    s = PAREN_PAT.sub(" ", line)
    s = ABBR_PAT.sub(" ", s)
    s = s.replace("餐后2小时", "餐后").replace("餐后两小时", "餐后").replace("餐后2h", "餐后")
    s = DATE_PAT.sub(" ", s)
    s = TIME_PAT.sub(" ", s)
    return s


def _segments(line: str) -> list[tuple[str, str, str, str, str]]:
    """把一行切成「标签 → 该标签对应的数字片段」，支持一行写多个指标。"""
    hits = []
    for alias, kind, sub, label, unit in LAB_ITEMS:
        for m in re.finditer(alias, line, re.I):
            hits.append((m.start(), m.end(), len(m.group(0)), kind, sub, label, unit))
    # 位置靠前优先；同位置时更长的标签优先（低密度脂蛋白胆固醇 > 胆固醇）
    hits.sort(key=lambda h: (h[0], -h[2]))
    kept = []
    last_end = -1
    for h in hits:
        if h[0] < last_end:
            continue
        kept.append(h)
        last_end = h[1]
    out = []
    for i, h in enumerate(kept):
        end = kept[i + 1][0] if i + 1 < len(kept) else len(line)
        out.append((h[3], h[4], h[5], h[6], line[h[1]:end]))
    return out


def parse_text(text: str) -> dict:
    text = (text or "").strip()
    result = {"ok": False, "items": [], "unmatched": [], "measured_at": "", "date_text": "", "error": ""}
    if not text:
        result["error"] = "请把检验单内容粘贴进来"
        return result

    # 检验日期
    m = DATE_PAT.search(text)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 9, 0)
            result["measured_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            result["date_text"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    if not result["measured_at"]:
        result["measured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result["date_text"] = "未识别到报告日期，按今天记录"

    seen = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 120:
            continue
        # 一行可能写多个指标，按标签切成片段，各取自己那一段里的数字
        for kind, sub, label, unit, seg in _segments(line):
            key = (kind, sub)
            if key in seen:
                continue
            num_src = _clean(seg)
            m_num = NUM_PAT.search(num_src)
            if not m_num:
                # 数值写在标签前面（如「6.8 mmol/L 空腹血糖」）时退回整行
                num_src = _clean(line)
                m_num = NUM_PAT.search(num_src)
            if not m_num:
                continue
            try:
                value = float(m_num.group(1))
            except ValueError:
                continue
            ok, msg = measurements.validate(kind, sub, value, None)
            if not ok:
                # 数值不合理（可能是别的项目或小数点点错），跳过并记录
                result["unmatched"].append(f"{label}：{line[:40]}（{msg}）")
                seen.add(key)
                continue
            unit_found = re.search(r"(mmol\s*/\s*l|mg\s*/\s*dl|%)", num_src, re.I)
            if unit_found:
                unit = unit_found.group(1).replace(" ", "")
                if unit.lower() == "mg/dl":
                    unit = "mg/dL"
            ref = RANGE_PAT.search(num_src)
            risk = risks.classify(kind, sub, value, None, {})
            result["items"].append({
                "kind": kind,
                "sub": sub,
                "label": label,
                "value": value,
                "unit": unit,
                "line": line[:80],
                "ref": f"{ref.group(1)}–{ref.group(2)}" if ref else "",
                "risk": risk,
                "checked": True,
            })
            seen.add(key)

    if not result["items"]:
        result["error"] = ("没有识别到可入库的指标。支持：空腹/餐后血糖、糖化血红蛋白、"
                           "总胆固醇、甘油三酯、低密度/高密度脂蛋白。")
        return result

    result["ok"] = True
    result["summary"] = f"识别到 {len(result['items'])} 项指标（{result['date_text']}），请核对后确认入库。"
    return result


def commit(user_id: str, items: list[dict], measured_at: str = "", source: str = "lab") -> dict:
    saved, failed = [], []
    for it in items:
        if not it.get("checked", True):
            continue
        try:
            value = float(it["value"])
        except (KeyError, TypeError, ValueError):
            failed.append({"label": it.get("label"), "error": "数值无效"})
            continue
        res = measurements.record(
            user_id, it["kind"], it.get("sub"), value, None, it.get("unit"),
            measured_at or None, source, note=(it.get("line") or "")[:80],
        )
        if res.get("ok"):
            saved.append(res)
        else:
            failed.append({"label": it.get("label"), "error": res.get("error")})
    return {
        "ok": bool(saved),
        "saved": saved,
        "failed": failed,
        "count": len(saved),
        "message": f"已入库 {len(saved)} 项" + (f"，{len(failed)} 项失败" if failed else ""),
    }


SAMPLE = """2026-10-30  市第一医院  生化检验报告
姓名：张**    性别：男    年龄：64
空腹血糖(GLU)        6.8 mmol/L     3.9-6.1      ↑
糖化血红蛋白(HbA1c)   7.5 %          4.0-6.0      ↑
总胆固醇(TC)          5.6 mmol/L     2.8-5.2      ↑
甘油三酯(TG)          2.31 mmol/L    0.4-1.7      ↑
低密度脂蛋白(LDL-C)   3.62 mmol/L    1.0-3.4      ↑
高密度脂蛋白(HDL-C)   1.02 mmol/L    1.0-2.6
"""
