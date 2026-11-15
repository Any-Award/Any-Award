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
STATES_PATH = HERE / "data" / "states.json"
KEEP = 50

# 重要性启发式（对齐 Stanford poignancy：1=刷牙日常，10=分手/录取）
_IMPORTANT_WORDS = (
    "落选", "上岸", "获奖", "分手", "公示", "录取", "淘汰", "逆袭",
    "诺奖", "奖学金", "保研", "考研", "挂科", "退学", "崩溃", "抑郁",
)


def _importance(item: dict) -> int:
    score = 5 if item.get("kind") == "thread" else 2
    body = str(item.get("body", ""))
    score += min(3, len(body) // 60)        # 长正文 +≤3
    if item.get("reply_to_nick"):
        score += 1                          # 有互动对象
    if any(w in body for w in _IMPORTANT_WORDS):
        score += 2                          # 命中情感/重大词
    return min(10, score)


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
    item = dict(item)
    item.setdefault("importance", _importance(item))
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


def retrieve(nick: str, k: int = 5, query: str | None = None) -> list[dict]:
    """加权检索（Stanford retrieve 的 recency + importance 两信号）。

    score = 0.5*norm(0.99^距最新条数) + 3*norm(importance/10)，取 top-k 按时间序返回。
    第三信号 relevance（embedding）留待 P1；query 参数预留，当前忽略。
    旧条目无 importance 字段时默认 3，无需迁移。
    """
    items = recent(nick, KEEP)
    if not items:
        return []
    n = len(items)
    recency = [0.99 ** (n - 1 - i) for i in range(n)]
    importance = [float(it.get("importance", 3)) / 10 for it in items]

    def norm(xs):
        lo, hi = min(xs), max(xs)
        return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in xs]

    rn, inn = norm(recency), norm(importance)
    scores = [0.5 * rn[i] + 3 * inn[i] for i in range(n)]
    top = sorted(range(n), key=lambda i: scores[i], reverse=True)[:k]
    top.sort()  # 按时间序返回，便于阅读
    return [items[i] for i in top]


def footprints(nicknames: list[str], k: int = 3, width: int = 60) -> str:
    """生成"各人近期足迹"提示块；没有记忆的人返回空串占位说明。"""
    blocks = []
    for nick in nicknames:
        items = retrieve(nick, k)
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


# ---------------------------------------------------------------------------
# 动态状态（斯坦福 revise_identity 的轻量版）：每生一份 currently + 洞察
# ---------------------------------------------------------------------------

def load_states() -> dict:
    if not STATES_PATH.is_file():
        return {}
    try:
        return json.loads(STATES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_states(states: dict) -> None:
    STATES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(states, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATES_PATH)


def get_state(nickname: str) -> dict | None:
    return load_states().get(nickname)
