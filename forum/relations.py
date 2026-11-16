"""AI 学生人际关系表（第三轮 Step2）。

数据: forum/data/relationships.json —— 无向带权边列表:
  [{"a", "b"(字典序对), "kind": 关系性质短语, "strength": 0-100,
    "last_note": 最近一次互动的印象, "neg": {"date", "n"}(当日连续负面计数),
    "updated": ISO}]

六阶段（参照 MaiBot 好感度插件的阶段注入思路,阈值本土化）:
  0-15 生疏 / 16-35 面熟 / 36-55 熟络 / 56-75 老熟人 / 76-90 死党 / 91-100 过命交情

更新规则（同插件,防"数值机械感"的关键是阻尼）:
  - LLM 评价产出 delta(-3..+3)（评价函数在 generate.py,本模块只管规则与存储）
  - strength>40 的负面 ×0.5（老交情经得起小摩擦）
  - 同一天第 2 次起连续负面再 ×0.5（防断崖）
  - clamp 0..100; 正向互动重置负面连击

用途遵循 AgentSociety 的结论: 关系数值只用于三处 prompt 注入——选谁、怎么说话、回不回。
本模块不 import generate（避免循环）; LLM 评价由 generate 调用本模块的规则函数。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REL_PATH = HERE / "data" / "relationships.json"
PERSONAS_PATH = HERE / "personas.json"

STAGES = [
    (15, "生疏", "基本不认识, 别装熟"),
    (35, "面熟", "知道有这么个人, 点头之交"),
    (55, "熟络", "经常在同一些帖里碰到, 说话不用客气"),
    (75, "老熟人", "互相知道脾性, 可以直接抬杠也可以直接开口求帮忙"),
    (90, "死党", "互怼是日常, 但对方被欺负会出头"),
    (100, "过命交情", "对方的事就是自己的事"),
]

# relations 自由文本 → 初始强度的关键词表（一次性迁移用）
_SEED_RULES = [
    (("互怼", "互推", "阴阳怪气但关系其实不错", "互相看不上又互相捧场"), 48, "互怼之交"),
    (("饭搭子",), 58, "饭搭子"),
    (("算账同盟",), 52, "算账同盟"),
    (("互相道晚安", "凌晨背书搭子"), 47, "深夜搭子"),
    (("感性同盟",), 44, "感性同盟"),
    (("照顾", "兜底", "帮过"), 45, "照顾"),
    (("黑粉", "拆台"), 20, "损友"),
    (("气质相近",), 40, "气质相近"),
]


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _empty_edge(a: str, b: str, strength: int = 25, kind: str = "同学") -> dict:
    lo, hi = _pair(a, b)
    return {"a": lo, "b": hi, "kind": kind, "strength": int(strength),
            "last_note": "", "neg": {}, "updated": datetime.now().isoformat(timespec="seconds")}


def load() -> list[dict]:
    if REL_PATH.is_file():
        try:
            return json.loads(REL_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return []


def save(edges: list[dict]) -> None:
    REL_PATH.parent.mkdir(parents=True, exist_ok=True)
    edges = sorted(edges, key=lambda e: (e["a"], e["b"]))
    tmp = REL_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(edges, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(REL_PATH)


def get(a: str, b: str) -> dict | None:
    lo, hi = _pair(a, b)
    for e in load():
        if e["a"] == lo and e["b"] == hi:
            return e
    return None


def ensure(a: str, b: str, strength: int = 25, kind: str = "同学") -> dict:
    """取边,不存在则建(涌现型关系的入口: 任何互动都可让陌生人变成熟人)。"""
    e = get(a, b)
    if e is None:
        e = _empty_edge(a, b, strength, kind)
        edges = load()
        edges.append(e)
        save(edges)
    return e


def stage_of(strength: float) -> tuple[str, str]:
    for cap, name, hint in STAGES:
        if strength <= cap:
            return name, hint
    return STAGES[-1][1], STAGES[-1][2]


def update(a: str, b: str, delta: int, note: str = "") -> dict:
    """按阻尼规则更新一条边,返回更新后的边。delta 由 LLM 评价给出(-3..+3)。"""
    delta = max(-3, min(3, int(delta)))
    e = ensure(a, b)
    today = datetime.now().strftime("%Y-%m-%d")
    if delta < 0:
        if e["strength"] > 40:
            delta = int(delta * 0.5) or (-1 if delta < 0 else 0)   # 老交情减半
        neg = e.get("neg") or {}
        n = neg.get("n", 0) + 1 if neg.get("date") == today else 1
        e["neg"] = {"date": today, "n": n}
        if n >= 2:                                                  # 防断崖
            delta = int(delta * 0.5) or (-1 if delta < 0 else 0)
    else:
        e["neg"] = {}
    e["strength"] = max(0, min(100, e["strength"] + delta))
    if note:
        e["last_note"] = note[:60]
    e["updated"] = datetime.now().isoformat(timespec="seconds")
    edges = load()
    lo, hi = _pair(a, b)
    edges = [e if (x["a"] == lo and x["b"] == hi) else x for x in edges]
    save(edges)
    return e


def hint_line(nick: str, other: str) -> str:
    """注入 prompt 的单行关系提示;无边或对方是自己时返回空串。"""
    if not other or other == nick:
        return ""
    e = get(nick, other)
    if e is None:
        return f"（你和{other}不熟, 就是普通同学）"
    name, hint = stage_of(e["strength"])
    kind = e.get("kind") or "同学"
    note = f",最近: {e['last_note']}" if e.get("last_note") else ""
    return f"（你和{other}: {kind}, 关系{name}——{hint}{note}）"


def weight(nick: str, other: str) -> float:
    """楼中楼目标选择的关系权重(Step3 用): 熟人更容易互怼互捧。"""
    e = get(nick, other)
    if e is None:
        return 1.0
    return 1.0 + e["strength"] / 50.0


def seed_from_personas() -> int:
    """从 personas.json 的 relations 文本一次性迁移初始关系边(幂等: 已有文件则跳过)。"""
    if REL_PATH.is_file():
        return 0
    data = json.loads(PERSONAS_PATH.read_text(encoding="utf-8"))
    people = {p["nickname"]: p for p in data["personas"]}
    nicks = list(people)
    pairs: dict[tuple[str, str], tuple[int, str]] = {}
    for nick, p in people.items():
        # 关键词只在"提到对方的那一句"里找——整段匹配会把别的 pair 的关键词
        # 错算到当前 pair(基线实测:梗先知的『互怼』对象是大壮,却命中了干饭王)
        segments = re.split(r"[；。]", str(p.get("relations", "")))
        for other in nicks:
            if other == nick:
                continue
            seg_hits = [s for s in segments if other in s]
            if not seg_hits:
                continue
            lo, hi = _pair(nick, other)
            best = pairs.get((lo, hi), (25, "同学"))
            for s in seg_hits:
                for keys, strength, kind in _SEED_RULES:
                    if any(k in s for k in keys):
                        if strength > best[0]:
                            best = (strength, kind)
                        break
            pairs[(lo, hi)] = best
    edges = []
    for (lo, hi), (strength, kind) in pairs.items():
        e = _empty_edge(lo, hi, strength, kind)
        edges.append(e)
    save(edges)
    return len(edges)


# 导入即播种（幂等）：新环境自动获得初始关系网,无需手工步骤
if not REL_PATH.exists():
    try:
        seed_from_personas()
    except Exception:
        pass
