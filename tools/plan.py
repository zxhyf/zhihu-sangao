# -*- coding: utf-8 -*-
"""7 日可执行方案生成器。

设计目标（对应方案“从记录到可执行”）：
1. 每条建议都落到「几点 + 吃什么/做什么 + 多少量」；
2. 尊重用户真实约束：会不会做饭、预算、口味、作息、家人是否帮忙；
3. 所有餐食依据《中国居民膳食指南（2022）》与三高相关指南的食物量与限盐限油标准；
4. 明确标注这是健康管理参考，不是治疗处方。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from config import DEFAULT_USER
from tools import profile as profile_tool

DISHES_BREAKFAST = [
    {
        "main": "燕麦片 40 g 用低脂牛奶 250 mL 冲泡",
        "protein": "水煮蛋 1 个（约 50 g）",
        "veg": "凉拌黄瓜 100 g（用醋和蒜末调味，不放盐）",
        "note": "燕麦选无糖原味，不要即食甜味麦片",
        "cook": 1,
    },
    {
        "main": "全麦馒头 50 g（约半个）",
        "protein": "无糖豆浆 300 mL + 茶叶蛋 1 个",
        "veg": "焯拌菠菜 100 g（滴几滴香油）",
        "note": "豆浆选无糖，包装豆浆注意看配料表有没有白砂糖",
        "cook": 1,
    },
    {
        "main": "荞麦面 50 g（生重），配番茄 150 g、鸡蛋 1 个做卤",
        "protein": "卤中的鸡蛋 1 个",
        "veg": "配一小碟凉拌木耳 50 g（泡发后重量）",
        "note": "面条煮到八分熟即可，别煮太烂，升糖更快",
        "cook": 1,
    },
    {
        "main": "杂粮饭 60 g（生重，糙米+小米+燕麦米各 20 g）",
        "protein": "水煮蛋 1 个 + 低脂牛奶 200 mL",
        "veg": "清炒小油菜 100 g（油 3 g）",
        "note": "杂粮饭可以一次煮 3 天量，分装冷藏，早上微波加热",
        "cook": 1,
    },
    {
        "main": "全麦面包 50 g（2 片）",
        "protein": "无糖酸奶 150 g + 水煮蛋 1 个",
        "veg": "圣女果 100 g",
        "note": "便利店就能买到；面包选配料表第一位是全麦粉的",
        "cook": 0,
    },
    {
        "main": "小米粥 250 g（小米 25 g）",
        "protein": "蒸蛋羹 1 个蛋 + 豆腐干 30 g",
        "veg": "凉拌海带丝 50 g（先清水泡 20 分钟去盐）",
        "note": "血糖偏高者把粥换成杂粮饭 50 g，粥的升糖速度更快",
        "cook": 1,
    },
]

DISHES_LUNCH = [
    {
        "main": "杂粮饭 75 g（生重）",
        "protein": "清蒸鲈鱼 80 g（姜丝、葱段，蒸 8 分钟）",
        "veg": "蒜蓉西兰花 200 g + 冬瓜汤 1 小碗（不放盐）",
        "note": "鱼每周吃 2 次，补充 n-3 脂肪酸",
        "cook": 1,
    },
    {
        "main": "二米饭 70 g（生重，大米+糙米）",
        "protein": "香菇滑鸡 80 g（鸡腿肉去皮）",
        "veg": "清炒油麦菜 200 g + 番茄豆腐汤（豆腐 50 g）",
        "note": "鸡肉去皮能减少约 1/3 的脂肪",
        "cook": 1,
    },
    {
        "main": "荞麦面 75 g（生重）",
        "protein": "牛肉丝 50 g（用淀粉抓一下，少油快炒）",
        "veg": "焯拌绿豆芽 200 g + 黄瓜丝 50 g",
        "note": "面汤别喝完，汤里盐最多",
        "cook": 1,
    },
    {
        "main": "糙米饭 75 g（生重）",
        "protein": "白灼虾 80 g（约 6 只，蘸醋不蘸酱油）",
        "veg": "蒜蓉菠菜 200 g + 紫菜蛋花汤（不放盐，紫菜本身有咸味）",
        "note": "虾的胆固醇集中在头部，去头吃更稳妥",
        "cook": 1,
    },
    {
        "main": "米饭 60 g（生重）+ 玉米 50 g",
        "protein": "番茄炒蛋（2 个蛋，少油）",
        "veg": "清炒圆白菜 200 g",
        "note": "食堂打菜时让师傅“少油少盐、汤汁分开装”",
        "cook": 0,
    },
    {
        "main": "杂粮饭 75 g（生重）",
        "protein": "清炖鸡胸肉 80 g（加姜片、料酒去腥）",
        "veg": "凉拌莴笋丝 150 g + 白灼芥蓝 150 g",
        "note": "鸡胸肉一次煮 3 块，撕成丝冷藏，拌菜直接用",
        "cook": 1,
    },
]

DISHES_DINNER = [
    {
        "main": "小米+大米饭 50 g（生重）",
        "protein": "家常豆腐 100 g（北豆腐，煎后少油烧）",
        "veg": "清炒芥蓝 200 g",
        "note": "晚餐主食控制在 50 g 生重，睡前 3 小时不再进食",
        "cook": 1,
    },
    {
        "main": "杂粮饭 50 g（生重）",
        "protein": "清蒸带鱼 80 g",
        "veg": "清炒西葫芦 200 g",
        "note": "带鱼选新鲜的，不要买腌制的咸带鱼",
        "cook": 1,
    },
    {
        "main": "蒸红薯 100 g",
        "protein": "白灼鸡胸肉 80 g（撕成丝，用柠檬汁和黑胡椒拌）",
        "veg": "凉拌木耳 100 g + 清炒生菜 200 g",
        "note": "红薯要计入主食，吃了红薯就少吃米饭",
        "cook": 1,
    },
    {
        "main": "蒸玉米 100 g（约 1 根）",
        "protein": "番茄牛肉（牛肉 60 g）",
        "veg": "炒生菜 200 g",
        "note": "牛肉选里脊，切薄片快炒，口感嫩且用油少",
        "cook": 1,
    },
    {
        "main": "杂粮饭 50 g（生重）",
        "protein": "香菇豆腐煲（豆腐 100 g、香菇 30 g）",
        "veg": "蒜蓉空心菜 200 g",
        "note": "素食日，用香菇提鲜可以少放盐",
        "cook": 1,
    },
    {
        "main": "荞麦面 50 g（生重）",
        "protein": "虾仁 60 g 滑蛋（1 个蛋）",
        "veg": "焯拌秋葵 150 g",
        "note": "秋葵的黏液有助延缓糖吸收，别焯太久",
        "cook": 1,
    },
]

SNACKS = [
    ("苹果 100 g（约半个）", "两餐之间吃，不要饭后立刻吃"),
    ("无糖酸奶 100 g + 核桃 5 g（约 1 个）", "坚果每天不超过 10 g"),
    ("黄瓜 100 g 或 小番茄 100 g", "嘴馋时先吃蔬菜"),
    ("低脂牛奶 150 mL", "睡前 1 小时喝，有助避免夜间饥饿"),
    ("梨 100 g", "水果放在两餐之间，每次 100 g 左右"),
    ("水煮毛豆 50 g", "补充植物蛋白，注意别加盐"),
]

EXERCISE = [
    ("快走 30 分钟（约 3000 步，能说话但唱不了歌的强度）", "避开清晨血压高峰，晚饭后 1 小时最合适"),
    ("太极拳或八段锦 15 分钟 + 靠墙静蹲 30 秒 × 3 组", "动作缓慢，扶着椅背做更安全"),
    ("室内原地踏步 10 分钟 × 2 次 + 坐站训练 10 次 × 3 组", "下雨天在家做，穿防滑鞋"),
    ("快走 20 分钟 + 弹力带划船 12 次 × 3 组", "抗阻训练不要憋气，呼气时发力"),
    ("广场舞或健身操 30 分钟", "以微微出汗、不喘不上气为宜"),
    ("快走 25 分钟 + 单脚站立（扶墙）30 秒 × 2 组", "平衡训练能降低跌倒风险"),
    ("散步 40 分钟（分两次，饭后各 20 分钟）", "饭后散步有助于降低餐后血糖"),
]

SALT_TIPS = [
    "今天用限盐勺，全天食盐不超过 5 g（约 1 个啤酒瓶盖）",
    "用醋、柠檬汁、葱姜蒜、花椒、香菇代替部分咸味",
    "酱油 6 mL 就等于 1 g 盐，今天做菜只放 1 勺",
    "看包装营养成分表，选钠 <120 mg/100 g 的食品",
    "不吃咸菜、腐乳、香肠，汤只喝料不喝汤",
    "在外吃饭要求少油少盐，菜过一遍热水再吃",
    "低钠盐要谨慎：正在吃 ACEI/ARB 或螺内酯者先问医生",
]

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _pick(seq: list, i: int) -> dict:
    return seq[i % len(seq)]


def _ingredients(text: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z]{2,6})\s*(\d+(?:\.\d+)?)\s*(g|mL|ml|个|片)", text):
        out.append((m.group(1).strip(), f"{m.group(2)} {m.group(3)}"))
    return out


def generate(user_id: str = DEFAULT_USER, days: int = 7) -> dict:
    p = profile_tool.get_profile(user_id)
    conds = p.get("conditions") or []
    has_dm = any("糖尿病" in c for c in conds)
    has_htn = any("高血压" in c for c in conds)
    has_lipid = any("血脂异常" in c for c in conds)
    has_ua = any("尿酸" in c for c in conds)
    can_cook = int(p.get("can_cook") or 0)
    budget = p.get("budget") or "normal"
    taste = p.get("taste") or "normal"
    wake = p.get("wake_time") or "06:30"
    sleep = p.get("sleep_time") or "22:30"

    def hhmm(base: str, delta_min: int) -> str:
        h, m = base.split(":")
        total = int(h) * 60 + int(m) + delta_min
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"

    t_wake = wake
    t_breakfast = hhmm(wake, 30)
    t_snack1 = hhmm(wake, 210)
    t_lunch = "12:00"
    t_snack2 = "15:30"
    t_dinner = "18:00"
    t_walk = "19:00"
    t_med_am = "08:00"
    t_med_pm = "18:00"
    t_sleep = sleep

    start = datetime.now() + timedelta(days=1)
    day_plans = []
    all_text: list[str] = []

    for i in range(days):
        d = start + timedelta(days=i)
        items: list[dict] = []

        b = _pick(DISHES_BREAKFAST, i)
        if not can_cook:
            b = _pick([x for x in DISHES_BREAKFAST if x["cook"] == 0] or DISHES_BREAKFAST, i)
        lu = _pick(DISHES_LUNCH, i)
        di = _pick(DISHES_DINNER, i)
        if can_cook == 0:
            lu = {**lu, "note": "在外就餐：选蒸、煮、白灼的菜，主食减半，菜过水去油"}

        breakfast_text = f"{b['main']}；{b['protein']}；{b['veg']}"
        lunch_text = f"{lu['main']}；{lu['protein']}；{lu['veg']}"
        dinner_text = f"{di['main']}；{di['protein']}；{di['veg']}"
        snack = _pick(SNACKS, i)
        ex = _pick(EXERCISE, i)

        items.append({"time": t_wake, "category": "measure", "title": "起床后先测量",
                      "content": "排尿后、服药前、早餐前测血压（坐位静息 5 分钟，测 2 遍取平均）"})
        items.append({"time": t_breakfast, "category": "meal", "title": "早餐",
                      "content": breakfast_text, "note": b["note"]})
        items.append({"time": t_med_am, "category": "med", "title": "早间服药",
                      "content": "按医嘱服药，服完在“用药打卡”里点一下"})
        items.append({"time": t_snack1, "category": "meal", "title": "上午加餐",
                      "content": snack[0], "note": snack[1]})
        items.append({"time": t_lunch, "category": "meal", "title": "午餐",
                      "content": lunch_text, "note": lu["note"]})
        if has_dm:
            items.append({"time": hhmm(t_lunch, 120), "category": "measure", "title": "餐后 2 小时血糖",
                          "content": "从吃第一口饭开始计时，满 2 小时测血糖"})
        items.append({"time": t_snack2, "category": "meal", "title": "下午加餐",
                      "content": _pick(SNACKS, i + 2)[0], "note": "加餐是为了避免晚餐前过饿而吃多"})
        items.append({"time": t_dinner, "category": "meal", "title": "晚餐",
                      "content": dinner_text, "note": di["note"]})
        items.append({"time": t_walk, "category": "exercise", "title": "运动",
                      "content": ex[0], "note": ex[1]})
        items.append({"time": hhmm(t_dinner, 180), "category": "measure", "title": "睡前血压",
                      "content": "睡前测一次血压并记录；如果今天头晕、心慌，把感受也写下来"})
        items.append({"time": t_sleep, "category": "sleep", "title": "准备睡觉",
                      "content": "睡前 1 小时不看手机，保证 7 小时睡眠（睡眠不足会升高血压）"})

        items.sort(key=lambda x: x["time"])
        day_plans.append({
            "date": d.strftime("%Y-%m-%d"),
            "weekday": WEEKDAYS[d.weekday()],
            "items": items,
        })
        all_text.extend([breakfast_text, lunch_text, dinner_text, snack[0]])

    # 购物清单
    agg: dict[str, float] = {}
    units: dict[str, str] = {}
    for name, qty in [x for t in all_text for x in _ingredients(t)]:
        num = float(re.findall(r"[\d.]+", qty)[0])
        unit = re.findall(r"[a-zA-Z个片]+", qty)[0]
        if unit in ("mL", "ml"):
            unit = "ml"
        key = f"{name}"
        if units.get(key) and units[key] != unit:
            continue
        units[key] = unit
        agg[key] = agg.get(key, 0) + num
    shopping = [{"item": k, "qty": f"{round(v, 1):g} {units[k]}"} for k, v in
                sorted(agg.items(), key=lambda x: -x[1])][:24]

    tips: list[str] = []
    if has_htn:
        tips.append("限盐是第一优先：全天食盐 <5 g，警惕酱油、腐乳、咸菜等隐形盐。")
    if has_dm:
        tips.append("主食定量并固定，全谷物占 1/3 以上；进餐顺序调整为蔬菜 → 蛋白 → 主食。")
    if has_lipid:
        tips.append("每日烹调油 25–30 g，每周吃 2 次鱼，少吃油炸食品和动物内脏。")
    if has_ua:
        tips.append("限制动物内脏、浓肉汤、啤酒和部分海鲜；每天饮水 2000 mL 以上（无心衰、无水肿时）。")
    if taste == "salty":
        tips.append("口味偏咸可以分两步减盐：先减 1/4，两周后再减 1/4，味觉会慢慢适应。")
    if budget == "low":
        tips.append("预算有限时优先选鸡蛋、豆腐、白菜、土豆、鸡胸肉，蛋白质一样够。")
    if not can_cook:
        tips.append("不做饭也能执行：便利店选无糖酸奶 + 全麦面包 + 水煮蛋，食堂要求少油少盐、汤汁分装。")
    tips.append(_pick(SALT_TIPS, 0))

    return {
        "ok": True,
        "title": f"{days} 日可执行方案",
        "profile": {
            "name": p.get("name"),
            "age": p.get("age"),
            "conditions": conds,
            "bmi": p.get("bmi"),
            "can_cook": bool(can_cook),
            "budget": budget,
            "taste": taste,
        },
        "days": day_plans,
        "shopping": shopping,
        "tips": tips,
        "basis": [
            "《中国居民膳食指南（2022）》每日食物推荐量与限盐限油标准",
            "《中国高血压防治指南（2024年修订版）》生活方式干预",
            "《中国糖尿病防治指南（2024版）》主食定量与进餐顺序",
            "《中国血脂管理指南（2023年）》膳食脂肪调整",
        ],
        "disclaimer": "方案为健康管理参考，不替代医生与营养师的个体化处方；有肾功能不全、心衰、痛风急性期等情况请先咨询医生。",
    }
