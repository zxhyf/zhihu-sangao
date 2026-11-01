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
                    PORT, REPORTS_DIR, SOURCES_FILE, UI_DIR, DOCS_DIR, SAFETY_LINE)
from data import db
from agent import llm, orchestrator
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
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")
            user_id = (qs.get("user") or [DEFAULT_USER])[0]

            if path in ("/", "/index.html"):
                return self._serve_file(UI_DIR / "index.html")
            if path.startswith("/assets/"):
                name = unquote(path[len("/assets/"):])
                return self._serve_file(UI_DIR / name)
            if path == "/favicon.ico":
                return self._send(204, b"")

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
            if path == "/api/health":
                return self._json({
                    "ok": True,
                    "app": APP_NAME,
                    "llm": {"configured": llm.CLIENT.available, "model": LLM_MODEL,
                            "mode": "llm" if llm.CLIENT.available else "local"},
                    "kb": {k: get_kb().status().get(k) for k in ("doc_count", "chunk_count", "built_at")},
                    "tools": len(registry.TOOLS),
                    "db": str(db.db_path()),
                })
            if path == "/api/report":
                days = int((qs.get("days") or ["7"])[0])
                return self._json(reports.weekly(user_id, days))
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
        ctype = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, data, ctype)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query or "")
            user_id = (qs.get("user") or [DEFAULT_USER])[0]

            if path == "/api/chat":
                body = self._json_body()
                message = (body.get("message") or "").strip()
                if not message:
                    return self._json({"ok": False, "error": "消息不能为空"}, 400)
                result = orchestrator.handle(message, user_id=user_id,
                                             use_llm=body.get("use_llm", True))
                return self._json(result)

            if path == "/api/tasks/toggle":
                body = self._json_body()
                return self._json(tasks.toggle(user_id, int(body.get("id") or 0)))

            if path == "/api/meds/log":
                body = self._json_body()
                name = (body.get("name") or "").strip()
                if not name:
                    return self._json({"ok": False, "error": "缺少药名"}, 400)
                return self._json(medications.log_dose(user_id, name, body.get("status") or "taken"))

            if path == "/api/meds/add":
                body = self._json_body()
                return self._json(medications.add_med(
                    user_id, body.get("name") or "", body.get("dose") or "",
                    body.get("frequency") or "每日 1 次", body.get("times") or ["08:00"],
                    body.get("purpose") or ""))

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
                return self._json({"ok": True, "profile": profile_tool.update_profile(user_id, **body)})

            if path == "/api/kb/upload":
                name = (qs.get("name") or ["upload.md"])[0]
                raw = self._body()
                if not raw:
                    return self._json({"ok": False, "error": "文件内容为空"}, 400)
                if name.lower().endswith(".docx"):
                    saved = get_kb().add_docx(name, raw)
                else:
                    text = raw.decode("utf-8", errors="ignore")
                    saved = get_kb().add_document(name, text)
                st = self.kb_status()
                db.execute("INSERT OR REPLACE INTO kb_files (name, size, chunks, added_at, note) VALUES (?,?,?,?,?)",
                           (saved, len(raw), st.get("chunk_count", 0), db.now_iso(), "由界面导入"))
                return self._json({"ok": True, "saved": saved, "kb": st})

            if path == "/api/kb/reindex":
                get_kb().build()
                return self._json({"ok": True, "kb": self.kb_status()})

            if path == "/api/kb/delete":
                body = self._json_body()
                ok = get_kb().remove_document(body.get("doc_id") or "")
                return self._json({"ok": ok, "kb": self.kb_status()})

            if path == "/api/kb/search":
                body = self._json_body()
                q = (body.get("q") or "").strip()
                return self._json({"ok": True, "results": get_kb().search(q, k=6)})

            if path == "/api/demo/seed":
                n = measurements.seed_demo(user_id)
                msg = f"已写入 {n} 条演示记录" if n else "演示数据已存在，未重复写入"
                return self._json({"ok": True, "inserted": n, "message": msg})

            if path == "/api/demo/clear":
                measurements.clear(user_id)
                return self._json({"ok": True})

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
        }


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


def banner(url: str, port: int, seeded: bool) -> None:
    line = "─" * 58
    print(f"\n  {APP_NAME} · {APP_SUBTITLE}")
    print(f"  {line}")
    print(f"  ▸ 访问地址   {url}")
    print(f"  ▸ 大模型     {'已连接 DeepSeek（' + LLM_MODEL + '）' if llm.CLIENT.available else '未配置，使用本地规则引擎'}")
    print(f"  ▸ 知识库     {get_kb().status().get('doc_count', 0)} 篇文档 / "
          f"{get_kb().status().get('chunk_count', 0)} 个片段（{DOCS_DIR}）")
    print(f"  ▸ 数据库     {db.db_path()}")
    print(f"  ▸ 演示数据   {'已写入' if seeded else '沿用已有数据'}")
    print(f"  {line}")
    print("  按 Ctrl+C 停止服务\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="智护三高 · 三高共病 AI 健康管理智能体")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-seed", action="store_true", help="不写入演示数据")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    db.init_db()
    profile_tool.ensure_profile(DEFAULT_USER)
    get_kb().build()

    seeded = False
    if not args.no_seed and measurements.count(DEFAULT_USER) == 0:
        measurements.seed_demo(DEFAULT_USER)
        seeded = True
    tasks.ensure_today(DEFAULT_USER)

    port = pick_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    server = ThreadingHTTPServer((args.host, port), Handler)
    banner(url, port, seeded)

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
