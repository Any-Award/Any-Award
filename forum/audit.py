#!/usr/bin/env python3
"""论坛去AI味审计：纯标准库，零 LLM 成本。用数据说话，替代肉眼调 prompt。

输入
  output/snapshot-*.json  生成快照（评论扁平 {nickname, body, reply_to}）
  data/forum.json         论坛当前主数据（评论 author 对象、reply_to=楼层id）
  personas.json           catchphrase 词表 + exam_date（倒计时的唯一事实源）

用法
  python3 audit.py                    # 全部快照时间序 + live 现状 + 首尾对比
  python3 audit.py --latest 3         # 最近 3 份
  python3 audit.py --file A B         # 指定文件
  python3 audit.py --detail FILE      # 单文件完整违例清单

指标口径（对应 HANDOFF.md 缺陷编号）
  口癖密度   每人「含 catchphrase」消息占比；单条命中≥2处=堆砌（缺陷1）
  禁词命中   lexicon.BANNED_WORDS + 首先其次 共现（缺陷6 可自动化部分）
  倒计时     「还有X天」类表述 vs exam_date 现算（缺陷2 的量化）。
             含 来/多/几/左右 的模糊表述容差±12天，精确表述±3天；
             其他截止日期（作业/毕设）会误报，仅作线索看待。
  复读率     楼中楼与父评论的字符 bigram 包含率；>0.5 列嫌疑（缺陷3）
  长度分布   ≤15字占比（_length_budget 目标≈60%）、p50/p90
  结构均匀度 每帖评论数直方图；每角色 distinct-2（≥5条才统计）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import median

from lexicon import BANNED_COOC, BANNED_WORDS, COMPILED_FRAMES, DENSITY_WATCH, POSITIVE_MARKS

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
LIVE_PATH = HERE / "data" / "forum.json"
PERSONAS_PATH = HERE / "personas.json"

# 模糊量词的宽容差（"三十来天"说到 24-48 都算口语范围内）
FUZZY_TOL, EXACT_TOL = 12, 3
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_to_int(s: str) -> int | None:
    """三十六→36，七十→70；解析失败返回 None。"""
    if s.isdigit():
        return int(s)
    total = tmp = 0
    for ch in s:
        if ch in "零〇":
            continue
        if ch == "十":
            total += (tmp or 1) * 10
            tmp = 0
        elif ch == "百":
            total += (tmp or 1) * 100
            tmp = 0
        elif ch in _CN_DIGIT:
            tmp = _CN_DIGIT[ch]
        else:
            return None
    return total + tmp


_DAY_RE = re.compile(
    r"还(?:有|剩|差)?[^。！？\n]{0,4}?([0-9]+|[零〇一二两三四五六七八九十百]+)\s*(来|多|几)?\s*天")
_UNIT_RE = re.compile(
    r"还(?:有|剩)[^。！？\n]{0,3}?(半|一|两|二|三|几)?个?(月|星期|周|礼拜)")


def _unit_days(m: re.Match) -> tuple[int, bool] | None:
    n = m.group(1)
    mult = {"半": 0.5, "一": 1, "两": 2, "二": 2, "三": 3, "几": 2, None: 1}[n]
    days = {"月": 30, "星期": 7, "周": 7, "礼拜": 7}[m.group(2)] * mult
    return int(days), True


def _scan_countdown(text: str, actual: int) -> list[dict]:
    """返回 [{said, fuzzy, quote, ok}]。actual<=0（考完了）时不再审计。"""
    out = []
    for m in _DAY_RE.finditer(text):
        v = _cn_to_int(m.group(1))
        if v is None:
            continue
        fuzzy = bool(m.group(2))
        tol = FUZZY_TOL if fuzzy else EXACT_TOL
        out.append({"said": v, "fuzzy": fuzzy, "ok": abs(v - actual) <= tol,
                    "quote": _ctx(text, m.start(), m.end())})
    for m in _UNIT_RE.finditer(text):
        unit = _unit_days(m)
        if unit is None:
            continue
        v, _ = unit
        out.append({"said": v, "fuzzy": True, "ok": abs(v - actual) <= FUZZY_TOL,
                    "quote": _ctx(text, m.start(), m.end())})
    return out


def _ctx(text: str, a: int, b: int, width: int = 10) -> str:
    return text[max(0, a - width):min(len(text), b + width)].replace("\n", " ")


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s))


def load_lexicons() -> tuple[dict[str, list[str]], int | None]:
    personas = json.loads(PERSONAS_PATH.read_text(encoding="utf-8"))["personas"]
    phrases = {p["nickname"]: [ _norm(c) for c in (p.get("catchphrase") or []) ]
               for p in personas}
    actual = None
    today = date.today()
    for p in personas:
        exam = p.get("exam_date")
        if exam:
            y, m, d = (int(x) for x in str(exam).split("-"))
            actual = (date(y, m, d) - today).days
    return phrases, actual


def unify(path: Path) -> dict | None:
    """把两种数据形态归一成 threads[{nickname,title,body,comments[{nickname,body,parent_nick,parent_body}]}]。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"跳过 {path.name}: {exc}", file=sys.stderr)
        return None
    if data.get("type") == "forum_snapshot":
        meta = data.get("meta") or {}
        gen_at = meta.get("generated_at") or ""
        title = meta.get("title") or ""
        threads = data.get("threads") or []
    else:  # forum.json（live）
        gen_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
        title = "（live 现状）"
        threads = data.get("threads") or []
    ann = data.get("announcement") or None
    out_threads = []
    for t in threads:
        author = t.get("author") or {}
        nick = t.get("nickname") or author.get("nickname") or "?"
        cs = t.get("comments") or []
        id_map = {c.get("id"): c for c in cs if c.get("id")}
        norm_comments = []
        for c in cs:
            a = c.get("author") or {}
            cnick = c.get("nickname") or a.get("nickname") or "?"
            if a.get("kind") == "player":
                continue  # 玩家评论只作父文本，不计入 AI 指标
            rt = c.get("reply_to")
            parent = id_map.get(rt) if isinstance(rt, str) and rt in id_map else None
            if parent is None and rt and rt not in id_map:
                # 快照形态：reply_to 是昵称或「楼主」
                if rt in ("楼主", "lz", None, ""):
                    parent = None
                else:
                    prior = [x for x in cs
                             if (x.get("nickname") or (x.get("author") or {}).get("nickname")) == rt]
                    parent = prior[-1] if prior else None
            pbody = pnick = None
            if parent is not None:
                pa = parent.get("author") or {}
                pnick = parent.get("nickname") or pa.get("nickname")
                pbody = parent.get("body")
            if pnick in (None, "?") or rt in ("楼主", None, ""):
                pnick, pbody = "楼主", t.get("body")
            norm_comments.append({"nickname": cnick, "body": c.get("body") or "",
                                  "parent_nick": pnick, "parent_body": pbody})
        out_threads.append({"nickname": nick, "title": t.get("title") or "",
                            "body": t.get("body") or "", "comments": norm_comments})
    return {"name": path.stem if path.suffix == ".json" else path.name,
            "gen_at": gen_at, "title": title, "announcement": ann,
            "threads": out_threads}


