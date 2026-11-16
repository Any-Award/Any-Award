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
    base = {"thread": 5, "received": 3}.get(item.get("kind"), 2)
    body = str(item.get("body", ""))
    score = base + min(3, len(body) // 60)     # 长正文 +≤3
    if item.get("reply_to_nick") or item.get("from"):
        score += 1                             # 有互动对象
    if any(w in body for w in _IMPORTANT_WORDS):
        score += 2                             # 命中情感/重大词
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
    """把一条评论写进作者与互动对象的记忆（玩家评论不入库）。

    第三轮新增：被回复者（或楼主）也记一条 kind=received 的见闻记忆——
    修复「A 怼了 B，只有 A 记得」的单向失忆（基线实测 122 对互动 59% 单向，
    人际冲突在认知层从未真正发生）。"""
    a = comment.get("author") or {}
    if a.get("kind") != "ai":
        return
    target, target_nick = None, None
    for c in thread.get("comments") or []:
        if c.get("id") == comment.get("reply_to"):
            target = c
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
    # 见闻记忆：回复对象优先，回复楼主则记楼主
    if target is None:
        op = thread.get("author") or {}
        target = {"author": op, "body": thread.get("body", "")} if op.get("kind") == "ai" else None
        target_nick = op.get("nickname") if target else None
    ta = (target or {}).get("author") or {}
    if target and ta.get("kind") == "ai" and target_nick and target_nick != a.get("nickname"):
        append(target_nick, {
            "at": comment.get("created_at", ""),
            "kind": "received",
            "thread_id": thread.get("id", ""),
            "thread_title": thread.get("title", ""),
            "body": comment.get("body", ""),
            "reply_to_nick": None,
            "from": a.get("nickname", ""),
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


def _scored(items: list[dict]) -> list[tuple[float, int, dict]]:
    """Stanford 两信号打分（recency+importance），互动条目加固定奖励，按分降序。

    互动 = 我回复过谁（reply_to_nick）/ 谁对我说过话（kind=received, from）。
    基线实测纯分数排序下 45 条注入 43 条是自己的帖——互动记忆被系统性埋没，
    「延续上次吵架」在结构上不可能，故对互动条目加 0.8 分奖励。"""
    n = len(items)
    recency = [0.99 ** (n - 1 - i) for i in range(n)]
    importance = [float(it.get("importance", 3)) / 10 for it in items]

    def norm(xs):
        lo, hi = min(xs), max(xs)
        return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in xs]

    rn, inn = norm(recency), norm(importance)
    out = []
    for i, it in enumerate(items):
        bonus = 0.8 if (it.get("reply_to_nick") or it.get("from")) else 0.0
        out.append((0.5 * rn[i] + 3 * inn[i] + bonus, i, it))
    out.sort(key=lambda x: -x[0])
    return out


def _is_interaction(item: dict) -> bool:
    return bool(item.get("reply_to_nick") or item.get("from") or item.get("kind") == "received")


def has_interaction(nick: str, other: str) -> bool:
    """nick 的记忆里是否有与 other 的互动（我回过 TA / TA 对我说过）。"""
    if not other or other == nick:
        return False
    return any(it.get("reply_to_nick") == other or it.get("from") == other
               for it in recent(nick, KEEP))


def retrieve(nick: str, k: int = 5, query: str | None = None) -> list[dict]:
    """加权检索（Stanford retrieve 的 recency + importance 两信号 + 互动奖励）。

    score = 0.5*norm(recency) + 3*norm(importance) + 0.8×互动。
    第三信号 relevance（embedding）留待 P1；query 参数预留，当前忽略。
    旧条目无 importance 字段时默认 3，无需迁移。"""
    items = recent(nick, KEEP)
    if not items:
        return []
    top = [it for _, _, it in _scored(items)[:k]]
    top.sort(key=lambda it: it.get("at", ""))   # 按时间序返回，便于阅读
    return top


def footprints(nicknames: list[str], k: int = 3, width: int = 60) -> str:
    """生成"各人近期足迹"提示块。混合配额：1 条自己的高热帖，其余名额留给
    互动记忆（谁怼过我/我回了谁）——关系延续的地基；不足时按分数补齐。"""
    blocks = []
    for nick in nicknames:
        items = recent(nick, KEEP)
        if not items:
            continue
        scored = _scored(items)
        chosen: list[dict] = []
        threads = [it for _, _, it in scored if it.get("kind") == "thread"]
        if threads:
            chosen.append(threads[0])
        for _, _, it in scored:
            if len(chosen) >= k:
                break
            if _is_interaction(it) and it not in chosen:
                chosen.append(it)
        for _, _, it in scored:
            if len(chosen) >= k:
                break
            if it not in chosen:
                chosen.append(it)
        lines = []
        for it in chosen:
            body = " ".join(str(it.get("body", "")).split())[:width]
            title = it.get("thread_title", "")
            if it.get("kind") == "thread":
                lines.append(f"  · 发帖《{title}》：{body}")
            elif it.get("kind") == "received":
                lines.append(f"  · 在《{title}》下，{it.get('from', '?')} 对我说：{body}")
            elif it.get("reply_to_nick"):
                lines.append(f"  · 在《{title}》下我回复 {it['reply_to_nick']}：{body}")
            else:
                lines.append(f"  · 在《{title}》下评论：{body}")
        blocks.append(f"【{nick} 的近期足迹】\n" + "\n".join(lines))
    return "\n".join(blocks)


def hot_topics(k: int = 4) -> str:
    """热帖按评论数排序（Step4 前是"最新4帖"——热≠新）。"""
    if not STATE_PATH.is_file():
        return ""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    threads = (state.get("threads") or [])[-10:]
    ranked = sorted(threads, key=lambda t: len(t.get("comments") or []), reverse=True)[:k]
    titles = [f"《{t.get('title', '')}》({len(t.get('comments') or [])}评)"
              for t in ranked if t.get("title")]
    if not titles:
        return ""
    return "论坛现在的热帖（按评论数）：" + "、".join(titles)


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
