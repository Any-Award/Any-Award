#!/usr/bin/env python3
"""余波回填：把校园论坛的舆情摘录回填进校史馆卷宗的「余波」章节。

打通 论坛 → 校史馆 的回路（设计稿"长循环"的落点）：评选结束后，
学生在论坛上的讨论作为"余波"归档进对应卷宗。

依赖卷宗自包含的 record.json（museum_writer.deposit 已写入）。
重复运行会刷新余波（替换旧的 aftermath 事件），不会重复堆叠。

用法：
  python3 archive/aftermath.py --volume archive/museum/volumes/2026/002-有志少年奖 \
      [--forum-url http://localhost:8768] [--threads 3]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import museum_writer


def fetch_threads(forum_url: str, n: int) -> list[dict]:
    base = forum_url.rstrip("/")
    if base.endswith("/generate"):
        base = base[: -len("/generate")]
    with urllib.request.urlopen(base + "/api/threads", timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    threads = data.get("threads") or []
    # 取全部候选供相关性筛选（奖项相关帖可能不是最近活跃的）
    detailed = []
    for t in threads[:100]:
        with urllib.request.urlopen(base + "/api/threads?id=" + t["id"], timeout=30) as resp:
            detailed.append(json.loads(resp.read().decode("utf-8")))
    return detailed


def relevance(thread: dict, keywords: list[str]) -> int:
    text = (thread.get("title", "") + " " + thread.get("body", ""))
    for c in thread.get("comments") or []:
        text += " " + c.get("body", "")
    return sum(2 if kw in thread.get("title", "") else 1 for kw in keywords if kw and kw in text)


def pick_relevant(threads: list[dict], record: dict, n: int) -> list[dict]:
    keywords = [record.get("meta", {}).get("award_name", "")]
    outcome = record.get("outcome") or {}
    if outcome.get("winner"):
        for c in record.get("candidates") or []:
            if c.get("id") == outcome["winner"] and c.get("name"):
                keywords.append(c["name"])
    scored = sorted(threads, key=lambda t: relevance(t, keywords), reverse=True)
    relevant = [t for t in scored if relevance(t, keywords) > 0]
    return (relevant or scored)[:n]


def build_aftermath_events(threads: list[dict]) -> list[dict]:
    events = [{
        "type": "note",
        "phase": "aftermath",
        "text": "以下为评选结束后校园论坛的部分舆论摘录（学生扮演系统生成，仅代表论坛内学生发言）。",
    }]
    for t in threads:
        author = (t.get("author") or {}).get("nickname", "匿名同学")
        events.append({
            "type": "speech",
            "phase": "aftermath",
            "actor": author,
            "text": f"《{t.get('title', '')}》\n{t.get('body', '')}",
        })
        for c in (t.get("comments") or [])[:2]:
            ca = (c.get("author") or {}).get("nickname", "匿名同学")
            events.append({
                "type": "speech",
                "phase": "aftermath",
                "actor": ca,
                "text": c.get("body", ""),
            })
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="论坛舆情回填卷宗余波")
    parser.add_argument("--volume", required=True, help="卷宗目录（含 record.json）")
    parser.add_argument("--forum-url", default="http://localhost:8768")
    parser.add_argument("--threads", type=int, default=3)
    args = parser.parse_args()

    volume_dir = Path(args.volume)
    record_path = volume_dir / "record.json"
    meta_path = volume_dir / "session_meta.json"
    if not record_path.is_file():
        print(f"错误：{record_path} 不存在（该卷宗需由新版 deposit 生成，含 record.json）", file=sys.stderr)
        sys.exit(1)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}

    threads = pick_relevant(fetch_threads(args.forum_url, args.threads), record, args.threads)
    if not threads:
        print("论坛暂无帖子，未回填。")
        return

    # 刷新余波：移除旧的 aftermath 事件，再追加新的
    record["events"] = [e for e in record.get("events", []) if e.get("phase") != "aftermath"]
    record["events"].extend(build_aftermath_events(threads))

    vol = {"doc_no": meta.get("doc_no", ""), "date": str(meta.get("deposited_at", ""))[:10]}
    volume_md = museum_writer.render_volume(record, vol)
    (volume_dir / "volume.md").write_text(volume_md, encoding="utf-8")
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已回填余波：{volume_dir / 'volume.md'}（{len(threads)} 帖）")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
