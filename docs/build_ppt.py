# -*- coding: utf-8 -*-
"""生成参赛用 PPT（16:9，20 页，符合大赛作品提交说明的结构建议）。

运行：
    python docs/build_ppt.py
输出：
    docs/智护三高_参赛作品说明.pptx
"""
from __future__ import annotations

import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "docs", "智护三高_参赛作品说明.pptx")
SHOT = os.path.join(BASE, "docs", "assets", "shot_plan.png")
SHOT_CARD = os.path.join(BASE, "docs", "assets", "shot_plan_card.png")

INK = RGBColor(0x16, 0x20, 0x2C)
INK2 = RGBColor(0x3D, 0x4C, 0x5E)
MUTED = RGBColor(0x6B, 0x7A, 0x8D)
PRIMARY = RGBColor(0x0F, 0x8F, 0x7E)
PRIMARY_D = RGBColor(0x0A, 0x6F, 0x62)
PRIMARY_L = RGBColor(0xE6, 0xF6, 0xF3)
ACCENT = RGBColor(0x2F, 0x6F, 0xEB)
ACCENT_L = RGBColor(0xEA, 0xF1, 0xFF)
WARN = RGBColor(0xC2, 0x76, 0x0A)
WARN_L = RGBColor(0xFD, 0xF3, 0xE2)
DANGER = RGBColor(0xC6, 0x28, 0x28)
DANGER_L = RGBColor(0xFD, 0xEA, 0xEA)
LINE = RGBColor(0xE3, 0xE9, 0xF1)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BG = RGBColor(0xF6, 0xF9, 0xFC)

FONT = "Microsoft YaHei"
W, H = 13.333, 7.5


def set_font(run, size=14, bold=False, color=INK, font=FONT):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = font
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", font)


def textbox(slide, x, y, w, h, text="", size=14, bold=False, color=INK,
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.25,
            font=FONT, space_after=4):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        r = p.add_run()
        r.text = line
        set_font(r, size, bold, color, font)
    return tb


