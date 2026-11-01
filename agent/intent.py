# -*- coding: utf-8 -*-
"""自然语言理解层：意图识别 + 健康实体抽取（确定性规则，可解释、可测试）。

不依赖任何第三方库；抽取结果全部可回溯到原文片段，便于在界面上展示“系统读到了什么”。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

CJK_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

LIPID_KEYS = [
    (r"总胆固醇|胆固醇\s*TC|\bTC\b", "tc", "总胆固醇", "mmol/L"),
    (r"甘油三酯|三酰甘油|\bTG\b", "tg", "甘油三酯", "mmol/L"),
    (r"低密度脂蛋白(?:胆固醇)?|\bLDL(?:-?C)?\b", "ldl", "低密度脂蛋白胆固醇", "mmol/L"),
    (r"高密度脂蛋白(?:胆固醇)?|\bHDL(?:-?C)?\b", "hdl", "高密度脂蛋白胆固醇", "mmol/L"),
]

NUM = r"(\d{1,3}(?:\.\d{1,2})?)"

BP_PATTERNS = [
    re.compile(rf"(?:血压|血压值|血压是|测得|测了)?\s*{NUM}\s*(?:/|／|比|、)\s*{NUM}\s*(?:mmHg|毫米汞柱)?"),
    re.compile(rf"(?:高压|收缩压)\s*{NUM}[^\d]{{0,6}}(?:低压|舒张压)\s*{NUM}"),
]


def now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_time(text: str, base: datetime | None = None) -> tuple[str, str]:
    """抽取测量时间，返回 (ISO 字符串, 时间描述)。"""
    base = base or now()
    dt = base
    desc = "现在"

    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if m:
        try:
            dt = base.replace(month=int(m.group(1)), day=int(m.group(2)))
            desc = f"{m.group(1)}月{m.group(2)}日"
        except ValueError:
            pass
    else:
        if "昨晚" in text or "昨夜" in text:
            dt = base - timedelta(days=1)
            desc = "昨晚"
        elif "前天" in text:
            dt = base - timedelta(days=2)
            desc = "前天"
        elif "昨天" in text or "昨日" in text:
            dt = base - timedelta(days=1)
            desc = "昨天"
        elif "今天" in text or "刚才" in text or "刚刚" in text:
            desc = "今天"

    hour = None
    if re.search(r"早上|早晨|清晨|早饭前|早餐前|空腹", text):
        hour, desc = 7, (desc + " 早晨") if desc != "现在" else "今天早晨"
    elif re.search(r"上午|早饭后|早餐后", text):
        hour = 9
    elif re.search(r"中午|午饭|午餐", text):
        hour = 12
    elif re.search(r"下午|午睡后", text):
        hour = 15
    elif re.search(r"晚上|晚饭|晚餐|傍晚", text):
        hour = 19
    elif re.search(r"睡前|夜里|夜间", text):
        hour = 22

    m2 = re.search(r"(\d{1,2})\s*[点时](?:\s*(\d{1,2})\s*分)?", text)
    if m2:
        h = int(m2.group(1))
        mi = int(m2.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            hour, minute = h, mi
        else:
            minute = 0
    else:
        minute = 0

    if hour is not None:
        dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return _fmt(dt), desc


def parse_measurements(text: str) -> list[dict]:
    """从文本中抽取可入库的测量记录。"""
    out: list[dict] = []
    ts, desc = parse_time(text)

    # ---- 血压 ----
    bp_done = False
    for pat in BP_PATTERNS:
        for m in pat.finditer(text):
            try:
                sys_v, dia_v = float(m.group(1)), float(m.group(2))
            except (TypeError, ValueError):
                continue
            if 40 <= sys_v <= 300 and 20 <= dia_v <= 200:
                out.append({
                    "kind": "bp", "sub_kind": None, "val1": sys_v, "val2": dia_v,
                    "unit": "mmHg", "measured_at": ts, "raw": m.group(0).strip(),
                    "time_desc": desc,
                })
                bp_done = True
                break
        if bp_done:
            break

    # ---- 血糖 ----
    if "血糖" in text:
        for m in re.finditer(rf"血糖[^\d]{{0,8}}{NUM}", text):
            v = float(m.group(1))
            if not (0.5 <= v <= 40):
                continue
            if re.search(r"餐后|饭后|服糖后|ogtt", text):
                sub = "postprandial"
            elif re.search(r"空腹|餐前|早饭前|早餐前", text):
                sub = "fasting"
            else:
                sub = "random"
            out.append({
                "kind": "glucose", "sub_kind": sub, "val1": v, "val2": None,
                "unit": "mmol/L", "measured_at": ts, "raw": m.group(0).strip(),
                "time_desc": desc,
            })
            break

    # ---- 糖化血红蛋白 ----
    m = re.search(rf"(?:糖化血红蛋白|糖化|HbA1c)\s*(?:是|为|:|：)?\s*{NUM}\s*%?", text, re.I)
    if m:
        v = float(m.group(1))
        if 2 <= v <= 20:
            out.append({"kind": "hba1c", "sub_kind": None, "val1": v, "val2": None,
                        "unit": "%", "measured_at": ts, "raw": m.group(0).strip(),
                        "time_desc": desc})

    # ---- 血脂 ----
    for pat, sub, label, unit in LIPID_KEYS:
        m = re.search(rf"(?:{pat})[^\d]{{0,8}}{NUM}", text, re.I)
        if m:
            v = float(m.group(1))
            if 0.1 <= v <= 30:
                out.append({"kind": "lipid", "sub_kind": sub, "val1": v, "val2": None,
                            "unit": unit, "measured_at": ts, "raw": m.group(0).strip(),
                            "label": label, "time_desc": desc})

    # ---- 体重 ----
    m = re.search(rf"体重[^\d]{{0,6}}{NUM}\s*(kg|公斤|千克|斤)?", text, re.I)
    if m:
        v = float(m.group(1))
        if (m.group(2) == "斤"):
            v = round(v / 2, 1)
        if 20 <= v <= 300:
            out.append({"kind": "weight", "sub_kind": None, "val1": v, "val2": None,
                        "unit": "kg", "measured_at": ts, "raw": m.group(0).strip(),
                        "time_desc": desc})

    # ---- 腰围 ----
    m = re.search(rf"腰围[^\d]{{0,6}}{NUM}\s*(cm|厘米)?", text, re.I)
    if m:
        v = float(m.group(1))
        if 30 <= v <= 200:
            out.append({"kind": "waist", "sub_kind": None, "val1": v, "val2": None,
                        "unit": "cm", "measured_at": ts, "raw": m.group(0).strip(),
                        "time_desc": desc})

    return out


DRUG_HINTS = [
    "氨氯地平", "硝苯地平", "非洛地平", "依那普利", "培哚普利", "贝那普利", "缬沙坦",
    "氯沙坦", "厄贝沙坦", "替米沙坦", "氢氯噻嗪", "吲达帕胺", "螺内酯", "呋塞米",
    "美托洛尔", "比索洛尔", "阿托伐他汀", "瑞舒伐他汀", "辛伐他汀", "普伐他汀",
    "非诺贝特", "依折麦布", "二甲双胍", "格列美脲", "格列齐特", "阿卡波糖",
    "达格列净", "恩格列净", "司美格鲁肽", "利拉鲁肽", "甘精胰岛素", "门冬胰岛素",
    "阿司匹林", "氯吡格雷", "华法林", "布洛芬", "甘草片", "别嘌醇", "非布司他",
    "左甲状腺素", "克拉霉素", "胺碘酮", "泼尼松", "低钠盐", "西柚",
]


CN_NUM = {"半": 0.5, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
DOSE_UNIT = r"(片|粒|袋|支|单位|毫升|ml|毫克|mg|克|g)"


def _fmt_dose(num: str, unit: str) -> str:
    unit = unit.lower()
    value = CN_NUM.get(num)
    if value is None:
        try:
            value = float(num)
        except ValueError:
            value = None
    if value is None:
        return f"{num} {unit}"
    text = f"{value:g}"
    if unit in ("片", "粒", "袋", "支", "单位"):
        return f"{text} {unit}"
    return f"{text} {'mg' if unit in ('mg', '毫克') else ('g' if unit in ('g', '克') else unit)}"


def parse_medications(text: str) -> list[dict]:
    out: list[dict] = []
    for name in DRUG_HINTS:
        if name not in text:
            continue
        dose = ""
        # 药名之后：氨氯地平 5 mg / 二甲双胍 0.5g
        m = re.search(rf"{name}[^\d\n]{{0,4}}(\d+(?:\.\d+)?|半|一|两|二|三)\s*{DOSE_UNIT}", text, re.I)
        if m:
            dose = _fmt_dose(m.group(1), m.group(2))
        else:
            # 药名之前：吃了一片氨氯地平 / 两粒二甲双胍
            m = re.search(rf"(\d+(?:\.\d+)?|半|一|两|二|三)\s*{DOSE_UNIT}[^\d，。；\n]{{0,8}}{name}", text, re.I)
            if m:
                dose = _fmt_dose(m.group(1), m.group(2))
        out.append({"name": name, "dose": dose, "raw": name})
    return out


INTENT_KEYWORDS = {
    "plan": ["方案", "计划", "食谱", "吃什么", "怎么吃", "安排", "一周", "7天", "七天",
             "明天", "早餐", "午餐", "晚餐", "配餐", "菜单"],    "report": ["报告", "周报", "总结", "汇总", "月报", "复盘"],
    "interaction": ["一起吃", "相互作用", "冲突", "同服", "相克", "能同时", "配着吃",
                    "用药安全", "副作用", "不良反应", "忌口"],
    "query_trend": ["趋势", "变化", "最近", "近来", "这段时间", "怎么样", "控制得",
                    "稳定", "波动", "平均值", "波动大"],
    "query_latest": ["上次", "最近一次", "刚才", "上一次"],
    "profile": ["我的档案", "我有什么病", "我在吃什么药", "我的情况", "病史", "我是谁"],
    "record": ["记录", "记一下", "录入", "存一下", "添加"],
    "lab": ["检验单", "化验单", "报告单", "体检报告", "生化", "化验结果", "化验"],
    "task": ["今天任务", "待办", "打卡", "任务清单"],
    "kb": ["为什么", "是什么", "怎么办", "注意什么", "能不能吃", "可以吃", "禁忌",
           "原理", "区别", "标准", "指标", "多少算", "正常范围", "指南"],
}


def detect_intent(text: str) -> tuple[str, float, dict]:
    """返回 (意图, 置信度, 详情)。"""
    t = (text or "").strip()
    if not t:
        return "unknown", 0.0, {}

    if re.search(r"^(你好|您好|hi|hello|在吗|早上好|晚上好)", t, re.I):
        return "greeting", 0.9, {}

    measurements = parse_measurements(t)
    meds = parse_medications(t)

    scores: dict[str, float] = {}
    for intent, words in INTENT_KEYWORDS.items():
        hit = [w for w in words if w in t]
        if hit:
            scores[intent] = scores.get(intent, 0) + min(3, len(hit)) * 1.0

    # 检验单/化验单：优先级高于逐条记录（一份报告里往往有多个数字）
    if re.search(r"(检验单|化验单|报告单|检验报告|化验报告|生化|体检报告)", t):
        scores["lab"] = scores.get("lab", 0) + 4.5

    # 有数值测量但没说是查询 → 记录
    if measurements:
        if not any(k in t for k in ("趋势", "怎么样", "平均", "变化")):
            scores["record"] = scores.get("record", 0) + 3.5

    if meds and re.search(r"吃|服|用", t):
        if not re.search(r"一起吃|能同服|相互作用|冲突", t):
            scores["med_record"] = scores.get("med_record", 0) + 3.0

    if len(meds) >= 2 or re.search(r"一起吃|同服|冲突|相克", t):
        scores["interaction"] = scores.get("interaction", 0) + 3.0

    if re.search(r"今天.{0,4}(做什么|干什么|安排什么|有什么任务|要干什么|该干啥)", t):
        scores["task"] = scores.get("task", 0) + 3.0

    # 用药计划变更（写入/修改/移除打卡安排），优先级高于「今天吃了一次」的记录
    med_plan = parse_med_plan(t)
    if med_plan:
        scores["med_plan"] = scores.get("med_plan", 0) + 5.0
        scores.pop("med_record", None)

    if re.search(r"(我的药|我的用药|用药清单|吃药要注意|药有没有(冲突|问题)|这些药)", t):
        scores["interaction"] = scores.get("interaction", 0) + 3.0

    if re.search(r"(怎么|如何).{0,4}(办|处理|办)", t) and not measurements:
        scores.setdefault("kb", 0)
        scores["kb"] += 1.0

    if not scores:
        return "kb", 0.55, {"measurements": measurements, "medications": meds, "med_plan": med_plan}

    intent = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1
    conf = round(min(0.98, 0.45 + scores[intent] / (total + 1.2)), 2)
    return intent, conf, {"measurements": measurements, "medications": meds,
                          "scores": scores, "med_plan": med_plan}


# ---------------------------------------------------------------- 用药计划
# 周期性表达：出现这些词才认为是"安排"，否则只是"今天吃了一次"
RECUR_WORDS = ("每天", "每日", "每晚", "每早", "每次", "一日", "长期", "以后", "从今天起",
               "常规", "平时", "一直", "固定")
PLAN_VERBS = ("改成", "改为", "调整为", "调整成", "加入", "加进", "加上", "安排", "设定",
              "设个提醒", "记到", "录入到", "改到")
# 明确表示「整体替换」的说法；没有这些词时一律按「合并去重」处理
REPLACE_VERBS = ("改成", "改为", "调整为", "调整成", "改到")
STOP_PATTERN = re.compile(
    r"(停(用|掉|药)|不(再|用|需要|想|打算)?吃|不用吃|不需要吃|删(掉|除)|移(除|出|走)|去掉|取消)")
ADVICE_QUESTION = re.compile(r"(能不能|可不可以|能否|要不要|该不该|是不是可以|是否)")


def _fmt_hm(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d}"


PERIOD_DEFAULT = {
    "早上": 8, "早晨": 8, "上午": 8, "中午": 12, "下午": 15,
    "傍晚": 19, "晚上": 19, "晚间": 19, "晚": 19, "夜里": 22, "睡前": 22,
}
CLOCK_RE = re.compile(
    r"(早上|早晨|上午|中午|下午|傍晚|晚上|晚间|睡前|夜里|晚)?\s*"
    r"(\d{1,2})\s*(?:[:：]\s*(\d{1,2})|[点时](?:\s*(\d{1,2})\s*分|\s*半)?)")


def parse_schedule(text: str) -> tuple[list[str], str]:
    """从一句话里抽出服药时间点，返回 (["08:00", ...], 描述)。

    支持混写：「8点、12点、18点、21点、睡前」「早上8:30、晚上9点」「每天8:00,12:00」。
    先抓带钟点的表达，再在剩下的文字里补「没有钟点」的时段词，
    避免「睡前」被前面的几个点挤掉（这正是之前"只能设 4 个时段"的原因）。
    """
    times: list[str] = []

    # 频次表达优先（这类说法没有具体钟点）
    if re.search(r"(一天|每日|每天)?\s*(两|2)\s*次|早晚各|早中各|中午和晚上|bid", text, re.I):
        return ["08:00", "19:00"], "每日 2 次（早、晚）"
    if re.search(r"(一天|每日|每天)?\s*(三|3)\s*次|早中晚", text, re.I):
        return ["08:00", "12:00", "19:00"], "每日 3 次（早、中、晚）"

    consumed: list[tuple[int, int]] = []
    for m in CLOCK_RE.finditer(text):
        period = m.group(1) or ""
        hh = int(m.group(2))
        if m.group(3) is not None:           # 8:30
            minute = int(m.group(3))
        elif "半" in m.group(0):
            minute = 30
        elif m.group(4) is not None:         # 8点30分
            minute = int(m.group(4))
        else:
            minute = 0
        if period in ("下午", "傍晚", "晚上", "晚间", "晚") and hh < 12:
            hh += 12
        if period == "中午" and hh < 11:
            hh += 12
        if not (0 <= hh <= 23 and 0 <= minute <= 59):
            continue
        times.append(_fmt_hm(hh, minute))
        consumed.append((m.start(), m.end()))

    # 在剩余文字里补没有钟点的时段词
    if consumed:
        masked = list(text)
        for s, e in consumed:
            for i in range(s, min(e, len(masked))):
                masked[i] = " "
        rest = "".join(masked)
    else:
        rest = text
    for word, hour in PERIOD_DEFAULT.items():
        if word in rest:
            times.append(_fmt_hm(hour))

    times = sorted(dict.fromkeys(times))[:8]
    if not times:
        return [], ""
    desc = f"每日 {len(times)} 次（{'、'.join(times)}）" if len(times) > 1 else f"每日 1 次（{times[0]}）"
    return times, desc


def parse_med_plan(text: str) -> dict | None:
    """判断这句话是不是在"安排用药"（而非只记录今天吃了一次）。

    返回 {action: "upsert"|"stop", items:[{name,dose,times}], desc, caution}
    """
    t = (text or "").strip()
    if not t:
        return None
    meds = parse_medications(t)
    if not meds:
        return None

    is_stop = bool(STOP_PATTERN.search(t))
    # 问句（能不能停药/减量）交给处方红线处理，不当作计划变更
    if is_stop and ADVICE_QUESTION.search(t):
        return None

    times, sched_desc = parse_schedule(t)
    has_recur = any(w in t for w in RECUR_WORDS)
    has_verb = any(w in t for w in PLAN_VERBS)

    if is_stop:
        action = "stop"
    elif has_recur or has_verb:
        action = "upsert"
    else:
        return None

    items = []
    seen = set()
    global_times, global_desc = times, sched_desc

    # 逐句解析：让「早上 8 点吃 A，晚上 9 点吃 B」各归各的时间
    for seg in re.split(r"[，,；;。\n]+", t):
        seg_meds = parse_medications(seg)
        if not seg_meds:
            continue
        seg_times, _ = parse_schedule(seg)
        for m in seg_meds:
            if m["name"] in seen:
                continue
            seen.add(m["name"])
            use_times = seg_times or global_times
            items.append({
                "name": m["name"],
                "dose": m.get("dose") or "",
                "times": [] if action == "stop" else (use_times or ["08:00"]),
            })

    # 兜底：整句里识别到药名但分段没匹配上
    if not items:
        for m in meds:
            items.append({"name": m["name"], "dose": m.get("dose") or "",
                          "times": [] if action == "stop" else (times or ["08:00"])})

    # 描述文案：时间一致就说次数，不一致就逐个列
    if action == "upsert" and items:
        tset = {tuple(i["times"]) for i in items}
        if len(tset) == 1:
            t0 = sorted(tset)[0]
            sched_desc = (f"每日 {len(t0)} 次（{'、'.join(t0)}）" if len(t0) > 1
                          else f"每日 1 次（{t0[0]}）")
        else:
            sched_desc = "；".join(f"{i['name']} {'、'.join(i['times'])}" for i in items)

    caution = ""
    if action == "stop":
        caution = ("如果这不是医生要求的，请不要自行停药。我只会把它从「用药打卡」清单里移除，"
                   "不改变任何医疗建议。")
    elif not times:
        caution = "没有听清具体时间，先按 08:00 安排；如果你想改时间，直接说“改成晚上 8 点”。"

    return {
        "action": action,
        "op": "replace" if any(v in t for v in REPLACE_VERBS) else "merge",
        "items": items,
        "times": times,
        "desc": sched_desc or ("从清单移除" if action == "stop" else "每日 1 次（08:00）"),
        "caution": caution,
    }


def parse_profile_update(text: str) -> dict:
    """从对话中抽取可更新档案的字段。"""
    upd: dict = {}
    m = re.search(r"我(?:今年)?\s*(\d{1,2})\s*岁", text)
    if m:
        age = int(m.group(1))
        if 10 <= age <= 110:
            upd["birth_year"] = now().year - age
    m = re.search(r"身高\s*(\d{2,3})(?:\.\d+)?\s*(cm|厘米)?", text)
    if m:
        h = float(m.group(1))
        if 100 <= h <= 220:
            upd["height_cm"] = h
    for key, cond in (("高血压", "高血压"), ("糖尿病", "糖尿病"), ("血糖高", "糖尿病"),
                      ("血脂异常", "血脂异常"), ("血脂高", "血脂异常"),
                      ("高尿酸", "高尿酸血症"), ("痛风", "高尿酸血症")):
        if key in text and re.search(r"有|患|得了|是", text):
            upd.setdefault("conditions_add", []).append(cond)
    if re.search(r"不会做饭|不做饭|没时间做饭|点外卖|外面吃", text):
        upd["can_cook"] = 0
    if re.search(r"一个人住|独居|自己住", text):
        upd["family_support"] = 0
    if re.search(r"预算|省钱|便宜", text):
        upd["budget"] = "low"
    if re.search(r"口味重|爱吃咸|喜欢咸", text):
        upd["taste"] = "salty"
    elif re.search(r"清淡|口味淡", text):
        upd["taste"] = "light"
    elif re.search(r"爱吃辣|喜欢辣", text):
        upd["taste"] = "spicy"
    return upd
