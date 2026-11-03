# -*- coding: utf-8 -*-
"""知识库检索引擎（零第三方依赖）。

能力：
- 扫描 knowledge/docs 下的 .md/.txt/.docx 文档（可随时新增文件，热加载）
- 解析 frontmatter 元数据（标题 / 来源 / 机构 / 年份 / 等级 / 主题）
- 按标题层级切分为语义块
- 中文二元组分词 + BM25 排序，返回可溯源的片段
- 生成 knowledge/index.json 供前端展示知识库状态
"""
from __future__ import annotations

import json
import math
import re
import time
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from config import DOCS_DIR, INDEX_FILE, KNOWLEDGE_DIR

CJK = r"\u4e00-\u9fff"
_TOKEN_RE = re.compile(rf"[{CJK}]+|[A-Za-z][A-Za-z0-9\-]+|\d+(?:\.\d+)?")
_STOP = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "会", "着", "没有", "看", "好", "自己",
    "这", "那", "什么", "怎么", "如何", "可以", "请问", "一下", "现在", "我的",
}

SUPPORTED_SUFFIXES = {".md", ".txt", ".markdown"}
MAX_CHUNK = 460
OVERLAP = 80

# 单字召回白名单：只保留真正有区分度的领域单字，避免“的/了/是”式噪声
SINGLE_TERMS = {"盐", "油", "糖", "药", "压", "脂", "尿", "肾", "肝", "脑", "心",
                "钾", "钙", "酒", "烟", "睡", "走"}

# 口语 → 指南用语的同义扩展（中文检索的关键）
SYNONYMS = {
    "中风": "卒中 脑卒中",
    "脑梗": "卒中 脑卒中",
    "心梗": "心肌梗死 胸痛",
    "心绞痛": "胸痛 冠心病",
    "三高": "高血压 糖尿病 血脂异常",
    "血压高": "高血压",
    "血糖高": "高血糖 糖尿病",
    "血脂高": "血脂异常",
    "尿酸高": "高尿酸血症",
    "降糖": "血糖 糖尿病",
    "降脂": "血脂 他汀",
    "副作用": "不良反应",
    "忌口": "饮食 禁忌",
    "少吃盐": "限盐 食盐",
    "控盐": "限盐 食盐",
    "头晕": "眩晕 低血压",
    "心慌": "心悸",
    "早上": "清晨 晨峰",
    "早晨": "清晨 晨峰",
    "尿酸": "高尿酸 痛风",
    "痛风": "高尿酸",
    # 英文缩写与口语混用（用户常写 LDL、A1c，正文里是 LDL-C、HbA1c）
    "ldl": "LDL-C 低密度 胆固醇",
    "hdl": "HDL-C 高密度",
    "tc": "总胆固醇",
    "tg": "甘油三酯",
    "a1c": "HbA1c 糖化血红蛋白 糖化",
    "糖化": "HbA1c 糖化血红蛋白",
    # 新增主题的日常说法
    "量血压": "血压测量 家庭血压",
    "血压计": "血压测量 上臂式",
    "复查": "随访 复诊 复查",
    "复诊": "随访 复查",
    "漏服": "漏服 依从",
    "忘了吃药": "漏服",
    "肾": "肾脏 eGFR 尿蛋白",
    "泡沫尿": "尿蛋白 微量白蛋白",
    "心脑血管": "心血管 卒中 冠心病 风险分层",
    "风险分层": "极高危 高危 危险分层",
}

# 主题词表：问题里出现这些词时，同主题文档加权，显著改善中文短查询的命中质量
TOPIC_HINTS = {
    "膳食": ["盐", "食盐", "钠", "饮食", "食谱", "烹调", "油", "主食", "碳水", "水果",
             "蔬菜", "蛋白", "食物", "限盐", "吃多少", "能吃", "喝"],
    "高血压": ["血压", "降压", "高血压", "收缩压", "舒张压"],
    "糖尿病": ["血糖", "糖尿病", "糖化", "低血糖", "胰岛素", "降糖", "空腹"],
    "血脂异常": ["血脂", "胆固醇", "甘油三酯", "他汀", "LDL", "HDL", "贝特", "低密度"],
    "用药安全": ["药", "副作用", "不良反应", "相互作用", "一起吃", "同服", "忌口", "说明书", "联用"],
    "急症": ["急症", "120", "急诊", "胸痛", "卒中", "中风", "昏迷", "抽搐", "急救", "危险"],
    "基层管理": ["基层", "随访", "转诊", "家庭医生", "社区", "复诊"],
    "运动与行为": ["运动", "锻炼", "快走", "太极", "习惯", "坚持", "依从", "打卡"],
    "指标判读": ["指标", "参考范围", "检验单", "怎么看", "正常值", "单位", "判读"],
    "流行病学": ["患病率", "多少人", "疾病负担", "流行病", "背景数据"],
}


