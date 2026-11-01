# -*- coding: utf-8 -*-
"""指标风险分级：把一次测量映射到 正常 / 警戒 / 危险 / 急症 四级，并可回溯到指南条目。

分级只做“是否超出指南参考范围”的提示，不设定个人目标值、不计算达标率。
"""
from __future__ import annotations

LEVELS = {
    "normal": {"label": "正常", "color": "#16a34a", "emoji": "✅", "rank": 0},
    "watch": {"label": "警戒", "color": "#d97706", "emoji": "⚠️", "rank": 1},
    "danger": {"label": "危险", "color": "#dc2626", "emoji": "🔴", "rank": 2},
    "emergency": {"label": "急症", "color": "#7f1d1d", "emoji": "🚨", "rank": 3},
}

KIND_LABEL = {
    "bp": "血压",
    "glucose": "血糖",
    "lipid": "血脂",
    "weight": "体重",
    "waist": "腰围",
    "hba1c": "糖化血红蛋白",
    "bmi": "BMI",
}

SUB_LABEL = {
    "fasting": "空腹",
    "postprandial": "餐后 2 小时",
    "random": "随机",
    "tc": "总胆固醇",
    "tg": "甘油三酯",
    "ldl": "低密度脂蛋白胆固醇",
    "hdl": "高密度脂蛋白胆固醇",
}

GUIDE_REF = {
    "bp": "《中国高血压防治指南（2024年修订版）》血压分级",
    "glucose": "《中国糖尿病防治指南（2024版）》诊断与低血糖标准",
    "lipid": "《中国血脂管理指南（2023年）》血脂合适水平",
    "hba1c": "《中国糖尿病防治指南（2024版）》糖化血红蛋白目标",
    "weight": "《中国居民膳食指南（2022）》成人 BMI 分类",
    "waist": "《中国高血压防治指南（2024年修订版）》腰围标准",
}


def level_meta(level: str) -> dict:
    return LEVELS.get(level, LEVELS["normal"])


def classify_bp(sys_v: float, dia_v: float) -> dict:
    if sys_v < 90 or dia_v < 60:
        return {"level": "watch", "label": "血压偏低",
                "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 低于 90/60 mmHg，注意有无头晕、乏力、起身眼前发黑。",
                "ref": "诊室血压 <90/60 mmHg 为低血压范围"}
    if sys_v >= 180 or dia_v >= 110:
        return {"level": "emergency", "label": "3 级高血压范围",
                "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 达到 3 级高血压（≥180/110 mmHg），属于高血压急症警戒线。",
                "ref": "诊室血压 ≥180/110 mmHg 为 3 级"}
    if sys_v >= 160 or dia_v >= 100:
        return {"level": "danger", "label": "2 级高血压范围",
                "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 落在 160–179/100–109 mmHg 区间。",
                "ref": "2 级高血压：160–179/100–109 mmHg"}
    if sys_v >= 140 or dia_v >= 90:
        return {"level": "watch", "label": "1 级高血压范围",
                "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 落在 140–159/90–99 mmHg 区间。",
                "ref": "1 级高血压：140–159/90–99 mmHg"}
    if sys_v >= 120 or dia_v >= 80:
        return {"level": "normal", "label": "正常高值",
                "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 属于正常高值（120–139/80–89 mmHg），仍在参考范围内。",
                "ref": "正常高值：120–139/80–89 mmHg"}
    return {"level": "normal", "label": "正常范围",
            "detail": f"{sys_v:.0f}/{dia_v:.0f} mmHg 在 120/80 mmHg 以下。",
            "ref": "正常血压：<120/80 mmHg"}


