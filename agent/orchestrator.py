# -*- coding: utf-8 -*-
"""智能体编排器：安全网关 → 意图识别 → 受控工具调用 → 知识检索 → 大模型叙事 → 结构化输出。

一条消息的完整链路（对应界面上的“思考过程”）
1. 安全网关：红旗症状 / 处方红线，命中即锁定输出，大模型不参与
2. 意图识别：确定性规则抽取数值、时间、药名
3. 工具调用：入库、查询、趋势、方案、报告、药物联动（全部服务端执行）
4. 知识检索：BM25 检索本地指南知识库，返回可溯源片段
5. 生成回复：DeepSeek 只负责“怎么说”，数字和结论来自工具
6. 输出：结构化卡片 + 叙事 + 来源 + 免责声明
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from config import DEFAULT_USER, DISCLAIMER, EMERGENCY_NUMBER
from data import db
from agent import formatter, llm, prompts, safety
from agent.intent import detect_intent, parse_profile_update, parse_time
from agent.rag import get_kb
from tools import (interactions, lab_report, measurements, medications, plan as plan_tool,
                   profile as profile_tool, registry, reports, risks, tasks, trends)

TRACE_LABEL = {
    "safety": "安全网关",
    "intent": "意图识别",
    "tool": "工具调用",
    "trend": "趋势分析",
    "kb": "知识检索",
    "llm": "生成回复",
    "guard": "输出校验",
    "medguard": "用药提示",
}


def _trace(step: str, status: str, detail: str) -> dict:
    return {"step": step, "label": TRACE_LABEL.get(step, step), "status": status, "detail": detail}


STEP_ORDER = ["safety", "intent", "tool", "trend", "kb", "llm", "guard", "medguard"]


def _order_trace(trace: list[dict]) -> list[dict]:
    """让界面上的“思考过程”按链路顺序展示，而不是按代码执行顺序。"""
    return sorted(trace, key=lambda t: STEP_ORDER.index(t["step"]) if t["step"] in STEP_ORDER else 99)


def _history(user_id: str, limit: int = 8) -> list[dict]:
    rows = db.query(
        "SELECT role, content FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit))
    return [dict(r) for r in reversed(rows)]


def _save(user_id: str, role: str, content: str, blocks: list | None = None) -> None:
    db.execute(
        "INSERT INTO chat_messages (user_id, role, content, blocks, created_at) VALUES (?,?,?,?,?)",
        (user_id, role, content, json.dumps(blocks or [], ensure_ascii=False), db.now_iso()))


FOLLOWUPS = {
    "record": ["我最近血压怎么样", "给我一份 7 天方案", "检查我的用药有没有冲突"],
    "lab": ["打开检验单录入", "看看我的血脂记录", "帮我生成这周的报告"],
    "query_trend": ["帮我生成这周的报告", "最近血糖怎么样", "我该重点改哪一件事"],
    "kb": ["三高人群每天能吃多少盐", "血压高早餐吃什么", "他汀和阿托伐他汀有什么区别"],
    "plan": ["帮我看看今天的任务", "我不会做饭，能不能换成外卖方案", "我的用药有没有冲突"],
    "report": ["复诊时该问医生什么", "我最近的血压趋势", "生成下周方案"],
    "interaction": ["我最近血压怎么样", "帮我整理用药清单", "他汀和阿托伐他汀有什么区别"],
    "greeting": ["今天血压 150/95", "我最近血压怎么样", "给我一份 7 天方案"],
    "default": ["今天血压 150/95", "我最近血压怎么样", "给我一份 7 天方案"],
}


def handle(text: str, user_id: str = DEFAULT_USER, use_llm: bool = True,
           save: bool = True) -> dict:
    started = time.time()
    text = (text or "").strip()
    trace: list[dict] = []
    blocks: list[dict] = []
    sources: list[dict] = []
    facts: dict = {}

    profile = profile_tool.get_profile(user_id)
    facts["profile"] = {k: profile.get(k) for k in
                        ("name", "age", "sex", "height_cm", "weight", "bmi", "conditions",
                         "can_cook", "budget", "taste", "wake_time", "sleep_time")}

    # ---------- 1. 意图与实体 ----------
    intent, conf, parsed = detect_intent(text)
    measurements_parsed = parsed.get("measurements") or []
    meds_parsed = parsed.get("medications") or []
    trace.append(_trace("intent", "ok",
                        f"意图={intent}（置信度 {conf}）"
                        + (f"，抽取到 {len(measurements_parsed)} 个指标" if measurements_parsed else "")
                        + (f"，识别到药物：{'、'.join(m['name'] for m in meds_parsed)}" if meds_parsed else "")))

    # 档案自动更新
    upd = parse_profile_update(text)
    if upd:
        conds = upd.pop("conditions_add", None)
        if upd:
            profile = profile_tool.update_profile(user_id, **upd)
        if conds:
            for c in conds:
                profile = profile_tool.add_condition(user_id, c)
        if upd or conds:
            trace.append(_trace("tool", "ok", f"档案已更新：{'、'.join(list(upd.keys()) + (conds or []))}"))
            facts["profile"] = {k: profile.get(k) for k in
                                ("name", "age", "sex", "height_cm", "weight", "bmi", "conditions",
                                 "can_cook", "budget", "taste", "wake_time", "sleep_time")}

    # ---------- 2. 记录类：先入库（即使随后命中急症，也要留下记录） ----------
    recorded: list[dict] = []
    if intent in ("record", "med_record") and measurements_parsed:
        for m in measurements_parsed:
            res = measurements.record(
                user_id, m["kind"], m.get("sub_kind"), m["val1"], m.get("val2"),
                m.get("unit"), m.get("measured_at"), "chat",
                note=m.get("raw", ""))
            if res.get("ok"):
                recorded.append(res)
                blocks.append(formatter.metric_block(res))
            else:
                blocks.append(formatter.alert_block(
                    "watch", "这条数据没有入库", res.get("error", ""),
                    ["请检查数值和单位后重新发送，例如“今天血压 150/95”"], "数据校验"))
        if recorded:
            trace.append(_trace("tool", "ok",
                                f"measurement.record × {len(recorded)} → 已写入 SQLite（{recorded[0]['value_text']}）"))
            facts["record"] = [{"label": r["label"], "value_text": r["value_text"],
                               "measured_at": r["measured_at"], "risk": r["risk"]} for r in recorded]

    # ---------- 3. 安全网关 ----------
    sec = safety.evaluate(text)
    if sec["level"] == "emergency":
        trace.append(_trace("safety", "blocked", f"命中红旗规则：{sec.get('title')} → 跳过建议生成"))
        payload = _emergency_response(sec, recorded, blocks, trace, started)
        if save:
            _save(user_id, "user", text)
            _save(user_id, "assistant", payload["reply"], payload["blocks"])
        return payload

    if sec["level"] == "prescription" and intent != "med_plan":
        trace.append(_trace("safety", "warn", f"命中处方红线：{'、'.join(sec.get('matched', []))} → 锁定为不可调药回答"))
        payload = _prescription_response(text, sec, profile, blocks, trace, started)
        if save:
            _save(user_id, "user", text)
            _save(user_id, "assistant", payload["reply"], payload["blocks"])
        return payload

    trace.append(_trace("safety", "ok", "未命中红旗症状与处方红线"))

    # ---------- 4. 业务路由（工具调用） ----------
    trend = None
    if intent == "record" and recorded:
        kind = recorded[0]["kind"]
        sub = recorded[0].get("sub_kind")
        trend = trends.analyze(user_id, kind, sub, days=30 if kind != "lipid" else 180, min_points=3)
        if trend.get("ok"):
            blocks.append(formatter.chart_block(trend))
            blocks.append(formatter.stats_block(trend))
            facts["trend"] = trend
            trace.append(_trace("trend", "ok",
                                f"trend.analyze({kind}) → {trend['count']} 条，均值 {trend['stats']['mean_text']}"))

    elif intent in ("query_trend", "query_latest"):
        kind, sub = _guess_metric(text)
        days = 30 if kind in ("bp", "glucose", "weight") else 180
        trend = trends.analyze(user_id, kind, sub, days=days, min_points=3)
        if trend.get("ok"):
            blocks.append(formatter.chart_block(trend))
            blocks.append(formatter.stats_block(trend))
            facts["trend"] = trend
            trace.append(_trace("trend", "ok",
                                f"trend.analyze({kind}{'/' + sub if sub else ''}) → {trend['count']} 条"))
        else:
            blocks.append(formatter.alert_block(
                "info", "记录不足", trend.get("message", ""),
                ["每天固定时间测一次，连续 3 天后就能看到趋势"], "数据"))
            facts["trend"] = trend
            trace.append(_trace("trend", "warn", "记录不足，未生成趋势图"))

    elif intent == "interaction" or (len(meds_parsed) >= 2 and intent == "med_record"):
        res = interactions.check([m["name"] for m in meds_parsed], text=text, user_id=user_id)
        blocks.append(formatter.interactions_block(res))
        facts["interaction"] = {
            "summary": res["summary"],
            "drugs": [{"name": d["name"], "class": d["class"], "watch": d.get("watch", [])} for d in res["drugs"]],
            "interactions": [{k: it[k] for k in ("title", "detail", "action", "level", "source")}
                             for it in res["interactions"]],
        }
        trace.append(_trace("tool", "ok",
                            f"drug.check → 识别 {len(res['drugs'])} 种药物，命中 {len(res['interactions'])} 条联动规则"))
        if intent == "med_record" and len(meds_parsed) >= 2:
            # 用户其实是在问“这些药一起吃要注意什么”，按用药联动回答更准确
            intent = "interaction"

    elif intent == "plan":
        p = plan_tool.generate(user_id, days=7)
        blocks.append(formatter.plan_block(p))
        facts["plan"] = {"title": p["title"], "profile": p["profile"], "tips": p["tips"],
                         "first_day": p["days"][0]["items"] if p["days"] else [],
                         "shopping": p["shopping"][:12]}
        trace.append(_trace("tool", "ok", f"plan.generate → {len(p['days'])} 天 × {len(p['days'][0]['items']) if p['days'] else 0} 项"))

    elif intent == "report":
        rep = reports.weekly(user_id, days=7)
        blocks.append(formatter.report_block(rep))
        facts["report"] = {"title": rep["title"], "summary": rep["summary"],
                           "sections": [{"title": s["title"], "lines": s["lines"]} for s in rep["sections"]]}
        trace.append(_trace("tool", "ok", f"report.weekly → {len(rep['sections'])} 个章节"))
        if any("用药" in s["title"] for s in rep["sections"]):
            blocks.append(formatter.med_safety_block())
            trace.append(_trace("medguard", "ok", "报告含用药清单，已附加用药安全提示"))

    elif intent == "task":
        items = tasks.ensure_today(user_id)
        st = tasks.stats_today(user_id)
        blocks.append(formatter.tasks_block(items, st))
        facts["task"] = st
        trace.append(_trace("tool", "ok", f"task.today → {st['total']} 项，已完成 {st['done']} 项"))

    elif intent == "profile":
        meds = medications.list_meds(user_id)
        blocks.append(formatter.meds_block(meds))
        facts["meds"] = [{"name": m["name"], "dose": m["dose"], "frequency": m["frequency"]} for m in meds]
        trace.append(_trace("tool", "ok", f"profile.get + med.list → {len(meds)} 种在服药物"))

    elif intent == "lab":
        parsed = lab_report.parse_text(text)
        if parsed.get("ok"):
            blocks.append(formatter.lab_block(parsed))
            facts["lab"] = {"date_text": parsed["date_text"], "summary": parsed["summary"],
                            "items": [{"label": i["label"], "value": i["value"], "unit": i["unit"],
                                       "risk": i["risk"]["label"]} for i in parsed["items"]]}
            trace.append(_trace("tool", "ok",
                                f"lab.parse → 识别 {len(parsed['items'])} 项，等待用户确认入库"))
        else:
            blocks.append(formatter.cta_block(
                "检验单录入",
                "把化验单上的文字粘贴到录入窗口（支持血糖、糖化、总胆固醇、甘油三酯、LDL、HDL），"
                "我会逐项识别、给出风险等级，你核对勾选后才会真正入库。",
                "打开检验单录入", "open_lab"))
            facts["lab"] = {"error": parsed.get("error", "")}
            trace.append(_trace("tool", "warn", "lab.parse 未识别到可入库指标，改为引导手动录入"))

    elif intent == "med_plan" and parsed.get("med_plan"):
        plan = parsed["med_plan"]
        # 区分「添加计划」与「变更计划」：和当前用药清单比对
        exists = {m["name"]: m for m in medications.list_meds(user_id)}
        adds, updates = 0, 0
        for it in plan["items"]:
            cur = exists.get(it["name"])
            if plan["action"] == "stop":
                it["change"] = "remove"
                it["prev_times"] = (cur or {}).get("times") or []
            elif cur:
                prev_times = cur.get("times") or []
                new_times = it["times"] or ["08:00"]
                same = (prev_times == new_times and
                        (not it.get("dose") or it["dose"] == (cur.get("dose") or "")))
                it["change"] = "same" if same else "update"
                it["prev_times"] = prev_times
                it["prev_dose"] = cur.get("dose") or ""
                updates += 0 if same else 1
            else:
                it["change"] = "add"
                it["prev_times"] = []
                adds += 1
        actionable = [it for it in plan["items"] if it.get("change") != "same"]
        plan["mode"] = ("none" if plan["action"] != "stop" and not actionable else
                        "add" if adds and not updates else
                        "update" if updates and not adds else "mixed")
        plan["noop"] = plan["mode"] == "none"
        if not plan["noop"]:
            blocks.append(formatter.med_change_block(plan))
        facts["med_plan"] = plan
        trace.append(_trace("tool", "ok",
                            f"生成用药计划草案（新增 {adds} / 变更 {updates} / 无变化 {len(plan['items']) - len(actionable)}）："
                            + ("无需改动" if plan["noop"] else "等待用户确认后写入")))

    elif intent == "med_record" and meds_parsed:
        recorded_meds = []
        taken_at, time_desc = parse_time(text)
        for m in meds_parsed:
            exists = any(x["name"] == m["name"] for x in medications.list_meds(user_id))
            if exists:
                medications.log_dose(user_id, m["name"], "taken",
                                     note=f"{m.get('dose') or ''} {time_desc}".strip(),
                                     taken_at=taken_at)
            else:
                medications.add_med(user_id, m["name"], m.get("dose") or "", "按医嘱",
                                    [taken_at[11:16]], "")
            recorded_meds.append({"name": m["name"], "dose": m.get("dose", ""), "time": taken_at})
        meds = medications.list_meds(user_id)
        blocks.append(formatter.meds_block(meds, "用药记录已更新"))
        facts["recorded_meds"] = recorded_meds
        facts["med_time"] = taken_at
        trace.append(_trace("tool", "ok",
                            f"med.log / med.add → {'、'.join(m['name'] for m in recorded_meds)}"
                            f"（{taken_at[:16]} 入库）"))

    # ---------- 4.5 用药语境：结构性附加安全提示（不依赖模型是否记得说） ----------
    if intent in ("interaction", "med_record", "profile", "med_plan"):
        blocks.append(formatter.med_safety_block())
        trace.append(_trace("medguard", "ok", "已附加用药安全提示：不构成用药建议，请遵医嘱"))

    # ---------- 5. 知识检索 ----------
    kb = get_kb()
    query = text
    if recorded:
        query = f"{recorded[0]['label']} {recorded[0]['value_text']} " + text
    k = 4 if intent in ("kb", "interaction", "unknown", "greeting") else 3
    try:
        chunks = kb.search(query, k=k)
    except Exception:
        chunks = []
    if chunks:
        sources = formatter.sources_payload(chunks)
        facts["kb_top"] = [{"title": c["title"], "heading": c["heading"], "text": c["text"][:400],
                            "source": c["source"]} for c in chunks[:2]]
        trace.append(_trace("kb", "ok",
                            f"BM25 检索 {len(kb.chunks)} 个片段 → 命中 {len(chunks)} 条：" +
                            "、".join(c["title"].split("（")[0][:12] for c in chunks[:3])))
    else:
        trace.append(_trace("kb", "warn", "未命中知识库片段，回复将不引用来源"))

    # ---------- 6. 生成叙事 ----------
    reply, mode, llm_note = "", "local", ""
    # 用药计划变更必须由系统说确定性文案：不能让模型说“已写入”，其实还在等确认
    forced = ""
    if intent == "med_plan" and parsed.get("med_plan"):
        forced = formatter.med_plan_reply(parsed["med_plan"])
    if forced:
        reply, mode = forced, "rule"
        trace.append(_trace("llm", "ok", "用药计划变更使用确定性文案，交由用户确认"))
    elif use_llm and llm.CLIENT.available:
        try:
            msgs = prompts.build_messages(text, intent, profile, facts, chunks, _history(user_id))
            reply = llm.CLIENT.chat(msgs)
            mode = "llm"
            trace.append(_trace("llm", "ok", f"DeepSeek {llm.CLIENT.model} 生成 {len(reply)} 字"))
        except Exception as exc:
            llm_note = str(exc)[:120]
            trace.append(_trace("llm", "warn", f"大模型调用失败（{llm_note}），降级为本地规则叙事"))
    else:
        trace.append(_trace("llm", "warn", "未启用大模型，使用本地规则叙事"))

    if not reply:
        reply = formatter.local_reply(intent, facts, text)

    # 输出校验：兜底插入免责声明与急症提示
    reply = _post_check(reply, text)

    payload = {
        "ok": True,
        "reply": reply,
        "blocks": blocks,
        "sources": sources,
        "trace": _order_trace(trace),
        "mode": mode,
        "intent": intent,
        "confidence": conf,
        "risk": (recorded[0]["risk"] if recorded else None),
        "followups": FOLLOWUPS.get(intent, FOLLOWUPS["default"]),
        "disclaimer": DISCLAIMER,
        "elapsed_ms": round((time.time() - started) * 1000),
        "llm_error": llm_note,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if save:
        _save(user_id, "user", text)
        _save(user_id, "assistant", reply, blocks)
    return payload


def _guess_metric(text: str) -> tuple[str, str | None]:
    if any(k in text for k in ("血压", "高压", "低压", "收缩压", "舒张压")):
        return "bp", None
    if any(k in text for k in ("血糖", "糖化")):
        if "糖化" in text:
            return "hba1c", None
        if "餐后" in text:
            return "glucose", "postprandial"
        if "空腹" in text:
            return "glucose", "fasting"
        return "glucose", None
    if any(k in text for k in ("血脂", "胆固醇", "甘油三酯", "LDL", "HDL", "低密度", "高密度")):
        if "甘油三酯" in text:
            return "lipid", "tg"
        if "高密度" in text or "HDL" in text:
            return "lipid", "hdl"
        if "总胆固醇" in text:
            return "lipid", "tc"
        return "lipid", "ldl"
    if "体重" in text:
        return "weight", None
    if "腰围" in text:
        return "waist", None
    return "bp", None


def _post_check(reply: str, text: str) -> str:
    reply = (reply or "").strip()
    if not reply:
        return "我没有理解这个问题，可以换一种说法吗？"
    if len(reply) > 1200:
        reply = reply[:1200] + "……"
    return reply


def _emergency_response(sec: dict, recorded: list[dict], blocks: list[dict],
                        trace: list[dict], started: float) -> dict:
    actions = sec.get("actions", "")
    reply = (
        f"**请先立即拨打 {EMERGENCY_NUMBER}。**\n\n"
        f"你描述的情况（{sec.get('title', '急症信号')}）属于需要急诊处理的范围，"
        f"{sec.get('why', '')}。这种情况下，任何家庭处理都不能替代急救。\n\n"
        f"{actions}\n\n"
        "等待救护车时：\n"
        "- 保持安静，坐下或半卧，解开衣领，不要自行加服任何药物\n"
        "- 让家人打开房门，准备好身份证、医保卡和平时吃的药盒\n"
        "- 如果患者意识丧失且没有呼吸，立即开始胸外按压，并让旁人取 AED\n\n"
        "我不会在你描述急症的情况下给任何“先在家观察”的建议。"
    )
    alert = formatter.alert_block(
        "emergency", f"检测到{sec.get('category', '急症')}信号",
        f"{sec.get('title', '')}。{sec.get('why', '')}",
        [actions, "拨打 120，不要自行前往医院", "不要自行加药、不要喂水喂药"], sec.get("category", ""))
    new_blocks = list(blocks) + [alert]
    return {
        "ok": True,
        "reply": reply,
        "blocks": new_blocks,
        "sources": [{"title": "三高急症识别与就医指征",
                     "source": "《中国高血压防治指南（2024年修订版）》/《中国糖尿病防治指南（2024版）》",
                     "org": "国家心血管病中心", "year": "2024", "url": "", "level": "A",
                     "snippet": "胸痛持续超过 15 分钟、意识改变、言语不清、血压 ≥180/110 伴症状等，应立即拨打 120。"}],
        "trace": _order_trace(trace),
        "mode": "safety",
        "intent": "emergency",
        "confidence": 0.99,
        "risk": {"level": "emergency", "label": "急症", "detail": sec.get("title", ""),
                 "ref": "红旗症状规则"},
        "followups": ["我今天血压 185/110 该怎么办", "哪些情况必须去急诊"],
        "disclaimer": DISCLAIMER,
        "elapsed_ms": round((time.time() - started) * 1000),
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _prescription_response(text: str, sec: dict, profile: dict, blocks: list[dict],
                           trace: list[dict], started: float) -> dict:
    chunks = get_kb().search(text, k=3)
    sources = formatter.sources_payload(chunks)
    reply = (
        "这个我不能替你决定。\n\n"
        f"{sec.get('message', '')}\n\n"
        "你可以这样准备：\n"
        + "\n".join(f"- {a}" for a in sec.get("actions", []))
        + "\n\n如果出现头晕、心慌、明显乏力或水肿，尽快就医，不要等到下次复诊。"
    )
    return {
        "ok": True,
        "reply": reply,
        "blocks": list(blocks) + [formatter.alert_block(
            "prescription", "涉及药物调整", sec.get("message", ""),
            sec.get("actions", []), "处方红线")],
        "sources": sources,
        "trace": _order_trace(trace),
        "mode": "safety",
        "intent": "prescription",
        "confidence": 0.95,
        "risk": None,
        "followups": ["帮我整理一份用药清单", "我最近的血压趋势", "他汀和阿托伐他汀有什么区别"],
        "disclaimer": DISCLAIMER,
        "elapsed_ms": round((time.time() - started) * 1000),
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