@dataclass
class Chunk:
    doc_id: str
    doc_title: str
    heading: str
    text: str
    meta: dict = field(default_factory=dict)
    tf: dict = field(default_factory=dict)
    length: int = 0
    heading_tokens: set = field(default_factory=set)


@dataclass
class Document:
    doc_id: str
    path: str
    title: str
    meta: dict
    size: int
    mtime: float
    chunks: int = 0


def _tokenize(text: str) -> list[str]:
    """中文：二元组为主信号 + 少量领域单字；英文与数字整词。"""
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        tok = m.group(0).lower()
        if re.fullmatch(rf"[{CJK}]+", tok):
            if len(tok) == 1:
                if tok not in _STOP:
                    out.append(tok)
            else:
                for i in range(len(tok) - 1):
                    bg = tok[i:i + 2]
                    if bg not in _STOP:
                        out.append(bg)
                for ch in tok:
                    if ch in SINGLE_TERMS:
                        out.append(ch)
        else:
            if tok not in _STOP:
                out.append(tok)
    return [t for t in out if t not in _STOP]


def _expand(query: str) -> list[str]:
    extra: list[str] = []
    low = (query or "").lower()
    for k, v in SYNONYMS.items():
        # 英文缩写大小写不敏感（LDL / ldl 都算）
        if k in query or (k.isascii() and k in low):
            extra.extend(_tokenize(v))
    return extra


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    meta: dict = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            block = parts[1]
            for line in block.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if k:
                        meta[k] = v
            return meta, parts[2].lstrip("\n")
    return meta, raw


