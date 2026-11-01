# -*- coding: utf-8 -*-
"""回复渲染层：把工具结果转成前端可渲染的结构化卡片，并提供离线叙事模板。"""
from __future__ import annotations

from datetime import datetime

from config import DISCLAIMER
from tools import risks


def metric_block(rec: dict) -> dict:
    r = rec.get("risk") or {}
    return {
        "type": "metric",
        "label": rec.get("label"),
        "value": rec.get("value_text"),
        "time": rec.get("measured_at"),
        "risk": {
            "level": r.get("level", "normal"),
            "label": r.get("label", "已记录"),
            "detail": r.get("detail", ""),
            "ref": r.get("ref", ""),
        },
    }


def chart_block(trend: dict) -> dict | None:
    if not trend or not trend.get("ok"):
        return None
    return {
        "type": "chart",
        "title": trend.get("label"),
        "kind": trend.get("kind"),
        "sub": trend.get("sub"),
        "unit": trend.get("unit"),
        "series": trend.get("series", []),
        "stats": trend.get("stats", {}),
        "counts": trend.get("counts", {}),
        "message": trend.get("message", ""),
    }


def stats_block(trend: dict) -> dict | None:
    if not trend or not trend.get("ok"):
        return None
    st = trend.get("stats", {})
    return {
        "type": "stats",
        "title": trend.get("label"),
        "items": [
            {"k": "记录条数", "v": f"{st.get('count')} 条"},
            {"k": "平均值", "v": st.get("mean_text")},
            {"k": "最低", "v": f"{st.get('min'):g} {trend.get('unit')}"},
            {"k": "最高", "v": f"{st.get('max'):g} {trend.get('unit')}"},
            {"k": "变化方向", "v": st.get("direction")},
            {"k": "超出参考范围", "v": f"{trend.get('abnormal')} 条"},
        ],
    }


def alert_block(level: str, title: str, body: str, actions: list[str],
                category: str = "") -> dict:
    return {"type": "alert", "level": level, "category": category,
            "title": title, "body": body, "actions": actions}


def plan_block(plan: dict, max_days: int = 7) -> dict:
    return {
        "type": "plan",
        "title": plan.get("title"),
        "days": plan.get("days", [])[:max_days],
        "shopping": plan.get("shopping", []),
        "tips": plan.get("tips", []),
        "basis": plan.get("basis", []),
    }


def report_block(report: dict) -> dict:
    return {"type": "report", "title": report.get("title"),
            "range": report.get("range"), "sections": report.get("sections", [])}


def meds_block(meds: list[dict], title: str = "当前用药清单") -> dict:
    return {
        "type": "meds", "title": title,
        "items": [{"name": m.get("name"), "dose": m.get("dose"),
                   "frequency": m.get("frequency"), "times": m.get("times") or [],
                   "purpose": m.get("purpose") or ""} for m in meds],
    }


def interactions_block(res: dict) -> dict:
    return {
        "type": "interactions",
        "title": "药物联动检查",
        "summary": res.get("summary"),
        "drugs": [{"name": d.get("name"), "class": d.get("class")} for d in res.get("drugs", [])],
        "interactions": res.get("interactions", []),
        "notes": res.get("notes", []),
        "disclaimer": res.get("disclaimer"),
    }


def tasks_block(items: list[dict], stats: dict | None = None) -> dict:
    return {"type": "tasks", "title": "今日任务卡", "items": items, "stats": stats}


def lab_block(parsed: dict) -> dict:
    return {
        "type": "lab",
        "title": "检验单识别结果",
        "date_text": parsed.get("date_text"),
        "measured_at": parsed.get("measured_at"),
        "items": parsed.get("items", []),
        "summary": parsed.get("summary", ""),
    }


def cta_block(title: str, body: str, button: str, action: str) -> dict:
    return {"type": "cta", "title": title, "body": body, "button": button, "action": action}


def med_safety_block(extra: list[str] | None = None) -> dict:
    """用药语境下强制附加的安全提示：不依赖模型是否记得说，由系统结构性保证。"""
    lines = [
        "以上内容用于帮助你**准备与医生的沟通**，不构成用药建议，也不能替代医生或药师的判断。",
        "**请严格按医生处方服药**：不自行加量、减量、换药或停药；漏服后不要自行补双倍剂量。",
        "同时服用其他药物、保健品或中成药时，请务必告知医生或药师。",
        "出现头晕、心慌、水肿、肌肉酸痛、黑便、尿量明显减少等不适，请尽快就医。",
    ]
    if extra:
        lines = list(extra) + lines
    return {
        "type": "safety_note",
        "title": "用药安全提醒",
        "lines": lines,
        "foot": "本建议不构成诊疗意见，请遵医嘱。",
    }