def audit(src: dict, phrases: dict[str, list[str]], actual: int | None) -> dict:
    ai_msgs = []          # (nick, body, thread_title, thread_body, parent_nick, parent_body)
    for t in src["threads"]:
        ai_msgs.append((t["nickname"], t["body"], t["title"], t["body"], "楼主", t["body"]))
        for c in t["comments"]:
            ai_msgs.append((c["nickname"], c["body"], t["title"], t["body"],
                            c["parent_nick"], c["parent_body"]))
    ann = src.get("announcement") or {}
    all_bodies = ([ann.get("title", ""), ann.get("body", "")] if ann else []) \
        + [m[1] for m in ai_msgs]

    # ---- 口癖密度（缺陷1）
    by_nick = {}
    stacks = []
    for nick, body, *_ in ai_msgs:
        st = by_nick.setdefault(nick, {"n": 0, "hit": 0})
        st["n"] += 1
        text = _norm(body)
        hits = sum(text.count(ph) for ph in phrases.get(nick, []) if ph)
        if hits:
            st["hit"] += 1
        if hits >= 2:
            stacks.append({"nick": nick, "hits": hits, "quote": body[:40]})
    n_msgs = max(1, len(ai_msgs))
    hit_msgs = sum(v["hit"] for v in by_nick.values())

    # ---- 禁词（缺陷6 可自动化部分）
    banned_hits = []
    texts = [(ann.get("title", ""), "公告标题"), (ann.get("body", ""), "公告正文")] if ann else []
    texts += [(m[1], f"{m[0]}") for m in ai_msgs]
    for body, who in texts:
        if not body:
            continue
        nb = _norm(body)
        for w in BANNED_WORDS[15:]:      # 一方面/另一方面：单条消息内任一即计
            if w in nb:
                banned_hits.append({"who": who, "word": w, "quote": body[:40]})
        for w in BANNED_WORDS[:15]:
            if w in nb:
                banned_hits.append({"who": who, "word": w, "quote": body[:40]})
        for a, b in BANNED_COOC:
            if a in nb and b in nb:
                banned_hits.append({"who": who, "word": f"{a}…{b} 共现", "quote": body[:40]})

    # ---- 倒计时（缺陷2）
    countdown = []
    if actual and actual > 0:
        for body, who in texts:
            for item in _scan_countdown(_norm(body), actual):
                countdown.append({"who": who, **item})

    # ---- 句型帧/密度控/人味正指标（第二轮：让步-表态-伪口语从审计盲区变可见）
    frame_hits = []
    density_cnt = {name: 0 for name in DENSITY_WATCH}
    pos_cnt = {mk: 0 for mk in POSITIVE_MARKS}
    n_chars = 0
    for body, who in texts:
        if not body:
            continue
        nb = _norm(body)
        n_chars += len(nb)
        for pat in COMPILED_FRAMES:
            m = pat.search(nb)
            if m:
                frame_hits.append({"who": who, "frame": m.group(0), "quote": body[:40]})
        for name, (words, _limit) in DENSITY_WATCH.items():
            density_cnt[name] += sum(nb.count(_norm(w)) for w in words if w)
        for mk in POSITIVE_MARKS:
            pos_cnt[mk] += nb.count(mk)
    density_per_k = {k: round(v / max(1, n_chars) * 1000, 2) for k, v in density_cnt.items()}

    # ---- 复读率（缺陷3）：仅楼中楼
    rates, worst = [], []
    for nick, body, t_title, t_body, pnick, pbody in ai_msgs:
        if pnick in (None, "楼主"):
            continue
        bg, pbg = _bigrams(body), _bigrams(pbody or "")
        if min(len(bg), len(pbg)) < 4:
            continue
        r = len(bg & pbg) / min(len(bg), len(pbg))
        rates.append(r)
        if r > 0.5:
            worst.append({"nick": nick, "rate": round(r, 2),
                          "body": body[:30], "parent": (pbody or "")[:30]})
    # 顶楼复读标题（≥6字连续片段）
    title_parrot = []
    for nick, body, t_title, *_ in ai_msgs:
        nt, nb = _norm(t_title), _norm(body)
        if len(nt) < 6:
            continue
        for i in range(len(nt) - 5):
            if nt[i:i + 6] in nb:
                title_parrot.append({"nick": nick, "frag": nt[i:i + 6], "quote": body[:30]})
                break

    # ---- 长度分布
    lens = sorted(len(_norm(b)) for _, b, *_ in ai_msgs)
    n = len(lens) or 1
    dist = {
        "le15": sum(1 for x in lens if x <= 15) / n,
        "p50": lens[(n - 1) // 2] if lens else 0,
        "p90": lens[min(n - 1, int(n * 0.9))] if lens else 0,
    }

    # ---- 结构均匀度
    counts = [len(t["comments"]) for t in src["threads"]]
    d2 = {}
    per_nick = {}
    for nick, body, *_ in ai_msgs:
        per_nick.setdefault(nick, []).append(body)
    for nick, bodies in per_nick.items():
        bgs = [b for b in (_bigrams(x) for x in bodies) if len(b) >= 3]
        if len(bgs) >= 5:
            all_bg = [g for s in bgs for g in s]
            d2[nick] = round(len(set(all_bg)) / max(1, len(all_bg)), 2)

    lou = sum(1 for m in ai_msgs if m[4] not in (None, "楼主"))
    return {
        "src": src, "n_threads": len(src["threads"]), "n_comments": len(ai_msgs) - len(src["threads"]),
        "lou": lou,
        "phrases": phrases, "by_nick": by_nick, "density": hit_msgs / n_msgs,
        "stacks": stacks, "banned": banned_hits, "countdown": countdown,
        "rates": rates, "worst": worst, "title_parrot": title_parrot,
        "dist": dist, "counts": counts, "d2": d2, "actual_days": actual,
        "frames": frame_hits, "density_cnt": density_cnt, "density_per_k": density_per_k,
        "pos": pos_cnt, "n_chars": n_chars,
    }


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _p(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * q))]


