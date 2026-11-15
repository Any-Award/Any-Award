#!/usr/bin/env python3
"""论坛自动多卷驱动：扫描校史馆卷宗，每个奖项喂给论坛生成讨论主题。

保持论坛解耦：本脚本是编排器，用 forum/adapters/museum_volume 把卷宗转成简报，
POST 给论坛 /generate。论坛本身不依赖校史馆。

- 按奖项去重（同一奖取最新一卷），避免重复话题。
- 记录已同步卷宗（archive/data/synced_volumes.json），默认只喂新增；--all 重喂全部。
- 可选 --news N 追加新闻、--daily 追加日常帖。

运行：python3 archive/forum_sync.py [--museum-root archive/museum] [--forum-url http://localhost:8768] [--news 2] [--daily] [--all]
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE / "forum"))
from adapters.museum_volume import pack_from_volume

SYNCED = HERE / "data" / "synced_volumes.json"


def load_synced() -> set:
    if SYNCED.is_file():
        try:
            return set(json.loads(SYNCED.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return set()


def save_synced(s: set) -> None:
    SYNCED.parent.mkdir(parents=True, exist_ok=True)
    SYNCED.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def post_pack(pack: dict, forum_url: str) -> bool:
    req = urllib.request.Request(
        forum_url.rstrip("/") + "/generate",
        data=json.dumps(pack, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status == 200
    except Exception as exc:  # noqa: BLE001
        print(f"  推送失败：{exc}", file=sys.stderr)
        return False


def latest_per_award(museum_root: Path) -> list:
    by_award = {}
    for meta_path in museum_root.glob("volumes/*/*/session_meta.json"):
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        award = m.get("award_name")
        vol_md = meta_path.parent / "volume.md"
        if not award or not vol_md.is_file():
            continue
        key = m.get("doc_no", "")
        if award not in by_award or key > by_award[award][0]:
            by_award[award] = (key, vol_md, meta_path.parent)
    return [(award, v[1], v[2]) for award, v in sorted(by_award.items())]


def forum_mentions(forum_url: str, award: str) -> bool:
    """论坛当前数据里是否还有该奖项的讨论（公告/帖/评正文含奖项名）。

    论坛状态可能被重置（forum.json 回滚），而 synced 标记还在——这会让卷宗
    永远不会被重喂。--status/--repair 用本函数核对标记与现实的漂移。"""
    data = None
    try:
        with urllib.request.urlopen(forum_url.rstrip("/") + "/api/threads", timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  拉取论坛数据失败：{exc}", file=sys.stderr)
        return False
    blob = []
    ann = (data or {}).get("announcement") or {}
    blob += [ann.get("title", ""), ann.get("body", "")]
    for t in (data or {}).get("threads") or []:
        blob += [t.get("title", ""), t.get("body", "")]
        for c in t.get("comments") or []:
            blob.append(c.get("body", ""))
    return award in "\n".join(blob)


def main() -> None:
    ap = argparse.ArgumentParser(description="论坛自动多卷驱动")
    ap.add_argument("--museum-root", default=str(HERE / "museum"))
    ap.add_argument("--forum-url", default="http://localhost:8768")
    ap.add_argument("--news", type=int, default=0, help="追加 N 条新闻")
    ap.add_argument("--daily", action="store_true", help="追加日常帖")
    ap.add_argument("--all", action="store_true", help="重喂全部（忽略已同步记录）")
    ap.add_argument("--status", action="store_true", help="只核对：标记已同步的奖项在论坛里是否真有讨论")
    ap.add_argument("--repair", action="store_true", help="清除漂移标记（标记已同步但论坛已无讨论）并重喂")
    args = ap.parse_args()

    synced = load_synced()
    if args.status or args.repair:
        print(f"{'奖项':<14} {'论坛有讨论':<8} 标记  卷宗")
        for award, vol_md, vol_dir in latest_per_award(Path(args.museum_root)):
            key = str(vol_dir.relative_to(Path(args.museum_root)))
            live = forum_mentions(args.forum_url, award)
            marked = key in synced
            print(f"{award:<14} {'✓' if live else '✗':^6}    {'是' if marked else '否':^4}  {vol_dir.name}")
            if args.repair and marked and not live:
                synced.discard(key)
                print(f"  ↳ 清除漂移标记，本次重喂")
        if args.repair:
            save_synced(synced)
        if not args.repair:
            return
    fed = 0
    for award, vol_md, vol_dir in latest_per_award(Path(args.museum_root)):
        key = str(vol_dir.relative_to(Path(args.museum_root)))
        if key in synced and not args.all:
            print(f"跳过已同步：{award}")
            continue
        print(f"喂论坛：{award}")
        if post_pack(pack_from_volume(vol_md), args.forum_url):
            synced.add(key)
            fed += 1
    save_synced(synced)
    print(f"本次喂 {fed} 个奖项话题")

    if args.news:
        subprocess.run([str(WORKSPACE / "Any-Award-Backend/.venv/bin/python"),
                        str(WORKSPACE / "news/generate.py"), "--count", str(args.news), "--post-to-forum"],
                       check=False)
    if args.daily:
        try:
            req = urllib.request.Request(args.forum_url.rstrip("/") + "/daily", data=b"", method="POST")
            urllib.request.urlopen(req, timeout=300)
            print("已追加日常帖")
        except Exception as exc:  # noqa: BLE001
            print(f"日常帖失败：{exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
