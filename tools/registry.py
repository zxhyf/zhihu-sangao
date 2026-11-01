# -*- coding: utf-8 -*-
"""受控工具注册表。

设计要点：
- 只有注册过的工具才能被智能体调用（白名单），模型无法“发明”能力；
- 所有工具调用都在服务端完成并记录 trace，界面上可以看到每一步做了什么；
- 工具层只做数据读写与确定性计算，不产生医疗建议。
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from config import DEFAULT_USER
from tools import (interactions, lab_report, measurements, medications, plan, profile,
                   reports, tasks, trends)


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    readonly: bool = True
    tags: list[str] = field(default_factory=list)


def _wrap(name: str, desc: str, fn: Callable, readonly: bool = True, tags: list[str] | None = None) -> Tool:
    return Tool(name=name, description=desc, fn=fn, readonly=readonly, tags=tags or [])


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


register(_wrap("profile.get", "读取健康档案（年龄、身高、共病、BMI、作息、做饭条件）",
               lambda user_id=DEFAULT_USER: profile.get_profile(user_id), True, ["档案"]))
register(_wrap("profile.update", "更新健康档案字段",
               lambda user_id=DEFAULT_USER, **kw: profile.update_profile(user_id, **kw), False, ["档案"]))
register(_wrap("measurement.record", "把一次测量的血压/血糖/血脂/体重写入数据库并做风险分级",
               lambda user_id=DEFAULT_USER, **kw: measurements.record(user_id, **kw), False, ["数据"]))
register(_wrap("measurement.list", "按指标与时间范围读取历史测量记录",
               lambda user_id=DEFAULT_USER, **kw: measurements.list_measurements(user_id, **kw), True, ["数据"]))
register(_wrap("measurement.latest", "读取某指标最近一次记录",
               lambda user_id=DEFAULT_USER, **kw: measurements.latest(user_id, **kw), True, ["数据"]))
register(_wrap("measurement.snapshot", "三高指标快照（每个指标的最近值 + 风险等级）",
               lambda user_id=DEFAULT_USER: measurements.snapshot(user_id), True, ["数据"]))
register(_wrap("trend.analyze", "对某指标做趋势统计：均值、极值、斜率、超出参考范围次数",
               lambda user_id=DEFAULT_USER, **kw: trends.analyze(user_id, **kw), True, ["分析"]))
register(_wrap("trend.overview", "多指标趋势总览",
               lambda user_id=DEFAULT_USER, **kw: trends.overview(user_id, **kw), True, ["分析"]))
register(_wrap("lab.parse", "解析粘贴的检验单文本，返回待人工确认的指标候选（不直接入库）",
               lambda text: lab_report.parse_text(text), True, ["数据", "检验单"]))
register(_wrap("lab.commit", "把用户核对确认后的检验单指标写入数据库",
               lambda user_id=DEFAULT_USER, **kw: lab_report.commit(user_id, **kw), False, ["数据", "检验单"]))
register(_wrap("med.list", "读取当前用药计划",
               lambda user_id=DEFAULT_USER: medications.list_meds(user_id), True, ["用药"]))
register(_wrap("med.add", "新增或更新一条用药计划（由用户陈述，不判断剂量是否合理）",
               lambda user_id=DEFAULT_USER, **kw: medications.add_med(user_id, **kw), False, ["用药"]))
register(_wrap("med.log", "记录一次服药打卡",
               lambda user_id=DEFAULT_USER, **kw: medications.log_dose(user_id, **kw), False, ["用药"]))
register(_wrap("med.adherence", "统计近 N 天用药依从率",
               lambda user_id=DEFAULT_USER, **kw: medications.adherence(user_id, **kw), True, ["用药"]))
register(_wrap("med.today", "今日服药时间表与完成情况",
               lambda user_id=DEFAULT_USER: medications.today_schedule(user_id), True, ["用药"]))
register(_wrap("drug.check", "共病药物联动规则检查（相互作用、代谢影响、监测建议）",
               lambda user_id=DEFAULT_USER, **kw: interactions.check(user_id=user_id, **kw), True, ["用药", "核心"]))
register(_wrap("plan.generate", "生成 7 日可执行方案（餐食、运动、测量、服药）",
               lambda user_id=DEFAULT_USER, **kw: plan.generate(user_id, **kw), False, ["方案"]))
register(_wrap("report.weekly", "生成周期健康管理报告",
               lambda user_id=DEFAULT_USER, **kw: reports.weekly(user_id, **kw), False, ["报告"]))
register(_wrap("task.today", "读取今日任务卡",
               lambda user_id=DEFAULT_USER: tasks.ensure_today(user_id), True, ["任务"]))
register(_wrap("task.toggle", "勾选/取消今日任务",
               lambda user_id=DEFAULT_USER, **kw: tasks.toggle(user_id, **kw), False, ["任务"]))

# 明确禁止的能力（安全边界，写在代码里而不是提示词里）
FORBIDDEN = [
    "开具处方", "调整药物剂量", "增加/减少药量", "停药建议", "诊断疾病",
    "解读为确诊结论", "预测寿命或预后", "替代医生", "急救判断",
]


class ToolError(Exception):
    pass


def call(name: str, **kwargs) -> dict:
    started = time.time()
    tool = TOOLS.get(name)
    if tool is None:
        return {
            "tool": name,
            "ok": False,
            "elapsed_ms": 0.0,
            "error": f"未注册的工具：{name}（受控白名单机制已拦截）",
        }
    try:
        result = tool.fn(**kwargs)
        return {
            "tool": name,
            "ok": True,
            "readonly": tool.readonly,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
            "result": result,
        }
    except Exception as exc:  # 工具内部异常不抛出到对话层
        return {
            "tool": name,
            "ok": False,
            "elapsed_ms": round((time.time() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=2),
        }


def catalog() -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "readonly": t.readonly, "tags": t.tags}
        for t in TOOLS.values()
    ]
