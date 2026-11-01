# -*- coding: utf-8 -*-
"""周期健康管理报告：只汇总数据库中真实存在的记录。"""
from __future__ import annotations

from datetime import datetime, timedelta

from config import DEFAULT_USER, DISCLAIMER
from data import db
from tools import measurements, medications, profile as profile_tool, risks, trends


def _range_text(days: int) -> str:
    end = datetime.now()
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}"


def _risk_events(user_id: str, days: int) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = db.query(
        "SELECT * FROM risk_events WHERE user_id=? AND created_at>=? ORDER BY created_at DESC LIMIT 20",
        (user_id, since))
    return [dict(r) for r in rows]


def weekly(user_id: str = DEFAULT_USER, days: int = 7) -> dict:
    p = profile_tool.get_profile(user_id)
    total = measurements.count(user_id, days)
    bp = trends.analyze(user_id, "bp", None, days, min_points=2)
    glu = trends.analyze(user_id, "glucose", None, days, min_points=2)
    adh = medications.adherence(user_id, days)
    events = _risk_events(user_id, days)
    snap = measurements.snapshot(user_id)

    sections: list[dict] = []

    # 1. 记录情况
    sections.append({
        "title": "一、记录情况",
        "lines": [
            f"统计区间：{_range_text(days)}",
            f"本期共记录 {total} 条健康数据" + (f"，其中血压 {bp.get('count', 0)} 条" if bp.get("ok") else ""),
            f"用药打卡 {adh['taken']} 次，预计应服 {adh['expected']} 次"
            + (f"，依从率 {adh['rate']:.0f}%" if adh["expected"] else "（尚未登记用药计划）"),
        ],
    })

    # 2. 血压
    if bp.get("ok"):
        st = bp["stats"]
        sections.append({
            "title": "二、血压趋势",
            "lines": [
                bp["message"],
                f"平均值 {st['mean_text']}，最高 {st['max']:g} mmHg，最低 {st['min']:g} mmHg",
                f"超出指南参考范围 {bp['abnormal']} 条（警戒 {bp['counts']['watch']}、危险 {bp['counts']['danger']}、急症 {bp['counts']['emergency']}）",
            ],
            "chart": bp,
        })
    else:
        sections.append({"title": "二、血压趋势", "lines": [bp.get("message", "本期无血压记录")]})

    # 3. 血糖
    if glu.get("ok"):
        st = glu["stats"]
        sections.append({
            "title": "三、血糖趋势",
            "lines": [
                glu["message"],
                f"平均值 {st['mean_text']}，{st['direction']}",
            ],
            "chart": glu,
        })
    else:
        sections.append({"title": "三、血糖趋势", "lines": [glu.get("message", "本期无血糖记录")]})

    # 4. 当前指标快照
    items = snap.get("items", [])
    if items:
        sections.append({
            "title": "四、最近一次指标",
            "lines": [f"{i['label']}：{i['value']}（{i['at'][:16]}，{i['risk']['label']}）" for i in items],
        })

    # 5. 风险事件
    if events:
        sections.append({
            "title": "五、需要关注的事件",
            "lines": [f"{e['created_at'][:16]}：{e['title']} {e['detail']}" for e in events[:6]],
        })
    else:
        sections.append({"title": "五、需要关注的事件", "lines": ["本期未记录到超出危险范围的事件。"]})

    # 6. 用药
    meds = medications.list_meds(user_id)
    if meds:
        sections.append({
            "title": "六、当前用药清单",
            "lines": [f"{m['name']} {m['dose']} · {m['frequency']}（{'/'.join(m.get('times') or [])}）"
                      for m in meds],
        })

    # 7. 下周重点 + 复诊问题
    focus: list[str] = []
    if bp.get("ok") and bp["abnormal"] > bp["count"] * 0.5:
        focus.append("血压多数记录高于参考范围，建议本周内复诊，并带上本期血压趋势")
    if bp.get("ok") and "上升" in bp["stats"]["direction"]:
        focus.append("血压呈上升趋势，先检查是否漏服药、口味变咸、睡眠变差")
    if glu.get("ok") and glu["counts"]["danger"] + glu["counts"]["emergency"] > 0:
        focus.append("出现血糖危险范围记录，建议把血糖记录和饮食情况一起带给医生")
    if adh["expected"] and adh["rate"] < 70:
        focus.append("用药依从率偏低，可以试试分药盒或手机闹钟，把服药挂在刷牙之后")
    if not bp.get("ok"):
        focus.append("血压记录不足，建议每天固定时间测量并记录（早晨服药前 + 睡前）")
    if not focus:
        focus.append("本期各项记录较为完整，继续保持每日测量与打卡")

    questions = [
        "我的血压/血糖这段时间的平均值和波动，是否在可接受范围？",
        "现在吃的这几种药，有没有代谢方面的相互影响需要注意？",
        "下次复查需要做哪些项目（肝肾功能、血脂、糖化血红蛋白、尿白蛋白）？",
        "生活方式上，最值得我优先改的一件事是什么？",
    ]

    sections.append({"title": "七、下周重点", "lines": focus})
    sections.append({"title": "八、复诊时可以问医生的问题", "lines": questions})

    md_lines = [f"# {p.get('name') or '用户'} · {days} 天健康管理报告", "",
                f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}　统计区间：{_range_text(days)}", ""]
    for s in sections:
        md_lines.append(f"## {s['title']}")
        for ln in s["lines"]:
            md_lines.append(f"- {ln}")
        md_lines.append("")

    return {
        "ok": True,
        "title": f"{days} 天健康管理报告",
        "range": _range_text(days),
        "sections": sections,
        "markdown": "\n".join(md_lines),
        "summary": f"本期共 {total} 条记录；"
                   + (f"血压平均 {bp['stats']['mean_text']}，{bp['stats']['direction']}；" if bp.get("ok") else "")
                   + (f"血糖平均 {glu['stats']['mean_text']}；" if glu.get("ok") else "")
                   + (f"用药依从率 {adh['rate']:.0f}%。" if adh["expected"] else ""),
        "disclaimer": DISCLAIMER,
    }
