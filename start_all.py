#!/usr/bin/env python3
"""一键启动《颁什么奖》全部本地服务（跨平台：Windows / macOS / Linux，任意 shell）。

用法：
    python start_all.py                 # 启动全部，Ctrl+C 停止全部
    python start_all.py --dry-run       # 只打印将执行的命令，不真正启动
    python start_all.py --only forum museum   # 只启动指定服务

服务与端口：
    game      8643   游戏（Vue 构建产物）
    collector 8765   收集器（玩家记录静默入馆）
    museum    8767   校史馆 UI
    forum     8768   论坛（需要后端 venv 的 openai/dotenv）

说明：
    - 路径全部相对脚本所在目录解析，无需先 cd，也不依赖具体 shell。
    - game/collector/museum 只用标准库，用当前 Python 即可；forum 自动找后端 venv。
    - 已在运行的端口会自动跳过，可重复执行。
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def venv_python():
    for venv in (ROOT / ".venv", ROOT / "Any-Award-Backend" / ".venv"):
        cand = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if cand.exists():
            return str(cand)
    return None


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def build_services():
    py = sys.executable
    vpy = venv_python()
    return [
        ("game", 8643, "http://localhost:8643/",
         [py, "-m", "http.server", "8643", "--directory", str(ROOT / "any-award-vue" / "dist")]),
        ("collector", 8765, "http://localhost:8765/",
         [py, str(ROOT / "archive" / "auto_inbox.py"), "serve",
          "--museum-root", str(ROOT / "archive" / "museum"),
          "--inbox", str(ROOT / "archive" / "inbox"), "--port", "8765"]),
        ("museum", 8767, "http://localhost:8767/",
         [py, str(ROOT / "archive" / "museum_server.py"),
          "--museum-root", str(ROOT / "archive" / "museum"), "--port", "8767"]),
        ("forum", 8768, "http://localhost:8768/",
         [vpy, str(ROOT / "forum" / "server.py"), "--port", "8768"] if vpy else None),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="一键启动全部本地服务（跨平台）")
    parser.add_argument("--dry-run", action="store_true", help="只打印命令，不启动")
    parser.add_argument("--only", nargs="*", help="只启动指定服务（game/collector/museum/forum）")
    args = parser.parse_args()

    procs = []
    for name, port, url, cmd in build_services():
        if args.only and name not in args.only:
            continue
        if port_busy(port):
            print(f"[跳过] {name:9s} 端口 {port} 已在运行")
            continue
        if cmd is None:
            print(f"[警告] {name:9s} 未找到含 openai 的 venv（.venv 或 Any-Award-Backend/.venv）；"
                  f"请先 python -m venv .venv 并 pip install -r requirements.txt")
            continue
        print(f"[启动] {name:9s} {url}")
        print("       " + " ".join(cmd))
        if not args.dry_run:
            procs.append((name, subprocess.Popen(cmd)))

    if args.dry_run:
        return

    if not procs:
        print("没有需要启动的服务。")
        return

    print("\n全部就绪。按 Ctrl+C 停止所有服务。\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止…")
        for name, p in procs:
            p.terminate()
        for name, p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        print("已停止。")


if __name__ == "__main__":
    main()
