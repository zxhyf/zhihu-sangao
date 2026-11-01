# -*- coding: utf-8 -*-
"""DeepSeek 大模型客户端（仅用标准库 urllib，无需 openai 包）。

特性：
- 超时 + 重试 + 失败降级（降级后由本地规则引擎接管，功能不中断）
- 健康检查，界面可显示“在线大模型 / 本地规则”状态
- 不在日志中输出 API Key
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT, LLM_MAX_TOKENS, LLM_TEMPERATURE


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, api_key: str = LLM_API_KEY, base_url: str = LLM_BASE_URL,
                 model: str = LLM_MODEL, timeout: float = LLM_TIMEOUT) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------
    def _post(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        return json.loads(raw)

    def chat(self, messages: list[dict], temperature: float | None = None,
             max_tokens: int | None = None, retries: int = 2) -> str:
        if not self.available:
            raise LLMError("未配置 DEEPSEEK_API_KEY")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": LLM_MAX_TOKENS if max_tokens is None else max_tokens,
            "stream": False,
        }
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                data = self._post("/chat/completions", payload)
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"返回内容为空：{str(data)[:200]}")
                msg = choices[0].get("message") or {}
                content = (msg.get("content") or "").strip()
                if not content:
                    raise LLMError("模型返回空文本")
                self.last_error = ""
                return content
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="ignore")[:300]
                except Exception:
                    pass
                last_exc = LLMError(f"HTTP {exc.code}: {body}")
                if exc.code in (401, 403):
                    break
            except Exception as exc:
                last_exc = exc
            time.sleep(0.8 * (attempt + 1))
        self.last_error = str(last_exc)
        raise LLMError(self.last_error)

    def health(self) -> dict:
        if not self.available:
            return {"ok": False, "mode": "local", "message": "未配置 API Key，使用本地规则引擎"}
        started = time.time()
        try:
            text = self.chat([{"role": "user", "content": "回复两个字：正常"}], temperature=0, max_tokens=8, retries=0)
            return {"ok": True, "mode": "llm", "model": self.model,
                    "latency_ms": round((time.time() - started) * 1000),
                    "message": text[:20]}
        except Exception as exc:
            return {"ok": False, "mode": "local", "model": self.model, "message": str(exc)[:200]}


CLIENT = LLMClient()
