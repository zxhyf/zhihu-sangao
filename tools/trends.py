# -*- coding: utf-8 -*-
"""趋势分析：只基于数据库中真实存在的记录计算，数据不足时明确说明。"""
from __future__ import annotations

from datetime import datetime, timedelta

from config import DEFAULT_USER
from tools import measurements, profile as profile_tool, risks


def _slope(points: list[tuple[float, float]]) -> float:
    """最小二乘斜率（单位/天）。points = [(天序号, 值)]"""
    n = len(points)
    if n < 2:
        return 0.0
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def analyze(user_id: str = DEFAULT_USER, kind: str = "bp", sub: str | None = None,
            days: int = 30, min_points: int = 3) -> dict:
    rows = measurements.list_measurements(user_id, kind, sub, days=days, limit=500)
    p = profile_tool.get_profile(user_id)
    label = risks.KIND_LABEL.get(kind, kind)
    if sub:
        label = f"{label}（{risks.SUB_LABEL.get(sub, sub)}）"

    if len(rows) < min_points:
        return {
            "ok": False,
            "kind": kind, "sub": sub, "label": label, "count": len(rows),
            "message": f"近 {days} 天只有 {len(rows)} 条{label}记录，不足以判断趋势。"
                       f"至少需要 {min_points} 条记录（建议每天固定时间测量）。",
        }

    t0 = datetime.strptime(rows[0]["measured_at"], "%Y-%m-%d %H:%M:%S")
    series = []
    pts = []
    values = []
    counts = {"normal": 0, "watch": 0, "danger": 0, "emergency": 0}
    for r in rows:
        dt = datetime.strptime(r["measured_at"], "%Y-%m-%d %H:%M:%S")
        rk = risks.classify(kind, r["sub_kind"], r["val1"], r["val2"], p)
        counts[rk["level"]] = counts.get(rk["level"], 0) + 1
        series.append({
            "t": r["measured_at"],
            "label": dt.strftime("%m-%d %H:%M"),
            "v": r["val1"],
            "v2": r["val2"],
            "risk": rk["level"],
            "text": risks.fmt_value(kind, r["sub_kind"], r["val1"], r["val2"]),
        })
        values.append(r["val1"])
        pts.append(((dt - t0).total_seconds() / 86400.0, r["val1"]))

    mean_v = sum(values) / len(values)
    slope = _slope(pts)
    first, last = values[0], values[-1]
    delta = last - first
    flat = abs(slope) < 0.05 if kind != "glucose" else abs(slope) < 0.02
    if flat:
        direction = "基本平稳"
    elif slope > 0:
        direction = "呈上升趋势"
    else:
        direction = "呈下降趋势"

    stats = {
        "count": len(values),
        "mean": round(mean_v, 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "first": round(first, 1),
        "last": round(last, 1),
        "delta": round(delta, 1),
        "slope_per_day": round(slope, 3),
        "direction": direction,
        "days": days,
    }
    if kind == "bp":
        dias = [r["val2"] for r in rows if r["val2"]]
        stats["mean_dia"] = round(sum(dias) / len(dias), 1) if dias else None
        stats["mean_text"] = f"{stats['mean']:.0f}/{stats['mean_dia']:.0f} mmHg" if dias else f"{stats['mean']:.0f} mmHg"
    else:
        stats["mean_text"] = f"{stats['mean']:g} {'%' if kind == 'hba1c' else ('kg' if kind == 'weight' else ('cm' if kind == 'waist' else 'mmol/L'))}"

    unit = "mmHg" if kind == "bp" else ("%" if kind == "hba1c" else ("kg" if kind == "weight" else ("cm" if kind == "waist" else "mmol/L")))
    abnormal = counts["watch"] + counts["danger"] + counts["emergency"]

    return {
        "ok": True,
        "kind": kind, "sub": sub, "label": label, "unit": unit,
        "count": len(values),
        "series": series,
        "stats": stats,
        "counts": counts,
        "abnormal": abnormal,
        "message": (
            f"近 {days} 天共 {len(values)} 条{label}记录，平均 {stats['mean_text']}，"
            f"波动 {min(values):g}–{max(values):g} {unit}，{direction}。"
            f"其中 {abnormal} 条超出指南参考范围。"
        ),
    }


def overview(user_id: str = DEFAULT_USER, days: int = 30) -> dict:
    """仪表盘：多指标趋势总览。"""
    out = {"bp": analyze(user_id, "bp", None, days),
           "glucose_fasting": analyze(user_id, "glucose", "fasting", days),
           "glucose_post": analyze(user_id, "glucose", "postprandial", days),
           "ldl": analyze(user_id, "lipid", "ldl", 180),
           "tg": analyze(user_id, "lipid", "tg", 180),
           "weight": analyze(user_id, "weight", None, 180)}
    return out
