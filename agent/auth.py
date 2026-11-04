# -*- coding: utf-8 -*-
"""会话与访问控制：让「本地演示」和「对外分享」是两种明确不同的模式。

两种运行模式
-----------
1. **本地单机模式（默认）**：不设 `APP_PASSWORD`，服务强制只监听 127.0.0.1，
   首次访问自动发放会话 Cookie，只有本机能访问，不需要密码。
2. **共享演示模式**：设置 `APP_PASSWORD` 后，任何 /api 请求都要求先登录；
   适合把地址发给评委或部署到局域网/云主机。

设计要点
--------
- 用户身份由服务端会话决定，**不接受客户端传入 user 参数**（防止越权读取他人数据）；
- 登录失败按 IP 限流（5 次 / 5 分钟），避免暴力尝试；
- POST 请求校验 Origin，配合 SameSite=Lax Cookie 降低 CSRF 风险；
- 所有写操作与登录事件写入 `data/audit.log`（JSONL），便于事后追溯。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from config import APP_PASSWORD, DATA_DIR, DEFAULT_USER, SESSION_TTL_HOURS

COOKIE_NAME = "zhsg_session"
SESSION_TTL = SESSION_TTL_HOURS * 3600   # 默认 48 小时（评委模式）/ 12 小时
MAX_LOGIN_FAILS = 5
LOGIN_WINDOW = 300               # 5 分钟
AUDIT_FILE = DATA_DIR / "audit.log"
AUDIT_MAX_BYTES = 512 * 1024


class SessionStore:
    """会话存储：内存做快表，SQLite 做持久层。

    只放内存会有一个致命问题：服务一重启（部署、崩溃、休眠唤醒），
    所有 Cookie 作废，用户再进来就是“新的人”，看到的是另一份数据。
    所以这里写穿到 sessions 表，重启后能凭同一个 Cookie 认出同一个人。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _persist(self, token: str, user_id: str, created: float) -> None:
        try:
            from data import db
            db.execute(
                "INSERT OR REPLACE INTO sessions (token_hash, user_id, created_at, expires_at) "
                "VALUES (?,?,?,?)",
                (self._hash(token), user_id, db.now_iso(), created + SESSION_TTL))
        except Exception:
            pass  # 持久化失败不影响当次会话（只是重启后需要重新登录）

    def create(self, user_id: str = DEFAULT_USER) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            if len(self._sessions) > 500:      # 防止无限增长
                self._prune(now)
            self._sessions[token] = {"user_id": user_id, "created": now, "seen": now}
        self._persist(token, user_id, now)
        return token

    def get(self, token: str | None) -> dict | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            sess = self._sessions.get(token)
            if sess:
                if now - sess["created"] > SESSION_TTL:
                    self._sessions.pop(token, None)
                    return None
                sess["seen"] = now
                return sess

        # 内存里没有（多半是服务重启过）：从 SQLite 恢复
        try:
            from data import db
            row = db.query_one(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash=?", (self._hash(token),))
        except Exception:
            return None
        if not row:
            return None
        if float(row["expires_at"]) < now:
            self.revoke(token)
            return None
        sess = {"user_id": row["user_id"], "created": float(row["expires_at"]) - SESSION_TTL,
                "seen": now}
        with self._lock:
            self._sessions[token] = sess
        return sess

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)
        try:
            from data import db
            db.execute("DELETE FROM sessions WHERE token_hash=?", (self._hash(token),))
        except Exception:
            pass

    def _prune(self, now: float) -> None:
        for tok in [t for t, s in self._sessions.items() if now - s["created"] > SESSION_TTL]:
            self._sessions.pop(tok, None)

    def purge_expired_db(self) -> int:
        try:
            from data import db
            return db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        except Exception:
            return 0


STORE = SessionStore()

# 登录限流：ip -> [时间戳]
_FAILS: dict[str, list[float]] = {}
_FAIL_LOCK = threading.Lock()


def login_allowed(ip: str) -> bool:
    now = time.time()
    with _FAIL_LOCK:
        hits = [t for t in _FAILS.get(ip, []) if now - t < LOGIN_WINDOW]
        _FAILS[ip] = hits
        return len(hits) < MAX_LOGIN_FAILS


def record_login_fail(ip: str) -> None:
    with _FAIL_LOCK:
        _FAILS.setdefault(ip, []).append(time.time())


_PASSWORD = APP_PASSWORD


def set_password(password: str) -> None:
    """命令行 --password 覆盖 .env 里的 APP_PASSWORD。"""
    global _PASSWORD
    _PASSWORD = (password or "").strip()


def check_password(password: str) -> bool:
    if not _PASSWORD:
        return True
    return hmac.compare_digest((password or "").encode("utf-8"), _PASSWORD.encode("utf-8"))


def password_required() -> bool:
    return bool(_PASSWORD)


def parse_cookie(header: str | None) -> dict:
    out: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


def session_cookie(token: str, max_age: int = SESSION_TTL) -> str:
    return f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"


def clear_cookie() -> str:
    return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"


# ---------------------------------------------------------------- 评委模式辅助
def new_demo_user() -> str:
    """每个浏览器会话一个独立演示用户，互不污染。"""
    return "u_demo_" + secrets.token_hex(4)


_MSG_HITS: dict[str, list[float]] = {}
_MSG_LOCK = threading.Lock()


def rate_ok(key: str, limit: int) -> bool:
    """简单限流：同一会话每小时最多 N 条消息（limit<=0 表示不限）。"""
    if limit <= 0:
        return True
    now = time.time()
    with _MSG_LOCK:
        hits = [t for t in _MSG_HITS.get(key, []) if now - t < 3600]
        if len(hits) >= limit:
            _MSG_HITS[key] = hits
            return False
        hits.append(now)
        _MSG_HITS[key] = hits
    return True


def audit(event: str, **fields) -> None:
    """写入审计日志（JSONL，超过 512KB 自动轮换）。"""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > AUDIT_MAX_BYTES:
            AUDIT_FILE.replace(AUDIT_FILE.with_suffix(".log.1"))
        rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": event, **fields}
        with AUDIT_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