def classify_glucose(v: float, sub: str = "random") -> dict:
    sub_label = SUB_LABEL.get(sub, "随机")
    if v < 3.0:
        return {"level": "emergency", "label": "严重低血糖",
                "detail": f"{sub_label}血糖 {v} mmol/L ≤3.0 mmol/L，属严重低血糖，需立即处理。",
                "ref": "血糖 <3.9 mmol/L 为低血糖，≤3.0 mmol/L 为严重低血糖"}
    if v < 3.9:
        return {"level": "emergency", "label": "低血糖",
                "detail": f"{sub_label}血糖 {v} mmol/L 低于 3.9 mmol/L，需立即补充 15 g 速效碳水。",
                "ref": "血糖 <3.9 mmol/L 为低血糖"}
    if v >= 16.7:
        return {"level": "emergency", "label": "显著高血糖",
                "detail": f"{sub_label}血糖 {v} mmol/L ≥16.7 mmol/L，存在酮症酸中毒风险。",
                "ref": "血糖 ≥16.7 mmol/L 需排查酮症"}
    if sub == "fasting":
        if v >= 7.0:
            return {"level": "danger", "label": "达糖尿病诊断阈值",
                    "detail": f"空腹血糖 {v} mmol/L ≥7.0 mmol/L，达到糖尿病诊断标准（需复查确认）。",
                    "ref": "空腹血糖 ≥7.0 mmol/L"}
        if v >= 6.1:
            return {"level": "watch", "label": "空腹血糖受损",
                    "detail": f"空腹血糖 {v} mmol/L 位于 6.1–6.9 mmol/L，属糖尿病前期。",
                    "ref": "空腹血糖 6.1–6.9 mmol/L 为 IFG"}
        return {"level": "normal", "label": "空腹血糖正常",
                "detail": f"空腹血糖 {v} mmol/L 在 3.9–6.1 mmol/L 参考范围内。",
                "ref": "空腹血糖参考范围 3.9–6.1 mmol/L"}
    if v >= 11.1:
        return {"level": "danger", "label": "餐后血糖明显升高",
                "detail": f"{sub_label}血糖 {v} mmol/L ≥11.1 mmol/L。",
                "ref": "餐后 2 小时血糖 ≥11.1 mmol/L"}
    if v >= 7.8:
        return {"level": "watch", "label": "餐后血糖偏高",
                "detail": f"{sub_label}血糖 {v} mmol/L 位于 7.8–11.0 mmol/L，属糖耐量减低范围。",
                "ref": "餐后 2 小时血糖 7.8–11.0 mmol/L 为 IGT"}
    return {"level": "normal", "label": "餐后血糖正常",
            "detail": f"{sub_label}血糖 {v} mmol/L <7.8 mmol/L，在参考范围内。",
            "ref": "餐后 2 小时血糖 <7.8 mmol/L"}


def classify_hba1c(v: float, has_diabetes: bool = False) -> dict:
    if v >= 9.0:
        return {"level": "danger", "label": "血糖长期控制不佳",
                "detail": f"HbA1c {v}% ≥9.0%，提示近 2–3 个月平均血糖明显偏高。",
                "ref": "多数成人目标 <7.0%，需医生个体化"}
    if v >= 6.5:
        return {"level": "watch", "label": "达糖尿病诊断阈值",
                "detail": f"HbA1c {v}% ≥6.5%，达到糖尿病诊断标准（需复查确认）。",
                "ref": "HbA1c ≥6.5% 为诊断切点"}
    if has_diabetes:
        return {"level": "normal", "label": "控制良好",
                "detail": f"HbA1c {v}% <6.5%，在多数成人目标范围（<7.0%）内。",
                "ref": "多数成人 HbA1c 目标 <7.0%"}
    return {"level": "normal", "label": "正常范围",
            "detail": f"HbA1c {v}% 在 4.0%–6.5% 参考范围内。",
            "ref": "HbA1c 参考范围 4.0%–6.5%"}


def classify_lipid(v: float, sub: str) -> dict:
    if sub == "tg":
        if v >= 5.6:
            return {"level": "emergency", "label": "严重高甘油三酯",
                    "detail": f"甘油三酯 {v} mmol/L ≥5.6 mmol/L，急性胰腺炎风险明显增加。",
                    "ref": "TG ≥5.6 mmol/L 为严重升高"}
        if v >= 2.3:
            return {"level": "danger", "label": "高甘油三酯",
                    "detail": f"甘油三酯 {v} mmol/L ≥2.3 mmol/L。",
                    "ref": "TG 2.3–5.6 mmol/L 为升高"}
        if v >= 1.7:
            return {"level": "watch", "label": "甘油三酯边缘升高",
                    "detail": f"甘油三酯 {v} mmol/L 位于 1.7–2.3 mmol/L。",
                    "ref": "TG 1.7–2.3 mmol/L 为边缘升高"}
        return {"level": "normal", "label": "甘油三酯合适",
                "detail": f"甘油三酯 {v} mmol/L <1.7 mmol/L。",
                "ref": "TG 合适水平 <1.7 mmol/L"}
    if sub == "ldl":
        if v >= 4.9:
            return {"level": "danger", "label": "LDL-C 明显升高",
                    "detail": f"LDL-C {v} mmol/L ≥4.9 mmol/L，属于心血管风险较高的情况，需就医评估。",
                    "ref": "LDL-C 升高 ≥4.9 mmol/L"}
        if v >= 3.4:
            return {"level": "watch", "label": "LDL-C 高于一般参考水平",
                    "detail": f"LDL-C {v} mmol/L ≥3.4 mmol/L（一般人群参考水平）。个人目标需按风险分层由医生确定。",
                    "ref": "一般人群 LDL-C <3.4 mmol/L"}
        return {"level": "normal", "label": "LDL-C 在参考范围",
                "detail": f"LDL-C {v} mmol/L <3.4 mmol/L。",
                "ref": "一般人群 LDL-C 合适水平 <3.4 mmol/L"}
    if sub == "tc":
        if v >= 6.2:
            return {"level": "danger", "label": "总胆固醇升高",
                    "detail": f"总胆固醇 {v} mmol/L ≥6.2 mmol/L。",
                    "ref": "TC ≥6.2 mmol/L 为升高"}
        if v >= 5.2:
            return {"level": "watch", "label": "总胆固醇边缘升高",
                    "detail": f"总胆固醇 {v} mmol/L 位于 5.2–6.2 mmol/L。",
                    "ref": "TC 5.2–6.2 mmol/L 为边缘升高"}
        return {"level": "normal", "label": "总胆固醇合适",
                "detail": f"总胆固醇 {v} mmol/L <5.2 mmol/L。",
                "ref": "TC 合适水平 <5.2 mmol/L"}
    if sub == "hdl":
        if v < 1.0:
            return {"level": "watch", "label": "HDL-C 偏低",
                    "detail": f"高密度脂蛋白胆固醇 {v} mmol/L <1.0 mmol/L，是心血管风险因素。",
                    "ref": "HDL-C <1.0 mmol/L 为降低"}
        return {"level": "normal", "label": "HDL-C 正常",
                "detail": f"高密度脂蛋白胆固醇 {v} mmol/L ≥1.0 mmol/L。",
                "ref": "HDL-C ≥1.0 mmol/L"}
    return {"level": "normal", "label": "已记录", "detail": "", "ref": ""}