def read_docx_text(path: Path) -> str:
    """用标准库解析 .docx（不依赖 python-docx）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as fh:
                xml = fh.read().decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        lines = [ln.strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)
    except Exception:
        return ""


def _split_blocks(body: str) -> list[tuple[str, str]]:
    """按 markdown 标题切块，返回 [(heading, text)]。"""
    blocks: list[tuple[str, list[str]]] = []
    current_heading = "正文"
    buf: list[str] = []
    for line in body.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if m:
            if buf:
                blocks.append((current_heading, buf))
            current_heading = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        blocks.append((current_heading, buf))

    out: list[tuple[str, str]] = []
    for heading, lines in blocks:
        text = "\n".join(lines).strip()
        if not text:
            continue
        # 超长块按段落二次切分
        if len(text) <= MAX_CHUNK:
            out.append((heading, text))
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        cur = ""
        for p in paras:
            if len(cur) + len(p) + 2 <= MAX_CHUNK:
                cur = (cur + "\n" + p).strip()
            else:
                if cur:
                    out.append((heading, cur))
                cur = p
        if cur:
            out.append((heading, cur))
    return out


class KnowledgeBase:
    def __init__(self, docs_dir: Path = DOCS_DIR) -> None:
        self.docs_dir = docs_dir
        self.docs: list[Document] = []
        self.chunks: list[Chunk] = []
        self._sig: tuple = ()
        self._df: dict = {}
        self._avgdl: float = 1.0
        self.loaded_at: float = 0.0

    # ---------------- 加载 ----------------
    def _signature(self) -> tuple:
        sig = []
        if self.docs_dir.exists():
            for p in sorted(self.docs_dir.iterdir()):
                if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES | {".docx"}:
                    st = p.stat()
                    sig.append((p.name, st.st_size, int(st.st_mtime)))
        return tuple(sig)

    def reload_if_changed(self) -> bool:
        sig = self._signature()
        if sig != self._sig:
            self.build()
            return True
        return False

    def build(self) -> None:
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.docs = []
        self.chunks = []
        for path in sorted(self.docs_dir.iterdir()):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in {".md", ".markdown", ".txt"}:
                raw = path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".docx":
                raw = read_docx_text(path)
            else:
                continue
            if not raw.strip():
                continue
            meta, body = _parse_frontmatter(raw)
            doc_id = path.stem
            title = meta.get("title") or path.stem
            blocks = _split_blocks(body)
            doc = Document(
                doc_id=doc_id,
                path=str(path),
                title=title,
                meta=meta,
                size=path.stat().st_size,
                mtime=path.stat().st_mtime,
                chunks=len(blocks),
            )
            self.docs.append(doc)
            for heading, text in blocks:
                toks = _tokenize(f"{title} {heading} {text}")
                tf: dict = {}
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
                self.chunks.append(
                    Chunk(
                        doc_id=doc_id,
                        doc_title=title,
                        heading=heading,
                        text=text,
                        meta=meta,
                        tf=tf,
                        length=max(1, len(toks)),
                        heading_tokens=set(_tokenize(heading)),
                    )
                )
        self._df = {}
        for c in self.chunks:
            for t in c.tf:
                self._df[t] = self._df.get(t, 0) + 1
        # 文档 → 主题集合（用于查询侧加权）
        self._doc_topics = {}
        for d in self.docs:
            topics = set()
            tag = (d.meta.get("topic") or "").strip()
            if tag:
                topics.add(tag)
            for key in TOPIC_HINTS:
                if key in d.title:
                    topics.add(key)
            self._doc_topics[d.doc_id] = topics
        self._avgdl = (sum(c.length for c in self.chunks) / len(self.chunks)) if self.chunks else 1.0
        self._sig = self._signature()
        self.loaded_at = time.time()
        self._write_index()

    # ---------------- 检索 ----------------
    def search(self, query: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []
        # 原始词权重 1.0；同义扩展词权重 0.45，避免扩展词喧宾夺主
        weights: dict[str, float] = {}
        for t in _tokenize(query):
            weights[t] = 1.0
        for t in _expand(query):
            weights.setdefault(t, 0.45)
        if not weights:
            return []
        uniq = list(weights.keys())
        n = len(self.chunks)
        k1, b = 1.5, 0.75

        # 查询侧主题识别
        q_topics = {key for key, words in TOPIC_HINTS.items() if any(w in query for w in words)}

        scored: list[tuple[float, Chunk]] = []
        for c in self.chunks:
            score = 0.0
            matched = 0
            for t, w in weights.items():
                f = c.tf.get(t, 0)
                if not f:
                    continue
                matched += w
                df = self._df.get(t, 0) or 1
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = f + k1 * (1 - b + b * c.length / self._avgdl)
                score += w * idf * (f * (k1 + 1)) / denom
            if matched == 0:
                continue
            score *= 1 + 0.08 * matched
            if any(t in c.doc_title.lower() for t in uniq[:3]):
                score *= 1.15
            head_hit = len(c.heading_tokens & set(uniq))
            if head_hit:
                score *= 1 + 0.12 * min(3, head_hit)
            doc_topics = self._doc_topics.get(c.doc_id, set())
            hit_topics = q_topics & doc_topics
            if hit_topics:
                score *= 1 + 0.45 * min(2, len(hit_topics))
            # 「本页不回答什么 / 边界说明」这类段落几乎不含医学内容，不该被当作依据
            if any(w in c.heading for w in ("不回答", "边界", "免责", "声明")):
                score *= 0.35
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        seen = set()
        for score, c in scored:
            key = (c.doc_id, c.heading)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "doc_id": c.doc_id,
                    "title": c.doc_title,
                    "heading": c.heading,
                    "text": c.text,
                    "score": round(score, 3),
                    "source": c.meta.get("source", c.doc_title),
                    "org": c.meta.get("org", ""),
                    "year": c.meta.get("year", ""),
                    "level": c.meta.get("level", ""),
                    "topic": c.meta.get("topic", ""),
                    "url": c.meta.get("url", ""),
                }
            )
            if len(results) >= k:
                break
        return results

    # ---------------- 索引文件 ----------------
    def _write_index(self) -> None:
        payload = {
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.loaded_at)),
            "doc_count": len(self.docs),
            "chunk_count": len(self.chunks),
            "docs": [
                {
                    "doc_id": d.doc_id,
                    "title": d.title,
                    "file": Path(d.path).name,
                    "size": d.size,
                    "chunks": d.chunks,
                    "source": d.meta.get("source", d.title),
                    "org": d.meta.get("org", ""),
                    "year": d.meta.get("year", ""),
                    "level": d.meta.get("level", ""),
                    "topic": d.meta.get("topic", ""),
                    "url": d.meta.get("url", ""),
                }
                for d in self.docs
            ],
        }
        try:
            INDEX_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def status(self) -> dict:
        try:
            index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:
            index = {"docs": [], "doc_count": len(self.docs), "chunk_count": len(self.chunks)}
        return index

    # ---------------- 新增文档 ----------------
    def add_document(self, filename: str, content: str) -> str:
        safe = re.sub(r"[\\/:*?\"<>|]+", "_", filename or "upload.md").strip()
        if not re.search(r"\.(md|markdown|txt)$", safe, re.I):
            safe += ".md"
        path = self.docs_dir / safe
        if path.exists():
            stem = path.stem
            path = self.docs_dir / f"{stem}_{int(time.time())}{path.suffix}"
        path.write_text(content, encoding="utf-8")
        self.build()
        return path.name

    def add_docx(self, filename: str, data: bytes) -> str:
        safe = re.sub(r"[\\/:*?\"<>|]+", "_", filename or "upload.docx").strip()
        if not safe.lower().endswith(".docx"):
            safe += ".docx"
        path = self.docs_dir / safe
        if path.exists():
            path = self.docs_dir / f"{path.stem}_{int(time.time())}{path.suffix}"
        path.write_bytes(data)
        self.build()
        return path.name

    def remove_document(self, doc_id: str) -> bool:
        for p in self.docs_dir.iterdir():
            if p.stem == doc_id:
                p.unlink()
                self.build()
                return True
        return False


KB = KnowledgeBase()


def get_kb() -> KnowledgeBase:
    KB.reload_if_changed()
    return KB
