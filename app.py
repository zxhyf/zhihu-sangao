# -*- coding: utf-8 -*-
"""智护三高 · 服务入口（零第三方依赖，仅用 Python 标准库）。

启动：
    python app.py            # 默认 http://127.0.0.1:8600
    python app.py --port 8700
"""
from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (APP_NAME, APP_SUBTITLE, DEFAULT_USER, DISCLAIMER, HOST, LLM_MODEL,
                    PORT, REPORTS_DIR, SOURCES_FILE, UI_DIR, DOCS_DIR, SAFETY_LINE,
                    APP_ENV, APP_PASSWORD, SEED_ON_FIRST_RUN, MAX_MESSAGE_LEN,
                    JUDGE_MODE, ENABLE_ADMIN_API, PREFER_LOCAL, RATE_LIMIT_PER_HOUR,
                    DEMO_USER_TTL_HOURS)
from data import db
from agent import auth, llm, orchestrator
from agent.rag import get_kb
from tools import (interactions, lab_report, measurements, medications, plan as plan_tool,
                   profile as profile_tool, registry, reports, tasks, trends)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "ZhiHuSanGao/1.0"
    _cookie: str | None = None

    # 普通用户不可调用的管理接口（关闭时一律 403，不依赖前端隐藏）
    ADMIN_PATHS = {
        "/api/kb/upload", "/api/kb/delete", "/api/kb/reindex",
        "/api/demo/seed", "/api/demo/clear",
        "/api/tools", "/api/llm/check", "/api/report/save", "/api/drugs",
    }

    def _admin_blocked(self, path: str) -> bool:
        if path in self.ADMIN_PATHS and not ENABLE_ADMIN_API:
            auth.audit("admin_blocked", ip=self.client_address[0], path=path)
            self._json({
                "ok": False,
                "error": "该接口在当前部署下已关闭（管理功能）",
                "code": "admin_disabled",
            }, 403)
            return True
        return False

    # ------------------------------------------------------------------ 基础
    def log_message(self, fmt, *args):  # 降噪
        if os.environ.get("APP_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if getattr(self, "_cookie", None):
            self.send_header("Set-Cookie", self._cookie)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ------------------------------------------------------------------ 会话
    def _current_session(self) -> dict | None:
        cookies = auth.parse_cookie(self.headers.get("Cookie"))
        return auth.STORE.get(cookies.get(auth.COOKIE_NAME))

    def _new_session_user(self) -> str:
        """评委模式：每个浏览器会话一个独立演示用户，首次进入自动种一份演示数据。"""
        if not JUDGE_MODE:
            return DEFAULT_USER
        uid = auth.new_demo_user()
        profile_tool.ensure_profile(uid)
        measurements.seed_demo(uid)
        tasks.ensure_today(uid)
        auth.audit("judge_session_new", user=uid)
        return uid

    def _issue_session(self, user_id: str) -> None:
        token = auth.STORE.create(user_id)
        self._cookie = auth.session_cookie(token)

    def _require_session(self) -> tuple[str | None, bool]:
        """返回 (user_id, 是否已拦截)。身份只来自服务端会话，不接受客户端传入。"""
        sess = self._current_session()
        if sess:
            return sess["user_id"], False
        if not auth.password_required():
            # 本地单机 / 评委模式：首次访问自动建会话
            uid = self._new_session_user()
            self._issue_session(uid)
            return uid, False
        self._json({"ok": False, "error": "未登录或会话已过期", "need_login": True}, 401)
        return None, True

    def _csrf_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True                      # 同源 fetch / curl 通常不带 Origin
        host = self.headers.get("Host", "")
        try:
            return urlparse(origin).netloc == host
        except Exception:
            return False

    def handle_session(self) -> None:
        sess = self._current_session()
        if sess:
            return self._json({"ok": True, "authenticated": True, "user_id": sess["user_id"],
                               "needs_password": auth.password_required()})
        if not auth.password_required():
            uid = self._new_session_user()
            self._issue_session(uid)
            return self._json({"ok": True, "authenticated": True, "user_id": uid,
                               "needs_password": False, "mode": "judge" if JUDGE_MODE else "local"})
        return self._json({"ok": True, "authenticated": False, "needs_password": True})

    def handle_login(self) -> None:
        ip = self.client_address[0]
        if not auth.login_allowed(ip):
            auth.audit("login_throttled", ip=ip)
            return self._json({"ok": False, "error": "尝试次数过多，请 5 分钟后再试"}, 429)
        body = self._json_body()
        if not auth.check_password(body.get("password") or ""):
            auth.record_login_fail(ip)
            auth.audit("login_fail", ip=ip)
            return self._json({"ok": False, "error": "密码不正确"}, 401)
        # 评委模式下每个登录者同样拿到独立演示数据，避免多人共用一份
        uid = self._new_session_user()
        token = auth.STORE.create(uid)
        self._cookie = auth.session_cookie(token)
        auth.audit("login_ok", ip=ip, user=uid)
        return self._json({"ok": True, "authenticated": True, "user_id": uid})

    def handle_logout(self) -> None:
        cookies = auth.parse_cookie(self.headers.get("Cookie"))
        auth.STORE.revoke(cookies.get(auth.COOKIE_NAME))
        self._cookie = auth.clear_cookie()
        auth.audit("logout", ip=self.client_address[0])
        return self._json({"ok": True, "authenticated": False})

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json_bytes(obj))

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            return {}

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        self._cookie = None
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")

            if path in ("/", "/index.html"):
                return self._serve_file(UI_DIR / "index.html")
            if path.startswith("/assets/"):
                name = unquote(path[len("/assets/"):])
                return self._serve_file(UI_DIR / name)
            if path == "/favicon.ico":
                return self._send(204, b"")

            # 公开端点
            if path == "/api/health":
                return self._json({
                    "ok": True,
                    "app": APP_NAME,
                    "env": APP_ENV,
                    "judge_mode": JUDGE_MODE,
                    "admin_api": ENABLE_ADMIN_API,
                    "engine": "local" if (PREFER_LOCAL or not llm.CLIENT.available) else "llm",
                    "auth": {"password_required": auth.password_required(),
                             "bind": HOST},
                    "llm": {"configured": llm.CLIENT.available, "model": LLM_MODEL,
                            "mode": "llm" if llm.CLIENT.available else "local"},
                    "kb": {k: get_kb().status().get(k) for k in ("doc_count", "chunk_count", "built_at")},
                    "tools": len(registry.TOOLS),
                })
            if path == "/api/session":
                return self.handle_session()

            if not path.startswith("/api/"):
                return self._json({"ok": False, "error": "not found"}, 404)

            if self._admin_blocked(path):
                return

            user_id, blocked = self._require_session()
            if blocked:
                return

            if path == "/api/bootstrap":
                return self._json(self.bootstrap(user_id))
            if path == "/api/trends":
                kind = (qs.get("kind") or ["bp"])[0]
                days = int((qs.get("days") or ["30"])[0])
                sub = (qs.get("sub") or [None])[0]
                return self._json(trends.analyze(user_id, kind, sub, days=days, min_points=2))
            if path == "/api/overview":
                return self._json(trends.overview(user_id, int((qs.get("days") or ["30"])[0])))
            if path == "/api/kb":
                return self._json(self.kb_status())
            if path == "/api/sources":
                return self._json(self.load_sources())
            if path == "/api/history":
                rows = db.query(
                    "SELECT id, role, content, blocks, created_at FROM chat_messages WHERE user_id=? ORDER BY id DESC LIMIT 50",
                    (user_id,))
                out = []
                for r in reversed(rows):
                    d = dict(r)
                    try:
                        d["blocks"] = json.loads(d.get("blocks") or "[]")
                    except Exception:
                        d["blocks"] = []
                    out.append(d)
                return self._json({"ok": True, "messages": out})
            if path == "/api/report":
                days = int((qs.get("days") or ["7"])[0])
                return self._json(reports.weekly(user_id, days))
            if path == "/api/meds":
                return self._json({
                    "ok": True,
                    "meds": medications.list_meds(user_id),
                    "schedule": medications.today_schedule(user_id),
                    "adherence": medications.adherence(user_id, 7),
                })
            if path == "/api/plan":
                return self._json(plan_tool.generate(user_id, int((qs.get("days") or ["7"])[0])))
            if path == "/api/tools":
                return self._json({"ok": True, "tools": registry.catalog(), "forbidden": registry.FORBIDDEN})
            if path == "/api/drugs":
                return self._json({"ok": True, "stats": interactions.stats(),
                                   "drugs": [{"name": d["name"], "class": d["class"]}
                                             for d in interactions.all_drugs()]})
            if path == "/api/lab/sample":
                return self._json({"ok": True, "text": lab_report.SAMPLE})
            return self._json({"ok": False, "error": "not found"}, 404)
        except Exception:
            traceback.print_exc()
            return self._json({"ok": False, "error": "服务器内部错误"}, 500)

    def _serve_file(self, path):
        try:
            data = path.read_bytes()
        except Exception:
            return self._json({"ok": False, "error": f"文件不存在：{path.name}"}, 404)
        # 给前端资源加版本号：改了 js/css 后浏览器不会再用旧缓存
        if path.name == "index.html":
            try:
                ver = int(max((UI_DIR / "app.js").stat().st_mtime,
                              (UI_DIR / "styles.css").stat().st_mtime))
                html = data.decode("utf-8")
                html = html.replace("/assets/app.js", f"/assets/app.js?v={ver}")
                html = html.replace("/assets/styles.css", f"/assets/styles.css?v={ver}")
                data = html.encode("utf-8")
            except Exception:
                pass
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, data, ctype)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        self._cookie = None
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")

            if path == "/api/login":
                return self.handle_login()
            if path == "/api/logout":
                return self.handle_logout()

            if not self._csrf_ok():
                auth.audit("csrf_blocked", ip=self.client_address[0], path=path)
                return self._json({"ok": False, "error": "请求来源校验失败"}, 403)

            if self._admin_blocked(path):
                return

            user_id, blocked = self._require_session()
            if blocked:
                return

            if path == "/api/chat":
                body = self._json_body()
                message = (body.get("message") or "").strip()
                if not message:
                    return self._json({"ok": False, "error": "消息不能为空"}, 400)
                if len(message) > MAX_MESSAGE_LEN:
                    return self._json({"ok": False, "error": f"消息过长（上限 {MAX_MESSAGE_LEN} 字）"}, 413)
                if not auth.rate_ok(user_id, RATE_LIMIT_PER_HOUR):
                    return self._json({"ok": False,
                                       "error": f"每小时最多 {RATE_LIMIT_PER_HOUR} 条，请稍后再试"}, 429)
                use_llm = bool(body.get("use_llm", True)) and not PREFER_LOCAL
                result = orchestrator.handle(message, user_id=user_id, use_llm=use_llm)
                return self._json(result)

            if path == "/api/tasks/toggle":
                body = self._json_body()
                return self._json(tasks.toggle(user_id, int(body.get("id") or 0)))

            if path == "/api/meds/log":
                body = self._json_body()
                name = (body.get("name") or "").strip()
                if not name:
                    return self._json({"ok": False, "error": "缺少药名"}, 400)
                res = medications.log_dose(user_id, name, body.get("status") or "taken",
                                           slot=body.get("slot"),
                                           taken_at=body.get("taken_at"))
                code = 200 if res.get("ok") else 400
                return self._json(res, code)

            if path == "/api/meds/add":
                body = self._json_body()
                # 默认「合并去重」：重复的时段自动跳过，不覆盖原有安排；
                # 只有「改时段」显式传 op=replace 时才整体替换。
                res = medications.upsert_times(
                    user_id, body.get("name") or "", body.get("dose") or "",
                    body.get("times") or ["08:00"],
                    (body.get("op") or "merge").lower())
                code = 200 if res.get("ok") else 400
                return self._json(res, code)

            if path == "/api/meds/stop":
                body = self._json_body()
                ok = medications.stop_med(user_id, (body.get("name") or "").strip())
                return self._json({"ok": ok}, 200 if ok else 404)

            if path == "/api/meds/apply":
                body = self._json_body()
                action = (body.get("action") or "").strip()
                items = body.get("items") or []
                if action not in ("upsert", "stop") or not items:
                    return self._json({"ok": False, "error": "参数不完整"}, 400)
                added, updated, removed = [], [], []
                op = (body.get("op") or "merge").lower()
                for it in items:
                    name = (it.get("name") or "").strip()
                    if not name:
                        continue
                    if action == "stop":
                        if medications.stop_med(user_id, name):
                            removed.append(name)
                        continue
                    res = medications.upsert_times(user_id, name, it.get("dose") or "",
                                                   it.get("times") or ["08:00"], op)
                    if res.get("mode") == "add":
                        added.append(name)
                    else:
                        updated.append({"name": name, "times": res["times"],
                                        "added": res["added"], "mode": res["mode"]})
                if action == "stop" and not removed:
                    return self._json({"ok": False,
                                       "error": "清单里没有这些药，未做修改。"}, 404)
                if action == "stop":
                    reply = f"已从「用药打卡」清单移除：{'、'.join(removed)}。这只是停止打卡提醒，不代表可以停药。"
                else:
                    parts = []
                    if added:
                        parts.append(f"已添加：{'、'.join(added)}")
                    if updated:
                        detail = "；".join(
                            f"{u['name']} 现在 {'、'.join(u['times'])}"
                            + (f"（新增 {'、'.join(u['added'])}）" if u["added"] else "（无新增）")
                            for u in updated)
                        parts.append(f"已更新：{detail}")
                    reply = "；".join(parts) + "。"
                auth.audit("med_plan_apply", ip=self.client_address[0], action=action,
                           op=op, added=added, updated=[u["name"] for u in updated],
                           removed=removed)
                return self._json({"ok": True, "action": action, "added": added,
                                   "updated": updated, "removed": removed, "reply": reply,
                                   "meds": medications.list_meds(user_id),
                                   "schedule": medications.today_schedule(user_id)})

            if path == "/api/drug/check":
                body = self._json_body()
                return self._json(interactions.check(body.get("names") or [], text=body.get("text") or "",
                                                     user_id=user_id))

            if path == "/api/lab/parse":
                body = self._json_body()
                return self._json(lab_report.parse_text(body.get("text") or ""))

            if path == "/api/lab/commit":
                body = self._json_body()
                res = lab_report.commit(user_id, body.get("items") or [],
                                        body.get("measured_at") or "")
                res["snapshot"] = measurements.snapshot(user_id)
                return self._json(res)

            if path == "/api/lab/sample":
                return self._json({"ok": True, "text": lab_report.SAMPLE})

            if path == "/api/profile":
                body = self._json_body()
                res = profile_tool.update_profile_checked(user_id, body)
                return self._json(res, 200 if res.get("ok") else 400)

            if path == "/api/kb/upload":
                name = (qs.get("name") or ["upload.md"])[0]
                raw = self._body()
                if not raw:
                    return self._json({"ok": False, "error": "文件内容为空"}, 400)
                if len(raw) > 2 * 1024 * 1024:
                    return self._json({"ok": False, "error": "文件过大（上限 2 MB）"}, 413)
                if name.lower().endswith(".docx"):
                    saved = get_kb().add_docx(name, raw)
                else:
                    text = raw.decode("utf-8", errors="ignore")
                    saved = get_kb().add_document(name, text)
                st = self.kb_status()
                db.execute("INSERT OR REPLACE INTO kb_files (name, size, chunks, added_at, note) VALUES (?,?,?,?,?)",
                           (saved, len(raw), st.get("chunk_count", 0), db.now_iso(), "由界面导入"))
                auth.audit("kb_upload", ip=self.client_address[0], file=saved, size=len(raw))
                return self._json({"ok": True, "saved": saved, "kb": st})

            if path == "/api/kb/reindex":
                get_kb().build()
                return self._json({"ok": True, "kb": self.kb_status()})

            if path == "/api/kb/delete":
                body = self._json_body()
                ok = get_kb().remove_document(body.get("doc_id") or "")
                auth.audit("kb_delete", ip=self.client_address[0], doc_id=body.get("doc_id"))
                return self._json({"ok": ok, "kb": self.kb_status()})

            if path == "/api/kb/search":
                body = self._json_body()
                q = (body.get("q") or "").strip()
                return self._json({"ok": True, "results": get_kb().search(q, k=6)})

            if path == "/api/demo/reset":
                # 用户自助：只重置「自己这份」演示数据，不触碰别人
                measurements.clear(user_id)
                profile_tool.ensure_profile(user_id)
                measurements.seed_demo(user_id)
                tasks.ensure_today(user_id)
                auth.audit("demo_reset", ip=self.client_address[0], user=user_id)
                return self._json({"ok": True, "message": "已恢复你这边的演示数据"})

            if path == "/api/demo/seed":
                n = measurements.seed_demo(user_id)
                msg = f"已写入 {n} 条演示记录" if n else "演示数据已存在，未重复写入"
                return self._json({"ok": True, "inserted": n, "message": msg})

            if path == "/api/demo/clear":
                body = self._json_body()
                if (body.get("confirm") or "").strip().upper() != "CLEAR":
                    return self._json({
                        "ok": False,
                        "error": "需要二次确认：请在请求体中传 confirm=CLEAR",
                        "scope": ["测量记录", "用药计划与打卡", "任务卡", "对话记录", "风险事件"],
                    }, 400)
                scope = (body.get("scope") or "all").lower()
                if scope == "demo":
                    n = measurements.clear_demo(user_id)
                    auth.audit("demo_clear", ip=self.client_address[0], user=user_id, rows=n)
                    return self._json({"ok": True, "scope": "demo", "removed": n})
                measurements.clear(user_id)
                auth.audit("data_clear", ip=self.client_address[0], user=user_id, scope="all")
                return self._json({"ok": True, "scope": "all"})

            if path == "/api/llm/check":
                return self._json(llm.CLIENT.health())

            if path == "/api/report/save":
                rep = reports.weekly(user_id, 7)
                REPORTS_DIR.mkdir(parents=True, exist_ok=True)
                fname = f"健康管理报告_{time.strftime('%Y%m%d_%H%M')}.md"
                (REPORTS_DIR / fname).write_text(rep["markdown"], encoding="utf-8")
                return self._json({"ok": True, "file": str(REPORTS_DIR / fname), "name": fname})

            return self._json({"ok": False, "error": "not found"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    # ------------------------------------------------------------------ 数据组装
    def load_sources(self) -> dict:
        try:
            return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"meta": {}, "sources": []}

    def kb_status(self) -> dict:
        st = get_kb().status()
        st["dir"] = str(DOCS_DIR)
        st["supported"] = [".md", ".txt", ".docx"]
        return st

    def bootstrap(self, user_id: str) -> dict:
        kb = get_kb()
        prof = profile_tool.get_profile(user_id)
        snap = measurements.snapshot(user_id)
        meds = medications.list_meds(user_id)
        task_items = tasks.ensure_today(user_id)
        task_stats = tasks.stats_today(user_id)
        return {
            "ok": True,
            "app": {"name": APP_NAME, "subtitle": APP_SUBTITLE,
                    "safety_line": SAFETY_LINE, "disclaimer": DISCLAIMER},
            "profile": prof,
            "snapshot": snap,
            "meds": meds,
            "tasks": task_items,
            "task_stats": task_stats,
            "adherence": medications.adherence(user_id, 7),
            "kb": self.kb_status(),
            "mode": {"llm": llm.CLIENT.available, "model": LLM_MODEL,
                     "label": "在线大模型（DeepSeek）" if llm.CLIENT.available else "本地规则引擎"},
            "drug_stats": interactions.stats(),
            "sources": self.load_sources(),
            "tools": registry.catalog(),
            "forbidden": registry.FORBIDDEN,
            "counts": {"measurements": measurements.count(user_id),
                       "measurements_7d": measurements.count(user_id, 7)},
            "demo": self.demo_info(user_id),
            "env": APP_ENV,
            "judge": self.judge_info(),
        }

    def judge_info(self) -> dict:
        engine = "local" if (PREFER_LOCAL or not llm.CLIENT.available) else "llm"
        return {
            "mode": JUDGE_MODE,
            "admin_enabled": ENABLE_ADMIN_API,
            "engine": engine,
            "engine_label": "本地运行 · 无需联网" if engine == "local" else f"在线大模型（{LLM_MODEL}）",
            "notice": "页面里的数字是系统生成的示例数据，不是你的真实病历。",
            "questions": [
                {"label": "记录一次血压", "q": "今天血压 150/95"},
                {"label": "看看最近怎么样", "q": "我最近血压怎么样"},
                {"label": "关于停药", "q": "我想把氨氯地平停掉"},
                {"label": "不舒服时", "q": "我胸口疼，还喘不上气"},
                {"label": "日常饮食", "q": "三高人群每天能吃多少盐"},
                {"label": "排一周的饭", "q": "给我一份 7 天方案"},
                {"label": "安排吃药时间", "q": "我每天早上8点吃一片氨氯地平"},
            ],
            "steps": [
                {"t": "1", "title": "记录一次指标",
                 "desc": "说「今天血压 150/95」，系统会帮你记下来，并说明这次读数的情况"},
                {"t": "2", "title": "记录吃药",
                 "desc": "打开「用药打卡」，按时间点勾选今天是否已经服药"},
                {"t": "3", "title": "身体不舒服时",
                 "desc": "说「我胸口疼，还喘不上气」，系统不会给建议，而是提醒你尽快就医"},
            ],
        }

    def demo_info(self, user_id: str) -> dict:
        """演示数据提示：让用户随时知道屏幕上的数字是合成的还是自己录的。"""
        demo_count = db.query_one(
            "SELECT COUNT(*) AS c FROM measurements WHERE user_id=? AND source='demo'", (user_id,))["c"]
        real_count = db.query_one(
            "SELECT COUNT(*) AS c FROM measurements WHERE user_id=? AND source!='demo'", (user_id,))["c"]
        return {"has_demo": demo_count > 0, "demo_count": demo_count, "real_count": real_count,
                "env": APP_ENV}


def pick_port(host: str, port: int) -> int:
    for candidate in range(port, port + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return port


def banner(url: str, port: int, seeded: bool, host: str) -> None:
    line = "─" * 58
    print(f"\n  {APP_NAME} · {APP_SUBTITLE}")
    print(f"  {line}")
    print(f"  ▸ 访问地址   {url}")
    mode_label = ("评委体验（每会话独立演示数据）" if JUDGE_MODE else
                  "共享演示（需登录密码）" if auth.password_required() else "本地单机（仅本机可访问）")
    print(f"  ▸ 运行模式   {mode_label}　环境：{APP_ENV}")
    print(f"  ▸ 管理接口   {'开启' if ENABLE_ADMIN_API else '关闭（普通用户不能改知识库/清空数据）'}")
    print(f"  ▸ 生成引擎   {'本地规则优先（不依赖网络）' if PREFER_LOCAL else '优先大模型，失败自动降级'}")
    print(f"  ▸ 监听地址   {host}" + ("" if auth.password_required() or host in ("127.0.0.1", "localhost")
                                  else "　⚠️ 未设密码却对外监听，已强制回收为本机"))
    print(f"  ▸ 大模型     {'已连接 DeepSeek（' + LLM_MODEL + '）' if llm.CLIENT.available else '未配置，使用本地规则引擎'}")
    print(f"  ▸ 知识库     {get_kb().status().get('doc_count', 0)} 篇文档 / "
          f"{get_kb().status().get('chunk_count', 0)} 个片段（{DOCS_DIR}）")
    print(f"  ▸ 数据库     {db.db_path()}")
    print(f"  ▸ 演示数据   {'已写入（界面会标注）' if seeded else '沿用已有数据'}")
    print(f"  {line}")
    print("  按 Ctrl+C 停止服务\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="智护三高 · 三高共病 AI 健康管理智能体")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-seed", action="store_true", help="不写入演示数据")
    parser.add_argument("--password", default="", help="共享演示模式：设置访问密码")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 命令行密码优先生效（--password），否则用 .env 里的 APP_PASSWORD
    if args.password:
        auth.set_password(args.password)

    # 没有密码就不允许对外监听：这是防止健康数据被局域网他人读取的最低保障
    host = args.host
    if not auth.password_required():
        if host not in ("127.0.0.1", "localhost"):
            print(f"  ⚠️ 未设置访问密码，拒绝监听 {host}，已回退到 127.0.0.1")
            host = "127.0.0.1"

    db.init_db()
    profile_tool.ensure_profile(DEFAULT_USER)
    get_kb().build()

    if JUDGE_MODE:
        purged = db.purge_inactive_demo_users(DEMO_USER_TTL_HOURS)
        if purged:
            print(f"  ▸ 已清理 {purged} 个过期的演示用户（{DEMO_USER_TTL_HOURS} 小时无活动）")

    seeded = False
    if not args.no_seed and SEED_ON_FIRST_RUN and measurements.count(DEFAULT_USER) == 0:
        measurements.seed_demo(DEFAULT_USER)
        seeded = True
        auth.audit("seed_demo", count=measurements.count(DEFAULT_USER))
    tasks.ensure_today(DEFAULT_USER)

    port = pick_port(host, args.port)
    url = f"http://{host}:{port}"
    server = ThreadingHTTPServer((host, port), Handler)
    banner(url, port, seeded, host)

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止服务。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
