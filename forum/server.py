#!/usr/bin/env python3
"""校园论坛独立服务（真论坛：玩家可发帖回帖，AI 学生自动互动）。

  GET  /                          论坛 UI（单文件 BBS 页面）
  GET  /api/threads               帖子列表（含公告）
  GET  /api/threads?id=<id>       帖子详情（含楼层评论）
  POST /api/threads               玩家发帖 {title, body, nickname}
                                  → 入库 + AI 学生评论，返回完整帖子
  POST /api/threads/<id>/comments 玩家回帖 {body, nickname}
                                  → 入库 + AI 学生追评，返回完整帖子
  POST /generate                  按简报生成一批 AI 帖子并入坛；
                                  空 body 复用 output/last_pack.json

状态持久化在 forum/data/forum.json（每次写入落盘）。
首次启动若状态为空，自动载入 output/ 里最新的 AI 快照作为种子内容。

用法（用后端 venv 运行以取得 openai/dotenv）：
  Any-Award-Backend/.venv/bin/python forum/server.py [--port 8768]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from generate import generate_snapshot, generate_comments, generate_replies_to_comment, generate_daily, save_snapshot, load_personas, load_llm_env, ensure_fresh_states
import memory
from openai import OpenAI
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
DATA_DIR = HERE / "data"
STATE_PATH = DATA_DIR / "forum.json"

LOCK = threading.Lock()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def make_thread(title: str, body: str, nickname: str, kind: str, tag: str = "") -> dict:
    return {
        "id": new_id("t"),
        "title": title.strip(),
        "body": body.strip(),
        "author": {"kind": kind, "nickname": nickname.strip() or "匿名同学", "tag": tag},
        "created_at": now(),
        "comments": [],
    }


def make_comment(body: str, nickname: str, kind: str, tag: str = "", reply_to: str | None = None) -> dict:
    return {
        "id": new_id("c"),
        "body": body.strip(),
        "author": {"kind": kind, "nickname": nickname.strip() or "匿名同学", "tag": tag},
        "created_at": now(),
        "reply_to": reply_to,
    }


def append_ai_comments(thread: dict, comments, tags: dict, default_reply: str | None = None) -> list:
    """把模型生成的评论入帖，并把 reply_to 昵称解析成真实楼层 id（AI 互相盖楼）。

    返回新增的评论列表。所有入帖路径（玩家互动 / 批量生成 / 种子）共用，保证一致。
    """
    nick_to_id = {c["author"]["nickname"]: c["id"] for c in thread["comments"]}
    added = []
    for c in comments or []:
        nickname = c.get("nickname")
        if nickname not in tags:
            continue
        rt = str(c.get("reply_to") or "").strip()
        reply_id = default_reply if rt in ("", "楼主") else nick_to_id.get(rt, default_reply)
        new = make_comment(c.get("body", ""), nickname, "ai", tags[nickname], reply_to=reply_id)
        thread["comments"].append(new)
        nick_to_id[nickname] = new["id"]
        added.append(new)
    return added


# ---------------------------------------------------------------------------
# 状态读写
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    state = {"schema_version": 1, "announcement": None, "threads": []}
    seed_from_latest_snapshot(state)
    return state


def seed_from_latest_snapshot(state: dict) -> None:
    files = sorted(OUT_DIR.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    files = [f for f in files if f.name != "last_pack.json"]
    if not files:
        return
    snapshot = json.loads(files[0].read_text(encoding="utf-8"))
    state["announcement"] = snapshot.get("announcement")
    tags = {p["nickname"]: p["tag"] for p in load_personas()["personas"]}
    for t in snapshot.get("threads") or []:
        thread = make_thread(t.get("title", ""), t.get("body", ""), t.get("nickname", ""), "ai", tags.get(t.get("nickname"), ""))
        thread["created_at"] = snapshot["meta"].get("generated_at", now())
        append_ai_comments(thread, t.get("comments"), tags)
        state["threads"].append(thread)
        memory.record_thread(thread)


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def find_thread(state: dict, thread_id: str) -> dict | None:
    for t in state["threads"]:
        if t["id"] == thread_id:
            return t
    return None


# ---------------------------------------------------------------------------
# AI 互动：给玩家帖子/评论生成学生回应
# ---------------------------------------------------------------------------

def ai_react(thread: dict, target_comment: dict | None = None) -> None:
    """为帖子生成 AI 学生回应并追加（LLM 调用，可能耗时几十秒）。

    target_comment 为 None：学生围绕主帖发言（新帖场景）；
    否则：学生针对玩家那条具体评论回应（楼中楼对话场景）。
    """
    env = load_llm_env()
    client = OpenAI(api_key=env["LLM_API_KEY"], base_url=env["LLM_API_BASE"])
    personas_data = load_personas()
    personas, rules = personas_data["personas"], personas_data["rules"]
    pseudo = {
        "nickname": thread["author"]["nickname"],
        "title": thread["title"],
        "body": thread["body"],
    }
    known = {p["nickname"]: p["tag"] for p in personas}
    if target_comment is not None:
        result = generate_replies_to_comment(
            client, env["LLM_MODEL_NAME"], personas, rules, pseudo, target_comment, thread["comments"], temperature=1.2
        )
        default_reply = target_comment["id"]
    else:
        result = generate_comments(client, env["LLM_MODEL_NAME"], personas, rules, pseudo, temperature=1.2)
        default_reply = None
    added = append_ai_comments(thread, result.get("comments"), known, default_reply)
    for c in added:  # 只记录本轮新增，避免重复入库
        memory.record_comment(thread, c)


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------

def public_thread(t: dict) -> dict:
    return {
        "id": t["id"],
        "title": t["title"],
        "author": t["author"],
        "created_at": t["created_at"],
        "comment_count": len(t["comments"]),
        "last_activity": t["comments"][-1]["created_at"] if t["comments"] else t["created_at"],
    }


def make_handler() -> type:
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, payload) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write((HERE / "ui" / "index.html").read_bytes())
            elif parsed.path == "/api/threads":
                with LOCK:
                    state = load_state()
                    tid = (parse_qs(parsed.query).get("id") or [""])[0]
                    if tid:
                        t = find_thread(state, tid)
                        if not t:
                            self._json(404, {"error": "帖子不存在"})
                        else:
                            self._json(200, t)
                    else:
                        payload = {
                            "announcement": state.get("announcement"),
                            "threads": [public_thread(t) for t in reversed(state["threads"])],
                        }
                        self._json(200, payload)
            else:
                self._json(404, {"error": "not found"})

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).strip()
            return json.loads(raw) if raw else {}

        def do_POST(self) -> None:
            from urllib.parse import urlparse
            path = urlparse(self.path).path
            if path == "/generate":
                self._handle_generate()
            elif path == "/daily":
                self._handle_daily()
            elif path == "/refresh":
                self._handle_refresh()
            elif path == "/api/threads":
                self._handle_new_thread()
            elif path.startswith("/api/threads/") and path.endswith("/comments"):
                tid = path[len("/api/threads/"):-len("/comments")].strip("/")
                self._handle_comment(tid)
            else:
                self._json(404, {"error": "not found"})

        def _handle_generate(self) -> None:
            try:
                data = self._read_json()
                if data:
                    pack = data
                else:
                    pack = json.loads((OUT_DIR / "last_pack.json").read_text(encoding="utf-8"))
                snapshot = generate_snapshot(pack)
                save_snapshot(snapshot, pack, OUT_DIR)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
                return
            tags = {p["nickname"]: p["tag"] for p in load_personas()["personas"]}
            with LOCK:
                state = load_state()
                state["announcement"] = snapshot.get("announcement") or state.get("announcement")
                for t in snapshot.get("threads") or []:
                    thread = make_thread(t.get("title", ""), t.get("body", ""), t.get("nickname", ""), "ai", tags.get(t.get("nickname"), ""))
                    append_ai_comments(thread, t.get("comments"), tags)
                    state["threads"].append(thread)
                    memory.record_thread(thread)
                save_state(state)
                self._json(200, {"ok": True, "threads": [public_thread(t) for t in reversed(state["threads"])]})

        def _handle_refresh(self) -> None:
            try:
                env = load_llm_env()
                client = OpenAI(api_key=env["LLM_API_KEY"], base_url=env["LLM_API_BASE"])
                personas = load_personas()["personas"]
                ensure_fresh_states(client, env["LLM_MODEL_NAME"], personas)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"ok": True, "states": memory.load_states()})

        def _handle_daily(self) -> None:
            try:
                env = load_llm_env()
                client = OpenAI(api_key=env["LLM_API_KEY"], base_url=env["LLM_API_BASE"])
                personas_data = load_personas()
                result = generate_daily(
                    client, env["LLM_MODEL_NAME"], personas_data["personas"], personas_data["rules"], temperature=1.2
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
                return
            tags = {p["nickname"]: p["tag"] for p in personas_data["personas"]}
            with LOCK:
                state = load_state()
                for t in result.get("threads") or []:
                    thread = make_thread(t.get("title", ""), t.get("body", ""), t.get("nickname", ""), "ai", tags.get(t.get("nickname"), ""))
                    state["threads"].append(thread)
                    memory.record_thread(thread)
                save_state(state)
                self._json(200, {"ok": True, "threads": [public_thread(t) for t in reversed(state["threads"])]})

        def _handle_new_thread(self) -> None:
            try:
                data = self._read_json()
            except json.JSONDecodeError as exc:
                self._json(400, {"error": str(exc)})
                return
            title = str(data.get("title") or "").strip()
            body = str(data.get("body") or "").strip()
            nickname = str(data.get("nickname") or "").strip()[:16] or "匿名同学"
            if not title or not body:
                self._json(400, {"error": "标题和正文都不能为空"})
                return
            thread = make_thread(title, body, nickname, "player", "玩家")
            try:
                ai_react(thread)
            except Exception as exc:  # noqa: BLE001 - AI 互动失败不阻塞玩家发帖
                print(f"AI 追评失败：{exc}", file=sys.stderr)
            with LOCK:
                state = load_state()
                state["threads"].append(thread)
                save_state(state)
            self._json(200, thread)

        def _handle_comment(self, tid: str) -> None:
            try:
                data = self._read_json()
            except json.JSONDecodeError as exc:
                self._json(400, {"error": str(exc)})
                return
            body = str(data.get("body") or "").strip()
            nickname = str(data.get("nickname") or "").strip()[:16] or "匿名同学"
            reply_to = str(data.get("reply_to") or "").strip() or None
            if not body:
                self._json(400, {"error": "评论不能为空"})
                return
            with LOCK:
                state = load_state()
                thread = find_thread(state, tid)
                if not thread:
                    self._json(404, {"error": "帖子不存在"})
                    return
                if reply_to and not any(c["id"] == reply_to for c in thread["comments"]):
                    self._json(400, {"error": "回复目标不存在"})
                    return
                player_comment = make_comment(body, nickname, "player", "玩家", reply_to=reply_to)
                thread["comments"].append(player_comment)
                save_state(state)
            try:
                ai_react(thread, target_comment=player_comment)
                with LOCK:
                    state = load_state()
                    current = find_thread(state, tid)
                    if current:
                        current["comments"] = thread["comments"]
                        save_state(state)
            except Exception as exc:  # noqa: BLE001
                print(f"AI 追评失败：{exc}", file=sys.stderr)
            with LOCK:
                state = load_state()
                self._json(200, find_thread(state, tid))

        def log_message(self, fmt: str, *args) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="校园论坛独立服务")
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler())
    print(f"论坛 UI: http://localhost:{args.port}/　玩家可发帖回帖，AI 学生自动互动")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    sys.exit(main())
