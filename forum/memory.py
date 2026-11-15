"""AI 学生的记忆层：每人一份持久化记忆，生成时注入"近期足迹"。

存储：forum/data/memory/<nickname>.json
  [{at, kind, thread_id, thread_title, body, reply_to_nick}, ...]  保留最近 50 条

两类注入：
  footprints(nicknames)：这些学生最近在论坛说过什么（自我一致性、延续梗）
  hot_topics()：论坛最近的热帖标题（环境感知）
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MEMORY_DIR = HERE / "data" / "memory"
STATE_PATH = HERE / "data" / "forum.json"
KEEP = 50


def _path(nickname: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in nickname)
    return MEMORY_DIR / f"{safe}.json"


def recent(nickname: str, k: int = 5) -> list[dict]:
    path = _path(nickname)
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return items[-k:]


def append(nickname: str, item: dict) -> None:
    if not nickname:
        return
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    items = recent(nickname, KEEP)
    items.append(item)
    _path(nickname).write_text(json.dumps(items[-KEEP:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_comment(thread: dict, comment: dict) -> None:
    """把一条评论写进其 AI 作者的记忆（玩家评论不入库）。"""
    a = comment.get("author") or {}
    if a.get("kind") != "ai":
        return
    target_nick = None
    for c in thread.get("comments") or []:
        if c.get("id") == comment.get("reply_to"):
            target_nick = (c.get("author") or {}).get("nickname")
            break
    append(a.get("nickname", ""), {
        "at": comment.get("created_at", ""),
        "kind": "comment",
        "thread_id": thread.get("id", ""),
        "thread_title": thread.get("title", ""),
        "body": comment.get("body", ""),
        "reply_to_nick": target_nick,
    })


def record_thread(thread: dict) -> None:
    """把一整帖（含评论）写进各位作者的记忆。仅用于全新帖子，避免重复记录。"""
    author = thread.get("author") or {}
    if author.get("kind") == "ai":
        append(author.get("nickname", ""), {
            "at": thread.get("created_at", ""),
            "kind": "thread",
            "thread_id": thread.get("id", ""),
            "thread_title": thread.get("title", ""),
            "body": thread.get("body", ""),
            "reply_to_nick": None,
        })
    for c in thread.get("comments") or []:
        record_comment(thread, c)


def footprints(nicknames: list[str], k: int = 3, width: int = 60) -> str:
    """生成"各人近期足迹"提示块；没有记忆的人返回空串占位说明。"""
    blocks = []
    for nick in nicknames:
        items = recent(nick, k)
        if not items:
            continue
        lines = []
        for it in items:
            body = " ".join(str(it.get("body", "")).split())[:width]
            if it.get("kind") == "thread":
                lines.append(f"  · 发帖《{it.get('thread_title', '')}》：{body}")
            else:
                target = f"（回复 {it['reply_to_nick']}）" if it.get("reply_to_nick") else ""
                lines.append(f"  · 在《{it.get('thread_title', '')}》下评论{target}：{body}")
        blocks.append(f"【{nick} 的近期足迹】\n" + "\n".join(lines))
    return "\n".join(blocks)


def hot_topics(k: int = 4) -> str:
    if not STATE_PATH.is_file():
        return ""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    titles = [t.get("title", "") for t in (state.get("threads") or [])[-k:]]
    if not titles:
        return ""
    return "论坛最近的热帖：" + "、".join(f"《{t}》" for t in reversed(titles))
