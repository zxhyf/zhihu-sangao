# -*- coding: utf-8 -*-
"""口语词表：把中老年人的日常说法，映射到系统认识的规范表达。

**它不参与知识检索**，只在两处使用：
1. 识别数值时的部位词（高压/上压 → 收缩压，低压/下压 → 舒张压）
2. 意图识别时的同义说法（"漏吃了" → 用药咨询，"能不能一起吃" → 药物联动）

放进知识库会被当成"医学证据"返回给用户，这是错的，所以单独成模块。
"""
from __future__ import annotations

import re

# 血压部位
SYS_WORDS = ("高压", "上压", "收缩压", "上面的血压")
DIA_WORDS = ("低压", "下压", "舒张压", "下面的血压")

# 指标别称
GLUCOSE_WORDS = ("血糖", "空腹血糖", "餐后血糖", "随机血糖", "指尖血")
HBA1C_WORDS = ("糖化", "糖化血红蛋白", "hba1c", "a1c", "糖化血色素")
LIPID_WORDS = ("血脂", "胆固醇", "甘油三酯", "低密度", "高密度", "ldl", "hdl", "tg", "tc")
WEIGHT_WORDS = ("体重", "称重", "胖了", "瘦了")

# 症状口语 → 规范化（供安全网关与提示使用）
SYMPTOM_MAP = {
    "胸口疼": "胸痛",
    "胸口痛": "胸痛",
    "心口疼": "胸痛",
    "心口痛": "胸痛",
    "胸闷": "胸闷",
    "上不来气": "呼吸困难",
    "喘不上气": "呼吸困难",
    "喘不过气": "呼吸困难",
    "憋气": "呼吸困难",
    "喘": "呼吸困难",
    "嘴歪": "口角歪斜",
    "说话不清": "言语不清",
    "大舌头": "言语不清",
    "半边身子麻": "一侧肢体无力",
    "一只手麻": "一侧肢体麻木",
    "腿没劲": "一侧肢体无力",
    "眼前发黑": "黑矇",
    "看东西重影": "视物重影",
    "心里发慌": "心悸",
    "心慌": "心悸",
    "出冷汗": "大汗",
    "恶心想吐": "恶心呕吐",
    "拉黑便": "黑便",
    "吐了": "呕吐",
}

# 意图同义说法（只做提示，最终仍由规则/模型判断）
INTENT_HINTS = {
    "med_missed": ("漏吃", "忘了吃", "忘记吃", "漏服", "少吃了一次"),
    "interaction": ("能不能一起吃", "一起吃行吗", "相冲", "冲突", "同吃"),
    "risk_query": ("严重吗", "要紧吗", "危险吗", "高不高", "是不是很高"),
    "stop_med": ("停药", "不吃了", "断药", "停一停"),
}


def normalize_measure_text(text: str) -> str:
    """把口语里的部位词换成规范说法，便于后续正则抽取。"""
    out = text
    for w in SYS_WORDS[:-1]:
        out = out.replace(w, "收缩压")
    for w in DIA_WORDS[:-1]:
        out = out.replace(w, "舒张压")
    return out


def normalize_symptoms(text: str) -> str:
    """把口语症状替换为规范词，供安全网关匹配（原始文本仍保留在对话里）。"""
    out = text
    for k, v in SYMPTOM_MAP.items():
        out = out.replace(k, v)
    return out


def matched_intents(text: str) -> list[str]:
    low = (text or "").lower()
    return [name for name, words in INTENT_HINTS.items() if any(w in low for w in words)]


def is_hba1c_mention(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in HBA1C_WORDS)


def is_lipid_mention(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in LIPID_WORDS)


def strip_filler(text: str) -> str:
    """去掉“那个/就是/嗯”这类填充词，提升正则命中率。"""
    return re.sub(r"(那个|这个|就是|嗯|啊|呀|呢|吧)", "", text or "")
