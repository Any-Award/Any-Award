#!/usr/bin/env python3
"""校史馆档案系统 · 渲染层。

把一局游戏的"对局记录 JSON"（契约见 schema.json）整理成馆藏卷宗并存档：

  deposit：校验记录 → 按年度自动编卷宗号 → 写卷宗 volume.md（展品，玩家向）
           + 馆务登记簿 session_meta.json（技术向） → 重建馆藏目录 index.md
  index：  仅重建馆藏目录

馆藏结构（支持多卷宗长期存放）：

  <museum-root>/index.md                                  总目录，每次入馆后重建
  <museum-root>/volumes/<YYYY>/<NNN>-<奖项slug>/volume.md          卷宗正文
  <museum-root>/volumes/<YYYY>/<NNN>-<奖项slug>/session_meta.json  登记簿

卷宗号按年度递增，永不覆盖既有卷宗；同一奖项办多届、多个奖项并行，各占一卷，
靠 session_id 关联同局记录。

用法：
  python3 museum_writer.py deposit RECORD.json [--museum-root DIR]
  python3 museum_writer.py index [--museum-root DIR]

本文件只依赖标准库；采集 adapter（见 adapters/）负责把后端/前端输出转成记录 JSON。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
META_FORMAT = "anyaward-museum-meta"

EVENT_TYPES = ("speech", "move", "pass", "shortlist", "qa", "decision", "note")

DEFAULT_PHASE = {
    "speech": "meeting",
    "move": "review",
    "pass": "review",
    "shortlist": "review",
    "qa": "defense",
    "decision": "ceremony",
    "note": "aftermath",
}

PHASES = (
    ("meeting", "设奖缘起"),
    ("review", "报名与审阅"),
    ("defense", "答辩实录"),
    ("ceremony", "裁定与颁奖"),
    ("aftermath", "余波"),
)

CN_NUM = ("一", "二", "三", "四", "五")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def one_line(text) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def esc_cell(text) -> str:
    return one_line(text).replace("|", "\\|")


def quote_block(prefix: str, text: str) -> str:
    return ("> " + prefix + str(text).strip()).replace("\n", "\n> ")


def _strip_tail(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def candidate_map(record) -> dict:
    return {str(c.get("id")): c for c in record.get("candidates") or [] if c.get("id") is not None}


def candidate_name(record, item_id) -> str:
    cand = candidate_map(record).get(str(item_id))
    if cand and cand.get("name"):
        return str(cand["name"])
    return str(item_id)


def candidate_summary(record, item_id) -> str:
    cand = candidate_map(record).get(str(item_id))
    return str(cand.get("summary") or "") if cand else ""


def phase_of(event) -> str:
    return str(event.get("phase") or DEFAULT_PHASE[event["type"]])


# ---------------------------------------------------------------------------
# 校验（系统边界：记录 JSON 可能来自队友模块或手写）
# ---------------------------------------------------------------------------

REQUIRED_EVENT_FIELDS = {
    "speech": ("text",),
    "move": ("item_id", "to_position"),
    "pass": (),
    "shortlist": ("item_ids",),
    "qa": ("candidate", "question"),
    "decision": ("winner",),
    "note": ("text",),
}


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("记录必须是 JSON 对象")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version 必须是 {SCHEMA_VERSION}")
    meta = record.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("缺少 meta 对象")
    for key in ("source_module", "award_name", "played_at"):
        if not one_line(meta.get(key)):
            raise ValueError(f"meta.{key} 不能为空")
    events = record.get("events")
    if not isinstance(events, list):
        raise ValueError("events 必须是数组")
    for i, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"events[{i}] 必须是对象")
        etype = event.get("type")
        if etype not in EVENT_TYPES:
            raise ValueError(f"events[{i}].type 未知：{etype!r}（允许：{EVENT_TYPES}）")
        for field in REQUIRED_EVENT_FIELDS[etype]:
            if event.get(field) is None:
                raise ValueError(f"events[{i}]（{etype}）缺少字段 {field}")
    return record


# ---------------------------------------------------------------------------
# 各幕渲染
# ---------------------------------------------------------------------------

def render_meeting(record, ctx, events) -> list[str]:
    lines: list[str] = []
    for e in events:
        if e["type"] == "speech":
            actor = str(e.get("actor") or "")
            prefix = f"**{actor}**：" if actor else ""
            lines.append(quote_block(prefix, e.get("text") or ""))
            lines.append("")
        elif e["type"] == "note":
            lines.append(one_line(e.get("text")))
            lines.append("")
    return _strip_tail(lines)


def render_review(record, ctx, events) -> list[str]:
    lines: list[str] = []
    cands = record.get("candidates") or []
    if cands:
        names = "、".join(str(c.get("name") or c.get("id")) for c in cands)
        lines.append(f"收到报名材料 {len(cands)} 份：{names}。")
        lines.append("")
    rows = []
    seq = 0
    for e in events:
        if e["type"] == "move":
            seq += 1
            obj = str(e.get("item_name") or candidate_name(record, e.get("item_id")))
            change = f"第{e.get('from_position', '?')}位 → 第{e.get('to_position', '?')}位"
            rows.append((seq, e.get("actor") or "", obj, change, e.get("reason") or ""))
        elif e["type"] == "pass":
            seq += 1
            rows.append((seq, e.get("actor") or "", "—", "弃权", e.get("reason") or ""))
    if rows:
        lines += ["评选纪实如下——", "", "| # | 主张 | 对象 | 变动 | 理由 |", "|---|------|------|------|------|"]
        for seq, actor, obj, change, reason in rows:
            lines.append(f"| {seq} | {esc_cell(actor)} | {esc_cell(obj)} | {esc_cell(change)} | {esc_cell(reason)} |")
        lines.append("")
    outcome = record.get("outcome") or {}
    if outcome.get("final_order"):
        names = "、".join(candidate_name(record, iid) for iid in outcome["final_order"])
        lines.append(f"委员会最终推荐顺序：{names}。")
        lines.append("")
    for e in events:
        if e["type"] == "shortlist":
            names = "、".join(candidate_name(record, iid) for iid in e.get("item_ids") or [])
            by = str(e.get("decided_by") or ctx["player"])
            lines.append(f"入围答辩名单：{names}（由{by}批定）。")
            lines.append("")
    if cands and not outcome.get("winner"):
        lines.append("其余候选人材料随卷存档，不作负面定性。")
        lines.append("")
    return _strip_tail(lines)


def render_defense(record, ctx, events) -> list[str]:
    lines: list[str] = []
    for e in events:
        if e["type"] == "qa":
            name = candidate_name(record, e.get("candidate"))
            summary = candidate_summary(record, e.get("candidate"))
            head = f"**{name}**" + (f"（{summary}）" if summary else "")
            questioner = str(e.get("questioner") or "")
            question = one_line(e.get("question"))
            lines.append(head)
            lines.append(f"问（{questioner}）：{question}" if questioner else f"问：{question}")
            answer = str(e.get("answer") or "").strip()
            if answer:
                lines.append(quote_block("答：“", answer + "”"))
            lines.append("")
        elif e["type"] == "note":
            lines.append(one_line(e.get("text")))
            lines.append("")
    return _strip_tail(lines)


def render_ceremony(record, ctx, events) -> list[str]:
    lines: list[str] = []
    for e in events:
        if e["type"] == "decision":
            lines.append(f"获奖者：**{candidate_name(record, e.get('winner'))}**。")
            lines.append("")
            citation = str(e.get("citation") or "").strip()
            if citation:
                lines.append(quote_block("颁奖辞：", citation))
                lines.append("")
            by = str(e.get("decided_by") or ctx["player"])
            lines.append(f"名单由{by}签署，荣誉证书亲手交付。")
            lines.append("")
        elif e["type"] == "note":
            lines.append(one_line(e.get("text")))
            lines.append("")
    return _strip_tail(lines)


def render_aftermath(record, ctx, events) -> list[str]:
    lines: list[str] = []
    for e in events:
        if e["type"] == "speech":
            actor = str(e.get("actor") or "")
            lines.append(quote_block(f"**{actor}**：" if actor else "", e.get("text") or ""))
            lines.append("")
        elif e["type"] == "note":
            lines.append(one_line(e.get("text")))
            lines.append("")
    return _strip_tail(lines)


RENDERERS = {
    "meeting": render_meeting,
    "review": render_review,
    "defense": render_defense,
    "ceremony": render_ceremony,
    "aftermath": render_aftermath,
}


# ---------------------------------------------------------------------------
# 卷宗渲染
# ---------------------------------------------------------------------------

def render_volume(record, vol: dict) -> str:
    meta = record["meta"]
    ctx = {
        "school": one_line(meta.get("school_name")) or "本校",
        "player": one_line(meta.get("player_name")) or "吴主任",
    }
    sections = []
    for phase_key, title in PHASES:
        events = [e for e in record["events"] if phase_of(e) == phase_key]
        body = RENDERERS[phase_key](record, ctx, events)
        if any(ln.strip() for ln in body):
            sections.append((title, body))
    if not sections:
        sections = [("存档登记", ["本卷暂无过程记录，仅作存档登记。"])]

    lines = [
        f"# {ctx['school']}校史馆 · 荣誉档案室",
        "",
        f"## {vol['doc_no']} ——「{one_line(meta['award_name'])}」",
        "",
        f"> 入馆日期：{vol['date']}　｜　整理：奖励执行委员会（组长：{ctx['player']}）",
        f"> 本卷收录：{'、'.join(t for t, _ in sections)}",
        "",
    ]
    for i, (title, body) in enumerate(sections):
        lines += [f"### {CN_NUM[i]} · {title}", ""] + body + [""]
    if not any(title == "裁定与颁奖" for title, _ in sections):
        lines += [f"获奖名单待{ctx['player']}裁定后补录。", ""]

    materials = [c for c in record.get("candidates") or [] if c.get("materials")]
    if materials:
        lines += ["---", "", f"<details><summary>附录 · 报名材料原文（{len(materials)}份）</summary>", ""]
        for c in materials:
            cid = str(c.get("id") or "")
            name = str(c.get("name") or cid)
            lines += ["", f"### {cid} · {name}", ""]
            for ln in str(c["materials"]).splitlines():
                lines.append(("> " + ln) if ln.strip() else ">")
        lines += ["", "</details>", ""]

    lines += ["---", "", "*本卷宗由档案系统自动整理入馆。*"]
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# 馆藏结构与编号
# ---------------------------------------------------------------------------

def slugify(text) -> str:
    s = re.sub(r'[\\/:*?"<>|\s（）()〔〕【】]+', "-", str(text)).strip("-.")
    return s or "award"


def year_of(played_at) -> int:
    m = re.match(r"\s*(\d{4})", str(played_at))
    return int(m.group(1)) if m else datetime.now().year


def assign_volume(museum_root: Path, year: int, award_name: str) -> tuple[int, Path]:
    year_dir = museum_root / "volumes" / str(year)
    year_dir.mkdir(parents=True, exist_ok=True)
    taken = set()
    for child in year_dir.iterdir():
        m = re.match(r"^(\d{3})-", child.name)
        if m:
            taken.add(int(m.group(1)))
    no = 1
    while no in taken:
        no += 1
    slug = slugify(award_name)
    dir_name = f"{no:03d}-{slug}"
    while (year_dir / dir_name).exists():
        no += 1
        dir_name = f"{no:03d}-{slug}"
    return no, year_dir / dir_name


def rebuild_index(museum_root: Path) -> None:
    entries = []
    for meta_path in sorted(museum_root.glob("volumes/*/*/session_meta.json")):
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("format") != META_FORMAT:
            continue
        m = dict(m)
        m["link"] = str((meta_path.parent / "volume.md").relative_to(museum_root))
        entries.append(m)
    entries.sort(key=lambda m: (m.get("year", 0), m.get("volume_no", "000")))

    lines = [
        "# 校史馆 · 馆藏目录",
        "",
        "凡入馆卷宗均按年度与入馆顺序编号；技术性登记见各卷 session_meta.json（馆务登记簿，非展品）。",
        "",
    ]
    by_year: dict = {}
    for m in entries:
        by_year.setdefault(m.get("year"), []).append(m)
    if not by_year:
        lines.append("馆内暂无卷宗。")
    for year in sorted(by_year, key=lambda y: int(y)):
        lines += [f"## {year} 年度", "", "| 卷宗号 | 奖项 | 获奖者 | 入馆日期 | 卷宗 |", "|---|------|--------|----------|------|"]
        for m in by_year[year]:
            winner = m.get("winner_display") or "（暂未裁定）"
            link = f"[{m.get('volume_no')}-{m.get('award_name')}](<{m['link']}>)"
            lines.append(
                f"| {m.get('doc_no')} | {m.get('award_name')} | {winner} "
                f"| {str(m.get('deposited_at', ''))[:10]} | {link} |"
            )
        lines.append("")
    museum_root.mkdir(parents=True, exist_ok=True)
    (museum_root / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 入馆
# ---------------------------------------------------------------------------

def deposit(record_path: Path, museum_root: Path) -> None:
    record = validate_record(load_json(record_path))
    meta = record["meta"]
    now = datetime.now()
    year = year_of(meta["played_at"])
    award = one_line(meta["award_name"])
    no, volume_dir = assign_volume(museum_root, year, award)
    doc_no = one_line(meta.get("award_doc_no")) or f"校奖发〔{year}〕{no:03d}号"

    vol = {"no": f"{no:03d}", "doc_no": doc_no, "date": now.strftime("%Y-%m-%d")}
    volume_md = render_volume(record, vol)

    outcome = record.get("outcome") or {}
    winner_display = candidate_name(record, outcome["winner"]) if outcome.get("winner") else ""
    meta_out = {
        "format": META_FORMAT,
        "version": SCHEMA_VERSION,
        "volume_no": f"{no:03d}",
        "doc_no": doc_no,
        "year": year,
        "volume_dir": str(volume_dir.relative_to(museum_root)),
        "school_name": one_line(meta.get("school_name")) or "本校",
        "player_name": one_line(meta.get("player_name")) or "吴主任",
        "award_name": award,
        "source_module": one_line(meta["source_module"]),
        "session_id": one_line(meta.get("session_id")) or uuid.uuid4().hex,
        "played_at": one_line(meta["played_at"]),
        "deposited_at": now.isoformat(timespec="seconds"),
        "model": meta.get("model") or None,
        "prompts_digest": meta.get("prompts_digest") or None,
        "winner_display": winner_display,
        "counts": {
            "events": len(record["events"]),
            "moves": sum(1 for e in record["events"] if e["type"] == "move"),
            "passes": sum(1 for e in record["events"] if e["type"] == "pass"),
        },
    }

    volume_dir.mkdir(parents=True, exist_ok=True)
    (volume_dir / "volume.md").write_text(volume_md, encoding="utf-8")
    (volume_dir / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (volume_dir / "session_meta.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    rebuild_index(museum_root)
    print(f"已入馆：{volume_dir / 'volume.md'}")
    print(f"卷宗号：{doc_no}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="校史馆档案系统：把对局记录 JSON 整理成馆藏卷宗")
    sub = parser.add_subparsers(dest="command", required=True)
    p_deposit = sub.add_parser("deposit", help="入馆一份对局记录")
    p_deposit.add_argument("record", help="对局记录 JSON 路径")
    p_deposit.add_argument("--museum-root", default="museum", help="馆藏根目录（默认 ./museum）")
    p_index = sub.add_parser("index", help="仅重建馆藏目录")
    p_index.add_argument("--museum-root", default="museum", help="馆藏根目录（默认 ./museum）")
    args = parser.parse_args(argv)
    root = Path(args.museum_root)
    if args.command == "deposit":
        deposit(Path(args.record), root)
    else:
        rebuild_index(root)
        print(f"馆藏目录已重建：{root / 'index.md'}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