def sources_payload(chunks: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for c in chunks:
        key = c.get("source") or c.get("title")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": c.get("title"),
            "heading": c.get("heading"),
            "source": c.get("source"),
            "org": c.get("org"),
            "year": c.get("year"),
            "url": c.get("url"),
            "level": c.get("level"),
            "snippet": (c.get("text") or "")[:160],
        })
    return out


# ------------------------------------------------------------------ 离线叙事
def local_reply(intent: str, facts: dict, user_text: str = "") -> str:
    """无大模型时的确定性叙事模板（保证功能完整、语气自然）。"""
    p = facts.get("profile") or {}
    name = p.get("name") or "您"

    if intent == "record":
        rec = (facts.get("record") or [None])[0]
        if not rec:
            return "这次没能识别出具体数值。可以这样说：“今天血压 150/95”“空腹血糖 7.2”“体重 70 公斤”。"
        risk = rec.get("risk") or {}
        lines = [f"已记录：{rec.get('measured_at', '')[:16]} {rec.get('label')} **{rec.get('value_text')}**，"
                 f"风险分级为「{risk.get('label')}」。", risk.get("detail", "")]
        trend = facts.get("trend")
        if trend and trend.get("ok"):
            st = trend.get("stats", {})
            lines.append(f"近 {st.get('days')} 天平均 {st.get('mean_text')}，{st.get('direction')}，"
                         f"共 {trend.get('abnormal')} 条超出指南参考范围。")
        else:
            lines.append("目前这个指标的记录还不多，连续记录 3 天以上就能看出趋势。")
        if risk.get("level") in ("danger", "emergency"):
            lines.append("- 这个数值已超出安全区间，先把测量结果和当时的感受记下来，尽快联系医生。")
        else:
            lines.append("- 明天同一时间（起床后、服药前、早餐前）再测一次，对比才有意义。")
        lines.append(f"- 记录依据：{risk.get('ref', '')}（来源：《中国高血压/糖尿病/血脂管理指南》）")
        return "\n".join(x for x in lines if x)

    if intent in ("query_trend", "query_latest"):
        trend = facts.get("trend")
        if not trend or not trend.get("ok"):
            msg = (trend or {}).get("message") or "目前还没有足够的记录来判断趋势。"
            return msg + "\n- 建议每天固定时间测一次，连续 3 天以上系统就能画出趋势图。"
        st = trend.get("stats", {})
        lines = [
            f"{trend.get('label')}：近 {st.get('days')} 天共 {st.get('count')} 条记录，平均 **{st.get('mean_text')}**，"
            f"区间 {st.get('min'):g}–{st.get('max'):g} {trend.get('unit')}，{st.get('direction')}。",
            f"其中 {trend.get('abnormal')} 条超出指南参考范围（警戒 {trend['counts']['watch']} 条、"
            f"危险 {trend['counts']['danger']} 条、急症 {trend['counts']['emergency']} 条）。",
        ]
        if "上升" in st.get("direction", ""):
            lines.append("- 上升趋势先排查三件事：有没有漏服药、口味是不是变咸了、最近睡眠够不够。")
        elif "下降" in st.get("direction", ""):
            lines.append("- 下降趋势说明当前管理方式在起作用，继续保持定时测量和记录。")
        else:
            lines.append("- 整体平稳，重点是保持每天同一时间测量，异常单次值要复测确认。")
        lines.append("- 复诊时把这张趋势图给医生看，比只说“最近还行”有用得多。")
        return "\n".join(lines)

    if intent == "interaction":
        res = facts.get("interaction") or {}
        if not res.get("drugs"):
            return "没有识别到具体药名。可以说“我在吃氨氯地平、二甲双胍、阿托伐他汀，能一起吃吗”。"
        lines = [res.get("summary", "")]
        for it in (res.get("interactions") or [])[:4]:
            tag = "⚠️ 高风险" if it.get("level") == "high" else "· 需关注"
            lines.append(f"- {tag}：{it.get('title')}。{it.get('action', '')}")
        if not res.get("interactions"):
            lines.append("- 在已收录的规则里没有命中明确冲突，但这不等于“可以随便一起吃”，新增药物仍需医生或药师审核。")
        lines.append("以上是知识库规则提示，不能替代医生和药师的判断。")
        return "\n".join(x for x in lines if x)

    if intent == "plan":
        plan = facts.get("plan") or {}
        tips = plan.get("tips") or []
        lines = [f"已根据你的情况生成 {plan.get('title', '7 日方案')}：会做饭={'是' if (plan.get('profile') or {}).get('can_cook') else '否'}，"
                 f"预算={(plan.get('profile') or {}).get('budget')}，"
                 f"共病={'、'.join((plan.get('profile') or {}).get('conditions') or []) or '未填写'}。"]
        lines.extend(f"- {t}" for t in tips[:3])
        lines.append("- 方案里的每一条都写了时间、食物克数和动作，照着做就行；做不到的项目可以告诉我，我按你的条件改。")
        return "\n".join(lines)

    if intent == "report":
        rep = facts.get("report") or {}
        return (f"{rep.get('summary', '本期报告已生成。')}\n"
                "- 报告里标红的部分是超过指南参考范围的记录，复诊时优先和医生讨论这几项。\n"
                "- 用药依从率低于 70% 时，先把打卡补起来，再谈调整方案。")

    if intent == "lab":
        lab = facts.get("lab") or {}
        items = lab.get("items") or []
        if items:
            head = "、".join(f"{i['label']} {i['value']}{i['unit']}" for i in items[:4])
            return (f"已从检验单识别出 {len(items)} 项指标（{lab.get('date_text', '')}）：{head}。\n"
                    "- 请逐项核对数值，确认无误后点「确认入库」，我不会自动写入。\n"
                    "- 入库后趋势图才会更新，之后的趋势分析和周报都会用到这批数据。")
        return ("把化验单上的文字粘贴到「检验单录入」窗口，我会逐项识别血糖、糖化、血脂四项，"
                "给出风险等级，你核对勾选后才入库。")

    if intent == "med_record":
        meds = facts.get("recorded_meds") or []
        if not meds:
            return "没有识别到药名。可以说“早上吃了氨氯地平 5 mg”。"
        names = "、".join(m.get("name", "") for m in meds)
        return (f"已记录用药：{names}。\n"
                "- 建议把服药时间和刷牙、早饭绑在一起，形成固定习惯。\n"
                "- 如果今天有漏服，不要自行补双倍剂量，下次按正常时间服用即可，并在复诊时告知医生。\n"
                "- 药物的加量、减量、更换都要由医生决定。")

    if intent == "profile":
        conds = "、".join(p.get("conditions") or []) or "未填写"
        return (f"{name}，{p.get('age') or '年龄未知'} 岁，{p.get('height_cm') or '身高未知'} cm，"
                f"{p.get('weight') or '体重未记录'} kg，BMI {p.get('bmi') or '未知'}。\n"
                f"- 共病：{conds}\n"
                f"- 作息：{p.get('wake_time')}–{p.get('sleep_time')}，做饭条件：{'会做饭' if p.get('can_cook') else '基本不做饭'}\n"
                "- 想改哪一项直接说，例如“我今年 58 岁”“我基本不做饭”“我口味偏咸”。")

    if intent == "task":
        t = facts.get("task") or {}
        return (f"今天共 {t.get('total', 0)} 项任务，已完成 {t.get('done', 0)} 项（{t.get('rate', 0)}%）。\n"
                "- 优先做两件事：起床后测血压、按点吃药。\n"
                "- 任务卡在右侧栏，点一下就能勾选。")

    if intent == "greeting":
        return ("你好，我是智护三高，可以帮你：\n"
                "- 记录血压、血糖、血脂、体重，并解释这次数值意味着什么\n"
                "- 看最近一段时间的趋势，判断是升还是降\n"
                "- 生成 7 天可执行的吃饭和运动方案\n"
                "- 检查三高共病用药之间的相互影响\n"
                "- 汇总成一份可以带去复诊的报告\n"
                "直接说一句就行，比如“今天血压 150/95”。")

    chunks = facts.get("kb_top") or []
    if chunks:
        head = chunks[0]
        snippet = (head.get("text") or "").strip().split("\n")
        body = "\n".join(snippet[:4])[:300]
        return (f"按《{head.get('title')}》的「{head.get('heading')}」这一节：\n{body}\n"
                f"（来源：{head.get('source')}）")
    return ("这个问题我需要更多信息才能回答。可以补充：具体指标和数值、正在吃的药、"
            "以及你最想解决的问题（比如“血压总是早上高”）。")


DISCLAIMER_LINE = DISCLAIMER