def rich(slide, x, y, w, h, blocks, line_spacing=1.3):
    """blocks: [(text, size, bold, color, align, space_before)]"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    first = True
    for item in blocks:
        text, size, bold, color = item[0], item[1], item[2], item[3]
        align = item[4] if len(item) > 4 else PP_ALIGN.LEFT
        before = item[5] if len(item) > 5 else 0
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_before = Pt(before)
        p.space_after = Pt(3)
        r = p.add_run()
        r.text = text
        set_font(r, size, bold, color)
    return tb


def rect(slide, x, y, w, h, fill=None, line=None, radius=False, line_w=1.0):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(line_w)
    shp.shadow.inherit = False
    if radius:
        try:
            shp.adjustments[0] = 0.08
        except Exception:
            pass
    return shp


def shape_text(shp, text, size=12, bold=False, color=INK, align=PP_ALIGN.LEFT,
               anchor=MSO_ANCHOR.MIDDLE, margin=0.12):
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(0.06)
    tf.margin_bottom = Inches(0.06)
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = 1.15
        r = p.add_run()
        r.text = line
        set_font(r, size, bold, color)


def new_slide(prs, title, kicker="", page=None, bg=WHITE):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    rect(slide, 0, 0, W, H, fill=bg)
    if kicker:
        textbox(slide, 0.72, 0.42, 8, 0.3, kicker, 11, True, PRIMARY)
        textbox(slide, 0.72, 0.72, 11.9, 0.55, title, 26, True, INK)
    else:
        textbox(slide, 0.72, 0.55, 11.9, 0.6, title, 26, True, INK)
    rect(slide, 0.72, 1.36, 0.62, 0.045, fill=PRIMARY)
    if page:
        textbox(slide, 0.72, 6.92, 6, 0.28, "智护三高 · 三高共病 AI 健康管理智能体", 9, False, MUTED)
        textbox(slide, 11.9, 6.92, 0.7, 0.28, f"{page:02d}", 10, True, MUTED, PP_ALIGN.RIGHT)
    return slide


def table(slide, x, y, w, col_widths, rows, header=True, size=11, row_h=0.34,
          header_fill=PRIMARY, header_color=WHITE, zebra=True):
    n_rows = len(rows)
    n_cols = len(rows[0])
    total_h = row_h * n_rows
    gs = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(w), Inches(total_h))
    tbl = gs.table
    for i, cw in enumerate(col_widths):
        tbl.columns[i].width = Inches(cw)
    for ri, row in enumerate(rows):
        tbl.rows[ri].height = Inches(row_h)
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_left = Inches(0.09)
            cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03)
            cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT
            r = p.add_run()
            r.text = str(val)
            if header and ri == 0:
                set_font(r, size, True, header_color)
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_fill
            else:
                set_font(r, size, ci == 0, INK2 if ci else INK)
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE if (not zebra or ri % 2) else BG
    # 去掉默认样式的边框感
    return tbl


# --------------------------------------------------------------------- 内容
def build():
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)

    # 01 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, H, fill=WHITE)
    rect(s, 0, 0, 0.28, H, fill=PRIMARY)
    rect(s, 8.6, 0, 4.733, H, fill=PRIMARY_L)
    textbox(s, 1.05, 1.55, 7.6, 0.32, "第二届全国人工智能应用创新大赛", 12, True, PRIMARY)
    textbox(s, 1.05, 1.95, 7.6, 0.4, "通用赛道 · 命题方向：让 AI Agent 赋能千行百业 · 领域：医疗", 12, False, MUTED)
    textbox(s, 1.05, 2.65, 7.6, 1.1, "智护三高", 54, True, INK)
    textbox(s, 1.05, 3.72, 7.6, 0.5, "三高共病 AI 健康管理智能体", 22, True, PRIMARY_D)
    textbox(s, 1.05, 4.42, 7.3, 1.0,
            "让患者不用先学会用 App，只要说一句「今天血压 150/95」，\n"
            "系统就把数据记下来、看懂趋势、并安排明天具体吃什么、做什么。", 14, False, INK2)
    for i, (label, sub) in enumerate([("零依赖运行", "纯标准库 + 原生前端"), ("知识可溯源", "11 篇指南要点"),
                                      ("安全可解释", "代码级边界")]):
        x = 1.05 + i * 2.45
        rect(s, x, 5.62, 2.25, 0.86, fill=BG, line=LINE, radius=True)
        textbox(s, x + 0.16, 5.74, 2.0, 0.28, label, 12, True, PRIMARY_D)
        textbox(s, x + 0.16, 6.05, 2.0, 0.28, sub, 9.5, False, MUTED)
    textbox(s, 1.05, 6.75, 7.2, 0.3,
            "本作品为健康管理辅助工具，不做诊断、不开处方、不调整药物剂量、不替代医生。", 9.5, False, MUTED)
    textbox(s, 9.2, 2.5, 3.6, 0.4, "一句话", 12, True, PRIMARY)
    textbox(s, 9.2, 2.95, 3.5, 2.6,
            "把碎片化的血压、血糖、血脂记录，\n变成能看懂的曲线、能执行的日程、\n能带去复诊的报告。",
            15, True, INK, line_spacing=1.5)

    # 02 背景
    s = new_slide(prs, "三高管理的真正难点，不在「有没有药」", "作品背景与说明", 2)
    left = [
        ("数据是碎的", "手写本、纸质检验单、不同品牌设备、口头描述，形不成可用趋势。"),
        ("管理是割裂的", "血压去心内科、血糖去内分泌、血脂再去一次，药物互相影响却没人统看。"),
        ("建议是空的", "「少盐少油多运动」说了一百遍，患者回家仍不知道明天早餐吃什么。"),
        ("随访是断的", "门诊 3 分钟，两次门诊之间三个月无人过问，依从性自然掉下来。"),
    ]
    for i, (t, d) in enumerate(left):
        y = 1.62 + i * 1.06
        rect(s, 0.72, y, 6.4, 0.88, fill=BG, line=LINE, radius=True)
        rect(s, 0.72, y, 0.055, 0.88, fill=PRIMARY if i % 2 == 0 else ACCENT)
        textbox(s, 0.95, y + 0.12, 6.0, 0.3, t, 13, True, INK)
        textbox(s, 0.95, y + 0.42, 6.0, 0.4, d, 10.5, False, INK2)

    textbox(s, 7.55, 1.6, 5.1, 0.3, "我们把它收敛成一个问题", 12, True, PRIMARY)
    rect(s, 7.55, 2.0, 5.1, 1.28, fill=PRIMARY_L, line=None, radius=True)
    textbox(s, 7.75, 2.14, 4.75, 1.05,
            "当一个人同时患两种以上慢性病、每天吃 5 种以上药时，\n谁来帮他看见药物与代谢之间的交叉影响？",
            13, True, PRIMARY_D)
    textbox(s, 7.55, 3.55, 5.1, 0.3, "参考资料", 12, True, PRIMARY)
    for i, line in enumerate([
        "《中国心血管健康与疾病报告》（国家心血管病中心）",
        "《中国居民营养与慢性病状况报告（2020年）》",
        "《中国高血压防治指南（2024年修订版）》",
        "《中国糖尿病防治指南（2024版）》",
        "《中国血脂管理指南（2023年）》",
        "《中国居民膳食指南（2022）》",
    ]):
        textbox(s, 7.55, 3.95 + i * 0.36, 5.1, 0.3, "· " + line, 10.5, False, INK2)
    textbox(s, 0.72, 6.15, 12.0, 0.35,
            "说明：按大赛匿名评审要求，本材料不出现学校名称、参赛者姓名与指导教师信息。", 9.5, False, MUTED)

    # 03 数据来源一
    s = new_slide(prs, "数据来源（一）：国家级临床指南与规范", "数据收集与处理 · 来源 A 类", 3)
    table(s, 0.72, 1.6, 11.9, [3.5, 2.9, 0.8, 4.7], [
        ["来源名称", "发布机构", "年份", "取用的内容"],
        ["中国高血压防治指南（2024年修订版）", "国家心血管病中心 / 中国高血压联盟", "2024", "血压分级、降压目标、生活方式干预、联合用药、随访频次"],
        ["中国糖尿病防治指南（2024版）", "中华医学会糖尿病学分会", "2024", "诊断标准、控制目标、低血糖处理、并发症筛查"],
        ["中国血脂管理指南（2023年）", "中国血脂管理指南修订联合委员会", "2023", "血脂分层目标、他汀原则、用药监测、胰腺炎风险"],
        ["中国居民膳食指南（2022）", "中国营养学会", "2022", "食物推荐量、限盐限油、食物交换份、低升糖主食"],
        ["国家基层高血压／糖尿病防治管理指南", "国家卫健委基层卫生健康司", "2019/2022", "基层随访频次、转诊指征、三高共管"],
    ], size=10.5, row_h=0.52)
    textbox(s, 0.72, 5.05, 11.9, 0.3, "权威性与时效性说明", 12, True, PRIMARY)
    for i, line in enumerate([
        "权威性：均为国家级学会或行政规范层面文件，是三高管理最高级别的实践依据。",
        "时效性：高血压、糖尿病、血脂三项均在 2023—2024 年完成版本更新，与当前临床一致。",
        "使用方式：整理为内部知识库要点（不整篇转载），回答时标注「名称 + 版本年份 + 发布机构」。",
        "版权合规：指南全文受期刊版权保护，仅作内部检索使用；对外材料只引用要点并注明出处。",
    ]):
        textbox(s, 0.72, 5.42 + i * 0.36, 11.9, 0.32, "· " + line, 10.5, False, INK2)

    # 04 数据来源二
    s = new_slide(prs, "数据来源（二）：公开数据集、药品说明与用户侧入口", "数据收集与处理 · 来源 B/C/D/E 类", 4)
    table(s, 0.72, 1.6, 5.95, [2.55, 3.4], [
        ["来源", "能拿到什么 / 权威性"],
        ["中国心血管健康与疾病报告", "患病率、知晓率、控制率；年度更新，国家级"],
        ["中国居民营养与慢性病状况报告", "糖尿病、血脂异常、肥胖率；约 5 年一次"],
        ["CHARLS 中国健康与养老追踪调查", "本土多轮追踪队列；需注册并遵守协议"],
        ["NHANES（美国 CDC）", "大样本对照与方法学验证，不外推中国结论"],
        ["IDF Diabetes Atlas", "国际口径患病人数，用于横向对比"],
    ], size=10, row_h=0.58)
    table(s, 7.0, 1.6, 5.62, [2.4, 3.22], [
        ["来源", "能拿到什么 / 权威性"],
        ["NMPA 药品说明书", "中文权威说明书：相互作用、代谢影响"],
        ["DailyMed（美国 NIH）", "结构规整的英文说明书，便于结构化"],
        ["用户手动录入", "主力入口：实时，覆盖血压/血糖/血脂/体重"],
        ["检验单 OCR + 对话抽取", "把纸质单与口语转成结构化字段"],
        ["微信蓝牙 API（规划）", "直连血压计、血糖仪；免额外资质"],
    ], size=10, row_h=0.58)
    textbox(s, 0.72, 5.05, 11.9, 0.3, "我们把「来源」做成了可核查的台账，而不是一句“参考了权威资料”", 12, True, PRIMARY)
    for i, line in enumerate([
        "knowledge/sources.json 收录 15 个来源，记录 名称 / 机构 / 年份 / 权威性 / 时效性 / 用途 / 获取日期 / 是否入库。",
        "界面「查看数据来源台账」可逐条查看，PPT 与视频中的每个数字都能回溯到具体报告与年份。",
        "知识库中 11 篇文档均带 frontmatter 元数据，回答时自动带出出处；没有命中的问题明确不引用。",
    ]):
        textbox(s, 0.72, 5.42 + i * 0.38, 11.9, 0.34, "· " + line, 10.5, False, INK2)

    # 05 数据处理
    s = new_slide(prs, "数据处理：从一句口语到一条可用记录", "数据收集与处理 · 预处理与利用", 5)
    steps = [
        ("① 自然语言输入", "“昨天早上血压 150/95，早餐后血糖 9.6”", PRIMARY_L, PRIMARY_D),
        ("② 实体抽取", "指标 / 数值 / 单位 / 时间 / 场景 / 药名（也支持整张检验单）", ACCENT_L, ACCENT),
        ("③ 生理边界校验", "收缩压 60–260、舒张压 30–160；收缩压必须大于舒张压", WARN_L, WARN),
        ("④ 结构化入库", "SQLite：kind / sub_kind / val1 / val2 / measured_at / source", BG, INK2),
        ("⑤ 风险分级", "正常 / 警戒 / 危险 / 急症，四级回溯到指南条目", DANGER_L, DANGER),
        ("⑥ 派生分析", "趋势斜率、超参考次数、依从率、复诊摘要", PRIMARY_L, PRIMARY_D),
    ]
    for i, (t, d, bgc, fgc) in enumerate(steps):
        col = i % 3
        row = i // 3
        x = 0.72 + col * 4.02
        y = 1.62 + row * 1.42
        rect(s, x, y, 3.75, 1.16, fill=bgc, line=None, radius=True)
        textbox(s, x + 0.18, y + 0.14, 3.4, 0.3, t, 13, True, fgc)
        textbox(s, x + 0.18, y + 0.5, 3.4, 0.55, d, 9.8, False, INK2)
    rect(s, 0.72, 4.7, 11.9, 0.02, fill=LINE)
    textbox(s, 0.72, 4.86, 11.9, 0.3, "三条不可让步的处理原则", 12, True, PRIMARY)
    for i, (t, d) in enumerate([
        ("宁可拒绝，也不入库", "数值越界或缺失必填项时直接拒绝，并提示“请检查单位或小数点”，避免错值污染整条趋势。"),
        ("数据不足就说不足", "少于 3 条记录不画趋势、不给方向结论，只提示继续记录，绝不补写或推测历史数据。"),
        ("原始值永远保留", "记录保存 source（chat/manual/ocr/device）与原文片段，便于回溯“这条数据是怎么来的”。"),
    ]):
        x = 0.72 + i * 4.02
        rect(s, x, 5.28, 3.75, 1.32, fill=WHITE, line=LINE, radius=True)
        textbox(s, x + 0.18, 5.4, 3.4, 0.3, t, 11.5, True, INK)
        textbox(s, x + 0.18, 5.72, 3.42, 0.8, d, 9.3, False, INK2)

    # 06 用户与场景
    s = new_slide(prs, "目标用户：从「患者本人」到「替他操心的人」", "目标用户与使用场景", 6)
    table(s, 0.72, 1.6, 11.9, [1.5, 2.6, 4.3, 3.5], [
        ["优先级", "用户", "核心诉求", "对我们的意义"],
        ["主要", "45 岁以上已确诊三高、需长期管理者", "看得懂自己的指标，知道每天该做什么", "用户基数最大，验证基础能力"],
        ["核心", "三高共病、多药同服的中老年患者", "担心药物互相打架，怕吃错", "最能体现创新点的人群"],
        ["传播", "异地照护父母的子女", "远程看得到父母状态，能帮上忙", "付费意愿与传播力最强"],
        ["落地", "社区卫生服务中心家庭医生", "减少重复问询，快速掌握随访重点", "B 端入口，落地路径的抓手"],
    ], size=10.5, row_h=0.5)
    textbox(s, 0.72, 4.35, 11.9, 0.3, "三个真实使用瞬间", 12, True, PRIMARY)
    scenes = [
        ("早晨 6:40", "起床后测完血压，对着手机说一句数值，系统判断是否需要今天就医。"),
        ("晚饭前 17:30", "不知道吃什么，问“今晚吃什么”，得到带克数、带做法的具体菜。"),
        ("复诊前一晚", "生成一页报告：30 天趋势、依从率、需要问医生的 4 个问题。"),
    ]
    for i, (t, d) in enumerate(scenes):
        x = 0.72 + i * 4.02
        rect(s, x, 4.75, 3.75, 1.55, fill=BG, line=LINE, radius=True)
        textbox(s, x + 0.2, 4.9, 3.35, 0.3, t, 12, True, PRIMARY_D)
        textbox(s, x + 0.2, 5.25, 3.38, 0.9, d, 10, False, INK2)

    # 07 总体架构
    s = new_slide(prs, "总体方案：五层架构，对话做入口，工具做事实", "技术方案总览", 7)
    layers = [
        ("交互层", "Chat-first 对话 · 结构化卡片 · SVG 趋势图 · 健康看板 · 适老化大字", ACCENT),
        ("智能层", "安全网关 → 意图识别 → 受控工具调用 → 知识检索 → 大模型叙事 → 输出校验", PRIMARY),
        ("知识层", "11 篇指南要点 · 40 种药物联动规则 · 数据来源台账（可溯源、可扩充）", RGBColor(0x5B, 0x46, 0xC4)),
        ("数据层", "SQLite：测量 / 用药 / 打卡 / 任务 / 对话 / 风险事件；对话抽取与检验单录入", RGBColor(0x18, 0x85, 0x4A)),
        ("反馈层", "任务打卡 + 指标回填 → 重算趋势与方案 → 依从率进入下一次对话", RGBColor(0xC2, 0x76, 0x0A)),
    ]
    for i, (name, desc, color) in enumerate(layers):
        y = 1.62 + i * 0.94
        rect(s, 0.72, y, 1.55, 0.76, fill=color, radius=True)
        textbox(s, 0.72, y + 0.2, 1.55, 0.36, name, 12.5, True, WHITE, PP_ALIGN.CENTER)
        rect(s, 2.42, y, 10.2, 0.76, fill=WHITE, line=LINE, radius=True)
        textbox(s, 2.66, y + 0.1, 9.8, 0.56, desc, 11, False, INK2, anchor=MSO_ANCHOR.MIDDLE)
    textbox(s, 0.72, 6.42, 11.9, 0.4,
            "关键取舍：大模型只负责「怎么说」，数字与结论全部来自工具调用 —— 从结构上压缩幻觉空间。", 11.5, True, PRIMARY_D)

    # 08 能力链
    s = new_slide(prs, "一次对话的完整链路，每一步都在界面上可见", "Agent 能力链", 8)
    chain = [
        ("安全网关", "红旗症状 / 调药请求 → 命中即锁定输出，大模型不参与"),
        ("意图识别", "确定性规则抽取指标、数值、时间、药名，输出置信度"),
        ("受控工具", "20 个白名单工具：入库 / 查询 / 趋势 / 方案 / 报告 / 药物联动"),
        ("知识检索", "BM25 + 主题加权 + 同义扩展，返回可溯源片段"),
        ("生成叙事", "DeepSeek 只写“怎么说”，数值必须原样引用事实区块"),
        ("输出校验", "结构化卡片 + 来源 + 免责声明 + 兜底长度与空值处理"),
    ]
    for i, (t, d) in enumerate(chain):
        y = 1.62 + i * 0.82
        rect(s, 0.72, y, 0.46, 0.46, fill=PRIMARY if i < 4 else ACCENT, radius=True)
        textbox(s, 0.72, y + 0.08, 0.46, 0.3, str(i + 1), 12, True, WHITE, PP_ALIGN.CENTER)
        textbox(s, 1.42, y + 0.02, 2.0, 0.34, t, 12.5, True, INK)
        textbox(s, 3.5, y + 0.04, 9.1, 0.34, d, 11, False, INK2)
    rect(s, 0.72, 6.55, 11.9, 0.42, fill=PRIMARY_L, radius=True)
    textbox(s, 0.95, 6.62, 11.5, 0.3,
            "工程实现：纯 Python 标准库 + 原生 JS，无第三方依赖；断网或 API 异常时自动降级为本地规则引擎，功能不中断。", 10, True, PRIMARY_D)

    # 09 核心能力
    s = new_slide(prs, "六个核心能力，全部可现场演示", "能力清单", 9)
    caps = [
        ("① 数据接入与结构化", "口语直接入库；粘贴检验单批量识别，勾选确认后写入", "校验 + 分级"),
        ("② 趋势与预警", "均值、极值、斜率、方向、超参考次数", "SVG 趋势图"),
        ("③ 可执行方案", "7 天 × 每天 11 项，到「几点吃什么多少克」", "时间轴卡片"),
        ("④ 用药联动检查", "40 种药物、31 条规则，输出监测与沟通建议", "风险分级卡"),
        ("⑤ 安全审查", "8 类红旗 + 处方红线；涉药回答强制附「请遵医嘱」提示条", "急症卡 / 拒绝卡"),
        ("⑥ 追踪闭环", "打卡、依从率、周报、复诊问题清单", "报告卡片"),
    ]
    for i, (t, d, tag) in enumerate(caps):
        col = i % 3
        row = i // 3
        x = 0.72 + col * 4.02
        y = 1.62 + row * 2.35
        rect(s, x, y, 3.75, 2.05, fill=WHITE, line=LINE, radius=True)
        rect(s, x, y, 3.75, 0.06, fill=PRIMARY if i % 2 == 0 else ACCENT)
        textbox(s, x + 0.2, y + 0.22, 3.35, 0.3, t, 13, True, INK)
        textbox(s, x + 0.2, y + 0.62, 3.35, 0.9, d, 10.5, False, INK2)
        rect(s, x + 0.2, y + 1.58, 1.9, 0.32, fill=PRIMARY_L, radius=True)
        textbox(s, x + 0.2, y + 1.63, 1.9, 0.26, tag, 9, True, PRIMARY_D, PP_ALIGN.CENTER)

    # 10 创新点一
    s = new_slide(prs, "创新点一：把「药物—代谢」联动做进规则库", "创新点 1 / 2", 10)
    textbox(s, 0.72, 1.5, 11.9, 0.34,
            "分科管理看不见交叉影响，联合管理才看得见。下表是本项目知识库中被工具真正调用、而不是写在墙上的规则。",
            11, False, INK2)
    table(s, 0.72, 1.98, 11.9, [2.45, 1.95, 4.15, 3.35], [
        ["常见组合", "代谢交叉点", "机制与后果", "系统给出的动作"],
        ["噻嗪类利尿剂 + 磺脲类", "升糖 / 升尿酸", "氢氯噻嗪可升高血糖与尿酸，削弱降糖效果，可能诱发痛风", "提示同步监测血糖与尿酸，复诊时说明用药组合"],
        ["β 受体阻滞剂 + 胰岛素", "掩盖低血糖", "美托洛尔阻断心慌、手抖等交感预警，只保留出汗，易漏诊低血糖", "列为高风险：睡前加测、随身带葡萄糖、家人知情"],
        ["他汀 + 贝特", "肌病 / 肝损", "联合使用增加肌病与肝损伤风险；大环内酯、西柚汁进一步升高他汀浓度", "提示复查 CK 与肝功能，出现肌痛立即就医"],
        ["ACEI + 保钾利尿剂 / 低钠盐", "高钾血症", "三重叠加可致严重高钾，心律失常风险隐蔽", "用药 1 周内复查血钾，慎用低钠富钾盐"],
        ["NSAIDs + 降压药 + 利尿剂", "急性肾损伤", "所谓“三重打击”，同时削弱降压效果", "避免自行长期止痛药，疼痛先咨询"],
    ], size=9.5, row_h=0.66)
    textbox(s, 0.72, 5.85, 11.9, 0.3, "为什么这是壁垒", 12, True, PRIMARY)
    textbox(s, 0.72, 6.2, 11.9, 0.7,
            "单病种 App 的知识库只覆盖自己那一科；把三科的药放在同一张表里，并用「谁在吃什么」驱动检索，"
            "才能回答“我这把药一起吃安不安全”。目前规则库覆盖 40 种常用药、31 条联动规则，全部可指回指南或说明书。",
            10.5, False, INK2)

    # 11 创新点二
    s = new_slide(prs, "创新点二：从「记录」到「明天照做就行」", "创新点 2 / 2", 11)
    textbox(s, 0.72, 1.5, 6.1, 0.34, "同一句“多运动”，两种交付方式", 11.5, True, PRIMARY)
    rect(s, 0.72, 1.9, 5.9, 0.9, fill=DANGER_L, line=None, radius=True)
    textbox(s, 0.95, 2.05, 5.5, 0.6, "×  少盐少油、适当运动、保持心情愉快", 12, False, DANGER)
    rect(s, 0.72, 2.95, 5.9, 1.5, fill=PRIMARY_L, line=None, radius=True)
    textbox(s, 0.95, 3.08, 5.5, 1.25,
            "✓  19:00 快走 30 分钟（约 3000 步，能说话但唱不了歌）\n"
            "✓  做菜只用 1 勺酱油，汤不喝完\n"
            "✓  21:00 睡前测一次血压并记录", 12, False, PRIMARY_D)
    textbox(s, 0.72, 4.62, 5.9, 0.3, "方案受真实约束，不是模板填空", 11.5, True, PRIMARY)
    for i, line in enumerate([
        "会不会做饭：不做饭 → 便利店组合 + 食堂点菜话术",
        "预算：紧 → 鸡蛋、豆腐、鸡胸肉，蛋白质一样够",
        "口味：偏咸 → 分两步减盐，每两周减 1/4",
        "作息：起床 6:30 → 任务卡从 6:30 开始排",
        "共病：合并糖尿病 → 加餐后 2 小时血糖、主食定量",
    ]):
        textbox(s, 0.72, 5.0 + i * 0.36, 5.9, 0.32, "· " + line, 10, False, INK2)
    if os.path.exists(SHOT_CARD):
        s.shapes.add_picture(SHOT_CARD, Inches(6.95), Inches(1.5), height=Inches(4.15))
        textbox(s, 6.95, 5.78, 5.6, 0.3, "界面实拍：7 天方案卡片（点日期切换，每项带时间与克数）", 9, False, MUTED)
        textbox(s, 6.95, 6.15, 5.6, 0.75,
                "左侧同一份数据同时支撑档案、指标快照与今日任务；右侧每张卡片都可点开“依据”查看来源。",
                9.5, False, INK2)

    # 12 知识库与 RAG
    s = new_slide(prs, "知识库：可扩充、可溯源、可验证", "知识增强（RAG）", 12)
    rows = [
        ["环节", "做法", "为什么这样做"],
        ["文档接入", "knowledge/docs 放 .md / .txt / .docx；界面支持拖拽", "预留位置，后续加文件即生效，无需改代码"],
        ["元数据", "frontmatter 记录 来源 / 机构 / 年份 / 等级 / 主题", "回答里的“来源”不是模型编的，而是文档自带的"],
        ["切分", "按标题层级切块，超长按段落二次切分", "保持语义完整，便于精确引用到“哪一节”"],
        ["检索", "中文二元组 + 领域单字 + 同义扩展 + 主题加权 BM25", "无向量库也能跑；离线、可解释、可调试"],
        ["输出", "片段进入提示词，回答带「依据」折叠区", "用户点开就能看到原文，可自行判断可信度"],
    ]
    table(s, 0.72, 1.6, 11.9, [1.5, 5.7, 4.7], rows, size=10, row_h=0.55)
    textbox(s, 0.72, 5.05, 11.9, 0.3, "当前知识库", 12, True, PRIMARY)
    stats = [("11", "篇指南与整理文档"), ("100+", "个可检索片段"), ("30+", "种药物"), ("31", "条联动规则")]
    for i, (num, label) in enumerate(stats):
        x = 0.72 + i * 3.02
        rect(s, x, 5.45, 2.8, 1.0, fill=BG, line=LINE, radius=True)
        textbox(s, x + 0.2, 5.55, 2.4, 0.45, num, 22, True, PRIMARY_D)
        textbox(s, x + 0.2, 6.05, 2.4, 0.3, label, 9.5, False, MUTED)

    # 13 安全边界
    s = new_slide(prs, "安全边界：写在代码里，而不是写在提示词里", "医疗安全与合规", 13)
    blocks = [
        ("第一道：红旗症状拦截", DANGER, DANGER_L,
         "8 类急症（胸痛、呼吸困难、卒中征象、意识改变、酮症、消化道出血、胰腺炎、高血压急症）关键词命中即跳过全部建议生成，直接输出 120 指引。"),
        ("第二道：数值急症判定", RGBColor(0x7F, 0x1D, 0x1D), DANGER_L,
         "血压 ≥180/110、血糖 <3.9 或 ≥16.7、甘油三酯 ≥5.6 直接判定急症，先留记录，再给急救提示。"),
        ("第三道：处方红线", WARN, WARN_L,
         "加减停换药一律拒绝。凡涉及用药的回答，系统再结构性附加一条提示：不构成用药建议、不自行加减停药、哪些症状要就医，并明确「请严格遵医嘱服药」。"),
    ]
    for i, (t, color, bgc, d) in enumerate(blocks):
        x = 0.72 + i * 4.02
        rect(s, x, 1.6, 3.75, 2.2, fill=bgc, line=None, radius=True)
        textbox(s, x + 0.2, 1.75, 3.35, 0.3, t, 12.5, True, color)
        textbox(s, x + 0.2, 2.12, 3.35, 1.55, d, 10, False, INK2)
    textbox(s, 0.72, 3.95, 11.9, 0.3, "另外四层工程约束", 12, True, PRIMARY)
    for i, (t, d) in enumerate([
        ("会话与权限", "身份只来自服务端会话，不接受 URL 传 user；无密码时强制只听本机，设密码后所有接口需登录。"),
        ("数据完整性", "生理边界 + 档案字段校验；打卡按「药 + 日期 + 时段」唯一，依从率不会超过 100%。"),
        ("工具白名单", "只有注册过的 20 个工具可被调用，模型无法“发明”能力，未注册调用被直接拦截。"),
    ]):
        x = 0.72 + i * 4.02
        rect(s, x, 4.35, 3.75, 1.4, fill=WHITE, line=LINE, radius=True)
        textbox(s, x + 0.2, 4.48, 3.35, 0.3, t, 11.5, True, INK)
        textbox(s, x + 0.2, 4.82, 3.38, 0.85, d, 9.5, False, INK2)
    rect(s, 0.72, 5.95, 11.9, 0.8, fill=BG, line=LINE, radius=True)
    textbox(s, 0.95, 6.02, 11.4, 0.7,
            "每条回复固定附「本建议不构成诊疗意见，请遵医嘱。」｜ 演示数据全程标注「合成」，可一键只清演示数据\n"
            "明确不做：疾病诊断 · 开具处方 · 调整药物剂量 · 替代医生 · 急救判断 · 承诺疗效",
            9.5, True, INK2)

    # 14 跨学科
    s = new_slide(prs, "跨学科视角：一个产品要同时回答四个学科的问题", "跨学科设计", 14)
    disc = [
        ("临床医学", "指南与用药", "阈值、目标、联合用药原则从指南来；药物联动从说明书来；不做超出指南的推断。"),
        ("行为科学", "让人真的会做", "实施意图（如果…就…）、习惯叠加（吃完药顺手记录）、降低启动门槛（10 分钟也算）。"),
        ("人机交互", "适老化与家人协同", "大字模式、语音友好短句、结构化卡片；子女端看板用同一份数据。"),
        ("公共卫生", "接进基层流程", "随访频次与转诊指征对齐国家基本公卫；三高共管、六病同防是政策抓手。"),
    ]
    for i, (name, sub, d) in enumerate(disc):
        col = i % 2
        row = i // 2
        x = 0.72 + col * 6.1
        y = 1.62 + row * 2.4
        rect(s, x, y, 5.8, 2.1, fill=WHITE, line=LINE, radius=True)
        rect(s, x, y, 5.8, 0.06, fill=PRIMARY if i % 2 == 0 else ACCENT)
        textbox(s, x + 0.25, y + 0.25, 5.2, 0.32, name + "　·　" + sub, 13, True, INK)
        textbox(s, x + 0.25, y + 0.7, 5.3, 1.2, d, 10.5, False, INK2)
    textbox(s, 0.72, 6.55, 11.9, 0.35,
            "例：同样是“建议运动”，临床给出强度与禁忌，行为科学给出怎么开始，人机交互给出怎么提醒，公卫给出怎么进随访。",
            10, False, MUTED)

    # 15 验证
    s = new_slide(prs, "怎么证明它有用：可复现的验证设计", "验证设计与当前结果", 15)
    table(s, 0.72, 1.6, 11.9, [2.6, 3.0, 6.3], [
        ["验证方式", "规模 / 口径", "产出指标与当前状态"],
        ["自动化回归测试", "74 项，标准库 unittest", "意图抽取、生理校验、四级分级、红旗/处方拦截、趋势、药物联动、方案、报告、RAG、白名单 —— 全部通过"],
        ["合成病例批量评测", "20–30 例，覆盖年龄/共病/依从性", "建议可执行率、安全拦截率、指南溯源命中率、幻觉率、响应时延（进行中）"],
        ["医生盲评", "15–20 条建议，评可用/需修改/不可用", "可用率、修改意见条数（已联系，待回收）"],
        ["真实用户随访", "20–30 位，2–3 轮记录", "指标记录变化、依从打卡率、方案采纳率（下一阶段）"],
    ], size=10, row_h=0.56)
    textbox(s, 0.72, 4.66, 11.9, 0.3, "测试跑在真实数据库上，不修改演示数据", 12, True, PRIMARY)
    textbox(s, 0.72, 5.02, 11.9, 0.4, "python -m unittest discover -s tests -v     →     Ran 74 tests … OK", 11, True, PRIMARY_D)
    for i, line in enumerate([
        "对照口径：只报告「管理行为与指标记录的变化」，不宣称疗效 —— 这是医疗类作品最容易越界的地方。",
        "响应时延：在线大模型约 2 秒；离线本地规则 < 100 毫秒；红旗拦截不调用模型，稳定 < 50 毫秒。",
        "可复现：所有评测脚本与数据都在项目内，评审可现场重跑。",
    ]):
        textbox(s, 0.72, 5.62 + i * 0.4, 11.9, 0.36, "· " + line, 10.5, False, INK2)

    # 16 界面与演示
    s = new_slide(prs, "界面即证据：思考过程、数据卡片、可溯源依据同屏", "作品演示", 16)
    if os.path.exists(SHOT):
        s.shapes.add_picture(SHOT, Inches(0.72), Inches(1.55), height=Inches(4.95))
    steps = [
        ("① 记录", "“今天血压 150/95” → 入库卡片 + 分级依据 + 30 天趋势"),
        ("② 追问", "“最近血压怎么样” → 均值/极值/方向/超参考次数"),
        ("③ 方案", "“给我一份 7 天方案” → 时间轴，到克数"),
        ("④ 用药", "「每天 8 点吃一片」→ 变更打卡计划，需二次确认"),
        ("⑤ 拦截", "“我想停药” / “胸口疼” → 拒绝卡 / 120 急救卡"),
        ("⑥ 用药页", "按时段打卡、依从率、添加药物；同页附用药安全提示"),
    ]
    for i, (t, d) in enumerate(steps):
        y = 1.6 + i * 0.85
        rect(s, 8.35, y, 4.15, 0.72, fill=BG, line=LINE, radius=True)
        textbox(s, 8.52, y + 0.08, 0.9, 0.3, t, 11, True, PRIMARY_D)
        textbox(s, 9.3, y + 0.1, 3.1, 0.55, d, 9, False, INK2)

    # 17 落地
    s = new_slide(prs, "落地路径：从「一次演示」到「一个入口」", "落地与商业化", 17)
    paths = [
        ("社区卫生服务中心", "嵌入家庭医生签约与三高共管随访，作为医生的随访助手；对齐全公卫 4 次随访 + 1 次体检。"),
        ("药店慢病管理", "购药提醒 + 依从性管理，天然高频接触点；药师端可看到药物联动提示。"),
        ("体检机构", "异常指标检后随访，转化路径最短；报告异常 → 一周内电话/微信随访。"),
        ("子女端订阅", "远程看板与异常提醒，付费意愿最强；只共享必要指标，不共享全部记录。"),
    ]
    for i, (t, d) in enumerate(paths):
        col = i % 2
        row = i // 2
        x = 0.72 + col * 6.1
        y = 1.62 + row * 1.55
        rect(s, x, y, 5.8, 1.3, fill=WHITE, line=LINE, radius=True)
        textbox(s, x + 0.24, y + 0.16, 5.3, 0.3, t, 12.5, True, INK)
        textbox(s, x + 0.24, y + 0.52, 5.35, 0.7, d, 10, False, INK2)
    rect(s, 0.72, 4.85, 11.9, 1.05, fill=PRIMARY_L, radius=True)
    textbox(s, 0.95, 5.0, 11.4, 0.8,
            "政策抓手：「三高共管、六病同防」是当前国家与多省推进的基层慢性病一体化服务模式。"
            "本项目卡住的正是它的信息化缺口 —— 基层医生需要的是「一次随访同时看清三高 + 用药 + 依从性」的工具。",
            11, True, PRIMARY_D)
    textbox(s, 0.72, 6.1, 11.9, 0.35,
            "商业模式的克制：先做“医生的助手”和“子女的眼睛”，不做“替代医生的诊断器”。", 10.5, False, MUTED)

    # 18 竞品对比
    s = new_slide(prs, "与现有方案的差别", "竞品分析", 18)
    table(s, 0.72, 1.6, 11.9, [3.0, 2.2, 2.2, 4.5], [
        ["维度", "单病种健康 App", "通用健康问答", "智护三高"],
        ["覆盖病种", "单一（只做血压或只做血糖）", "泛健康", "三高共病联合，含代谢交叉"],
        ["数据落地", "各自闭环，难导出", "不保存、不计算", "本地 SQLite，趋势可回溯"],
        ["用药视角", "无或仅提醒", "泛泛而谈", "40 种药、31 条联动规则，可指回说明书"],
        ["建议颗粒度", "泛化文案", "泛化文案", "到几点、吃什么、多少克、做多久"],
        ["安全边界", "弱", "靠提示词", "代码级三层拦截 + 统一免责"],
        ["知识可溯源", "少", "常无来源", "每篇文档带元数据，回答附依据"],
        ["部署成本", "需云服务", "需联网", "零依赖本地运行，可离线演示"],
    ], size=10, row_h=0.55)

    # 19 规划
    s = new_slide(prs, "下一步：三个月内的三件事", "未来规划", 19)
    plan = [
        ("第一个月", "评测补齐", "合成 30 例病例批量评测，产出安全拦截率、溯源命中率、时延分布；回收医生盲评。"),
        ("第二个月", "数据入口", "接入检验单 OCR（拍照→结构化→人工确认入库）与微信蓝牙血压计，减少手工录入。"),
        ("第三个月", "基层试点", "与 1–2 家社区卫生服务中心做小样本试点，跑通“随访前自动生成摘要”的医生端流程。"),
    ]
    for i, (t, sub, d) in enumerate(plan):
        y = 1.62 + i * 1.65
        rect(s, 0.72, y, 1.75, 1.42, fill=PRIMARY if i == 0 else PRIMARY_L, radius=True)
        textbox(s, 0.72, y + 0.45, 1.75, 0.4, t, 13, True, WHITE if i == 0 else PRIMARY_D, PP_ALIGN.CENTER)
        rect(s, 2.62, y, 10.0, 1.42, fill=WHITE, line=LINE, radius=True)
        textbox(s, 2.86, y + 0.16, 9.5, 0.32, sub, 13, True, INK)
        textbox(s, 2.86, y + 0.56, 9.55, 0.75, d, 10.5, False, INK2)
    textbox(s, 0.72, 6.55, 11.9, 0.35,
            "不变的东西：不做诊断、不开处方、不替代医生。变的只是把这些事做得更准、更省力。", 10.5, True, PRIMARY_D)

    # 20 结束
    s = prs.slides.add_slide(prs.slide_layouts[6])
    rect(s, 0, 0, W, H, fill=WHITE)
    rect(s, 0, 0, W, 0.16, fill=PRIMARY)
    textbox(s, 1.2, 2.05, 11, 0.4, "智护三高", 40, True, INK)
    textbox(s, 1.2, 2.95, 11, 0.5, "让三高管理从「记住数字」变成「知道下一步做什么」", 18, True, PRIMARY_D)
    rect(s, 1.2, 3.75, 1.2, 0.05, fill=PRIMARY)
    textbox(s, 1.2, 4.05, 10.8, 1.1,
            "所有内容均可现场复现：零依赖运行、74 项测试全通过、知识库可现场拖入新文件。\n"
            "本作品为健康管理辅助工具，不构成诊疗意见，请遵医嘱。", 12, False, INK2)
    textbox(s, 1.2, 5.55, 10.8, 0.4, "第二届全国人工智能应用创新大赛 · 通用赛道 · 医疗领域", 10.5, False, MUTED)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print("saved:", OUT, "slides:", len(prs.slides))


if __name__ == "__main__":
    build()
