# -*- coding: utf-8 -*-
"""全局配置：路径、模型、安全边界常量。

设计原则：零第三方依赖即可运行（仅 Python 标准库）。
若配置了 DeepSeek API Key 则启用大模型叙事生成，否则自动降级为本地规则引擎，
功能与演示流程保持完整。
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
DOCS_DIR = KNOWLEDGE_DIR / "docs"
INDEX_FILE = KNOWLEDGE_DIR / "index.json"
SOURCES_FILE = KNOWLEDGE_DIR / "sources.json"
UI_DIR = BASE_DIR / "ui"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "health.db"
UPLOAD_LOG = DATA_DIR / "uploads.json"

APP_NAME = "智护三高"
APP_SUBTITLE = "三高共病 AI 健康管理智能体"


def _load_dotenv() -> None:
    """极简 .env 解析（不依赖 python-dotenv）。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


_load_dotenv()

# ---------------- 大模型配置 ----------------
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "45"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1000"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.35"))

# ---------------- 服务配置 ----------------
HOST = os.environ.get("APP_HOST", "127.0.0.1")
PORT = int(os.environ.get("APP_PORT", "8600"))
DEFAULT_USER = "u_local"

# ---------------- 安全边界 ----------------
DISCLAIMER = "本建议不构成诊疗意见，请遵医嘱。"
SAFETY_LINE = "本系统仅提供健康管理辅助，不做诊断、不开处方、不调整药物剂量、不替代医生。"
EMERGENCY_NUMBER = "120"

# 指南参考范围（用于“超出参考范围”提示，不设定个人目标、不计算达标率）
REFERENCE_RANGES = {
    "bp_sys": (90, 139, "mmHg", "诊室收缩压参考范围 90–139 mmHg"),
    "bp_dia": (60, 89, "mmHg", "诊室舒张压参考范围 60–89 mmHg"),
    "glucose_fasting": (3.9, 6.1, "mmol/L", "空腹血糖参考范围 3.9–6.1 mmol/L"),
    "glucose_postprandial": (3.9, 7.8, "mmol/L", "餐后 2 小时血糖参考范围 3.9–7.8 mmol/L"),
    "glucose_random": (3.9, 7.8, "mmol/L", "随机血糖参考范围 3.9–7.8 mmol/L"),
    "hba1c": (4.0, 6.5, "%", "HbA1c 参考范围 4.0%–6.5%"),
    "lipid_tc": (2.8, 5.2, "mmol/L", "总胆固醇合适水平 <5.2 mmol/L"),
    "lipid_tg": (0.4, 1.7, "mmol/L", "甘油三酯合适水平 <1.7 mmol/L"),
    "lipid_ldl": (1.0, 3.4, "mmol/L", "LDL-C 参考水平 <3.4 mmol/L（分层目标需医生确定）"),
    "lipid_hdl": (1.0, 2.6, "mmol/L", "HDL-C 参考水平 ≥1.0 mmol/L"),
    "weight": (40.0, 110.0, "kg", "体重参考范围因身高而异"),
    "waist": (50.0, 90.0, "cm", "男性腰围 <90 cm，女性 <85 cm"),
}

# 演示模式（无真实数据时用于展示趋势；正式演示可在界面中清除）
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
