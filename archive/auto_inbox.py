#!/usr/bin/env python3
"""自动入馆：监视 inbox 目录或提供本地收集服务，把对局记录自动入馆。

三种用法：

  once   处理一轮 inbox 里已存在的记录后退出
  watch  常驻监视 inbox 目录（Ctrl+C 停止）
  serve  常驻监视 inbox + 起一个本地 HTTP 收集服务（POST /ingest）。
         前端游戏打完时直接 POST 记录，静默入馆，玩家无需手动拖文件。

处理成功的记录移入 <inbox>/deposited/，校验失败的移入 <inbox>/rejected/，
都不会被重复处理。

示例：
  python3 auto_inbox.py serve --museum-root museum --inbox inbox --port 8765
  python3 auto_inbox.py watch --museum-root museum --inbox inbox
  python3 auto_inbox.py once  --museum-root museum --inbox inbox
"""

import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import museum_writer


def _process_path(path: Path, inbox: Path, museum_root: Path) -> str:
    """Deposit one record file; move it to deposited/ or rejected/. Returns status."""
    try:
        museum_writer.deposit(path, museum_root)
        status = "deposited"
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"拒绝 {path.name}：{exc}", file=sys.stderr)
        status = "rejected"
    target_dir = inbox / status
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), target_dir / path.name)
    print(f"已归档 {status}：{path.name} → {target_dir / path.name}")
    return status


def process_once(inbox: Path, museum_root: Path) -> None:
    for path in sorted(inbox.glob("*.json")):
        _process_path(path, inbox, museum_root)


def make_handler(inbox: Path, museum_root: Path):
    class IngestHandler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Methods", "POST, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type"
            )

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "service": "anyaward-ingest"}')

        def do_POST(self) -> None:
            if self.path != "/ingest":
                self.send_response(404)
                self._cors()
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            name = (
                "ingest-"
                + datetime.now().strftime("%Y%m%d-%H%M%S")
                + "-"
                + uuid.uuid4().hex[:6]
                + ".json"
            )
            path = inbox / name
            try:
                json.loads(raw)
                path.write_bytes(raw)
            except json.JSONDecodeError as exc:
                self._reply(400, {"ok": False, "error": f"不是合法 JSON：{exc}"})
                return
            try:
                museum_writer.deposit(path, museum_root)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._reply(400, {"ok": False, "error": str(exc)})
                rejected = inbox / "rejected"
                rejected.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), rejected / name)
                return
            deposited = inbox / "deposited"
            deposited.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), deposited / name)
            self._reply(200, {"ok": True, "message": "已入馆"})

        def _reply(self, code: int, payload: dict) -> None:
            self.send_response(code)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )

        def log_message(self, fmt: str, *args) -> None:  # 静默访问日志
            pass

    return IngestHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="把对局记录自动入馆")
    parser.add_argument("mode", choices=["once", "watch", "serve"], help="运行模式")
    parser.add_argument("--museum-root", default="museum", help="馆藏根目录（默认 ./museum）")
    parser.add_argument("--inbox", default="inbox", help="监视目录（默认 ./inbox）")
    parser.add_argument("--port", type=int, default=8765, help="serve 模式监听端口（默认 8765）")
    args = parser.parse_args()

    inbox = Path(args.inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    museum_root = Path(args.museum_root)

    if args.mode == "once":
        process_once(inbox, museum_root)
    elif args.mode == "watch":
        print(f"监视 {inbox.resolve()} …（Ctrl+C 停止）")
        while True:
            process_once(inbox, museum_root)
            time.sleep(2)
    else:
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port), make_handler(inbox, museum_root)
        )
        print(
            f"收集服务 http://127.0.0.1:{args.port}/ingest 已启动；"
            f"馆藏：{museum_root.resolve()}；Ctrl+C 停止。"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。")