def scorecard(r: dict) -> str:
    src = r["src"]
    d = r["dist"]
    lines = [
        f"== {src['name']}  [{src['gen_at']}] {src['title'][:24]}",
        f"   帖 {r['n_threads']} | 评 {r['n_comments']} | 楼中楼 {r['lou']}"
        f"（{pct(r['lou'] / max(1, r['n_comments']))}）",
        f"   长度: ≤15字 {pct(d['le15'])} | p50 {d['p50']} | p90 {d['p90']}字"
        f"   〔目标: ≤15字≈60%, p50<20〕",
        f"   口癖密度 {pct(r['density'])} | 堆砌(单条≥2处) {len(r['stacks'])}"
        f" | 禁词 {len(r['banned'])}"
        f" | 倒计时违例 {sum(1 for c in r['countdown'] if not c['ok'])}/{len(r['countdown'])}"
        f" | 复读p90 {_p(r['rates'], 0.9):.2f} 嫌疑 {len(r['worst'])}",
        f"   句型帧: ✗{len(r['frames'])}  密度控(次/千字): "
        + " ".join(f"{k} {v}" for k, v in r["density_per_k"].items())
        + "  人味符号: " + " ".join(f"{mk}{cnt}" for mk, cnt in r["pos"].items()),
    ]
    return "\n".join(lines)