def classify_weight(v: float, height_cm: float | None) -> dict:
    if not height_cm:
        return {"level": "normal", "label": "已记录",
                "detail": f"体重 {v} kg 已记录。补充身高后可以计算 BMI。", "ref": ""}
    bmi = v / ((height_cm / 100) ** 2)
    if bmi >= 28:
        return {"level": "danger", "label": f"肥胖（BMI {bmi:.1f}）",
                "detail": f"BMI {bmi:.1f} ≥28.0，属肥胖范围。",
                "ref": "中国成人 BMI ≥28.0 为肥胖"}
    if bmi >= 24:
        return {"level": "watch", "label": f"超重（BMI {bmi:.1f}）",
                "detail": f"BMI {bmi:.1f} 位于 24.0–27.9，属超重。",
                "ref": "中国成人 BMI 24.0–27.9 为超重"}
    if bmi < 18.5:
        return {"level": "watch", "label": f"体重偏低（BMI {bmi:.1f}）",
                "detail": f"BMI {bmi:.1f} <18.5，属体重偏低，老年患者需注意肌少症风险。",
                "ref": "中国成人 BMI <18.5 为体重过低"}
    return {"level": "normal", "label": f"体重正常（BMI {bmi:.1f}）",
            "detail": f"BMI {bmi:.1f} 在 18.5–23.9 正常范围。",
            "ref": "中国成人 BMI 18.5–23.9 为正常"}


def classify_waist(v: float, sex: str = "") -> dict:
    limit = 85 if sex == "女" else 90
    if v >= limit:
        return {"level": "watch", "label": "中心性肥胖",
                "detail": f"腰围 {v:.0f} cm ≥{limit} cm，提示中心性肥胖。",
                "ref": f"{'女性' if sex == '女' else '男性'}腰围应 <{limit} cm"}
    return {"level": "normal", "label": "腰围正常",
            "detail": f"腰围 {v:.0f} cm 在参考范围内。",
            "ref": f"{'女性' if sex == '女' else '男性'}腰围 <{limit} cm"}


def classify(kind: str, sub: str | None, val1: float, val2: float | None,
             profile: dict | None = None) -> dict:
    profile = profile or {}
    if kind == "bp":
        return classify_bp(val1, val2 or 0)
    if kind == "glucose":
        return classify_glucose(val1, sub or "random")
    if kind == "lipid":
        return classify_lipid(val1, sub or "tc")
    if kind == "hba1c":
        has_dm = "糖尿病" in (profile.get("conditions") or "")
        return classify_hba1c(val1, has_dm)
    if kind == "weight":
        return classify_weight(val1, profile.get("height_cm"))
    if kind == "waist":
        return classify_waist(val1, profile.get("sex") or "")
    return {"level": "normal", "label": "已记录", "detail": "", "ref": ""}


def fmt_value(kind: str, sub: str | None, val1: float, val2: float | None, unit: str | None = None) -> str:
    if kind == "bp":
        return f"{val1:.0f}/{val2:.0f} mmHg"
    if kind == "lipid":
        return f"{val1:g} mmol/L"
    if kind == "glucose":
        return f"{val1:g} mmol/L"
    if kind == "hba1c":
        return f"{val1:g}%"
    if kind == "weight":
        return f"{val1:g} kg"
    if kind == "waist":
        return f"{val1:.0f} cm"
    return f"{val1:g} {unit or ''}".strip()