def summary_row(name: str, r: dict) -> str:
    d = r["dist"]
    cd_bad = sum(1 for c in r["countdown"] if not c["ok"])
    return (f"{name:<34} 帖{r['n_threads']:>2} 评{r['n_comments']:>3} "
            f"|≤15字{pct(d['le15']):>4} p50{d['p50']:>3} p90{d['p90']:>3} "
            f"|口癖{pct(r['density']):>4} 堆砌{len(r['stacks'])} "
            f"|禁词{len(r['banned'])} 帧✗{len(r['frames'])} 倒计时✗{cd_bad} "
            f"|复读p90 {_p(r['rates'], 0.9):.2f} 嫌疑{len(r['worst'])}")


def detail(r: dict) -> str:
    out = [f"--- 细节: {r['src']['name']} ---"]
    actual = r["actual_days"]
    out.append(f"考研倒计时事实值: {actual} 天" if actual else "考研倒计时: 无 exam_date")
    if r["countdown"]:
        out.append("倒计时表述:")
        for c in r["countdown"]:
            flag = "✗" if not c["ok"] else " "
            out.append(f"  {flag} [{c['who']}] 说{c['said']}天({'模糊' if c['fuzzy'] else '精确'})  「{c['quote']}」")
    if r["banned"]:
        out.append("禁词命中:")
        for b in r["banned"][:10]:
            out.append(f"  ✗ [{b['who']}] 『{b['word']}』「{b['quote']}」")
    if r["frames"]:
        out.append("句型帧命中（绝对禁档）:")
        for f in r["frames"][:12]:
            out.append(f"  ✗ [{f['who']}] 帧『{f['frame']}』「{f['quote']}」")
    alarms = []
    for name, (words, limit) in DENSITY_WATCH.items():
        if r["density_cnt"][name] > limit:
            alarms.append(f"{name} {r['density_cnt'][name]}次(阈值{limit}/份)")
    out.append("密度控: " + ("⚠ " + "；".join(alarms) if alarms else "全部在阈值内")
               + " ｜每千字: " + " ".join(f"{k} {v}" for k, v in r["density_per_k"].items()))
    out.append("人味符号: " + " ".join(f"{mk}{cnt}" for mk, cnt in r["pos"].items()))
    if r["stacks"]:
        out.append("口癖堆砌（单条≥2处）:")
        for s in r["stacks"][:10]:
            out.append(f"  ✗ [{s['nick']}] ×{s['hits']} 「{s['quote']}」")
    density_line = "  ".join(
        f"{nick}{v['hit']}/{v['n']}" for nick, v in r["by_nick"].items() if v["n"])
    out.append(f"各角色口癖命中: {density_line}")
    if r["worst"]:
        out.append("楼中楼复读嫌疑（>0.5）:")
        for w in sorted(r["worst"], key=lambda x: -x["rate"])[:8]:
            out.append(f"  ✗ [{w['nick']}] {w['rate']:.2f} 「{w['body']}」←「{w['parent']}」")
    if r["title_parrot"]:
        out.append("顶楼复读标题片段:")
        for t in r["title_parrot"][:6]:
            out.append(f"  ✗ [{t['nick']}] 『{t['frag']}』「{t['quote']}」")
    out.append(f"每帖评论数: {r['counts']}")
    low_d2 = sorted(r["d2"].items(), key=lambda kv: kv[1])[:5]
    if low_d2:
        out.append("distinct-2 最低: " + "  ".join(f"{k}:{v}" for k, v in low_d2))
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="论坛去AI味审计")
    ap.add_argument("--latest", type=int, default=0, help="只看最近 N 份快照")
    ap.add_argument("--file", nargs="+", help="指定文件（可含 data/forum.json）")
    ap.add_argument("--detail", help="输出该文件的完整违例清单")
    ap.add_argument("--no-live", action="store_true", help="不审 data/forum.json")
    args = ap.parse_args()

    phrases, actual = load_lexicons()
    if args.file:
        paths = [Path(f) for f in args.file]
    else:
        paths = sorted(OUT_DIR.glob("snapshot-*.json"))
        if args.latest:
            paths = paths[-args.latest:]
        if LIVE_PATH.is_file() and not args.no_live:
            paths.append(LIVE_PATH)
    if args.detail:
        paths = [Path(args.detail)]

    srcs = [s for s in (unify(p) for p in paths) if s]
    if not srcs:
        print("没有可审计的文件")
        return
    results = [audit(s, phrases, actual) for s in srcs]

    if args.detail:
        print(detail(results[0]))
        return

    for r in results:
        print(scorecard(r))
    print("\n== 汇总（时间序） ==")
    print(f"{'文件':<34} 规模 |长度分布 |口癖/禁词/倒计时 |复读")
    for r in results:
        print(summary_row(r["src"]["name"], r))
    if len(results) >= 2:
        first, last = results[0], results[-1]
        print(f"\n== 首尾对比: {first['src']['name']} → {last['src']['name']} ==")
        rows = [
            ("口癖密度", pct(first["density"]), pct(last["density"])),
            ("≤15字占比", pct(first["dist"]["le15"]), pct(last["dist"]["le15"])),
            ("p50 长度", first["dist"]["p50"], last["dist"]["p50"]),
            ("堆砌条数", len(first["stacks"]), len(last["stacks"])),
            ("禁词命中", len(first["banned"]), len(last["banned"])),
            ("倒计时违例", sum(1 for c in first["countdown"] if not c["ok"]),
             sum(1 for c in last["countdown"] if not c["ok"])),
            ("复读p90", round(_p(first["rates"], 0.9), 2), round(_p(last["rates"], 0.9), 2)),
        ]
        for label, a, b in rows:
            print(f"  {label:<10} {a} → {b}")


if __name__ == "__main__":
    main()
