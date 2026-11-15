#!/usr/bin/env python3
"""采集层 · shared_ordering → 对局记录。

读取 shared_ordering_simulation 落盘的 shared_ordering.json
（SharedOrderingController.get_state() 的序列化），转换为 schema.json 约束的
对局记录 JSON。纯标准库，不依赖 Concordia，可在无后端环境单独测试。

说明：
- 后端 prompts.json 里的五位委员以英文名注册，卷宗使用游戏内称谓，
  KNOWN_NAMES 提供默认映射，可用 --name-map 覆盖。
- 被控制器拒绝的操作（accepted=false，如 JSON 不合法）不进卷宗，
  仅在生成时报告数量。

用法：
  python3 adapters/shared_ordering.py STATE.json -o RECORD.json \
      [--award 有志少年奖] [--school 本校] [--player 吴主任] \
      [--played-at ISO8601] [--model 名称] [--prompts-digest 串] \
      [--name-map "Dean Zhao=赵副主任,Prof Qian=钱教授"]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

KNOWN_NAMES = {
    "Dean Zhao": "赵副主任",
    "Prof Qian": "钱教授",
    "Chief Sun": "孙处长",
    "Chief Li": "李部长",
    "Chief Zhou": "周处长",
}

_FIELD_RE = re.compile(r"^([^：:]{1,12})[：:](.*)$")


def parse_name_map(text) -> dict:
    overrides = {}
    for pair in str(text or "").split(","):
        if "=" in pair:
            key, value = pair.split("=", 1)
            overrides[key.strip()] = value.strip()
    return overrides


def map_name(raw, overrides) -> str:
    name = str(raw)
    return overrides.get(name, KNOWN_NAMES.get(name, name))


def parse_candidate(item_id, text) -> dict:
    fields = {}
    for line in str(text).splitlines():
        m = _FIELD_RE.match(line.strip())
        if m:
            fields.setdefault(m.group(1).strip(), m.group(2).strip())
    summary = " · ".join(x for x in (fields.get("学院"), fields.get("专业")) if x)
    return {
        "id": str(item_id),
        "name": fields.get("姓名") or str(item_id),
        "summary": summary,
        "materials": str(text),
    }


def convert(state, args) -> tuple[dict, int]:
    played_at = args.played_at
    if not played_at:
        mtime = Path(args.state).stat().st_mtime
        played_at = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")

    overrides = parse_name_map(args.name_map)
    candidates = [
        parse_candidate(iid, text)
        for iid, text in (state.get("item_descriptions") or {}).items()
    ]

    events = []
    accepted = sorted(
        (e for e in state.get("action_log") or [] if e.get("accepted")),
        key=lambda e: (int(e.get("round", 0)), int(e.get("turn", 0))),
    )
    for e in accepted:
        actor = map_name(e.get("actor") or e.get("participant"), overrides)
        common = {
            "round": e.get("round"),
            "turn": e.get("turn"),
            "revision": e.get("revision"),
        }
        op = str(e.get("op", "")).upper()
        if op == "MOVE":
            events.append({
                "type": "move",
                "actor": actor,
                "item_id": str(e.get("item_id")),
                "from_position": e.get("from_position"),
                "to_position": e.get("to_position"),
                "reason": str(e.get("reason") or ""),
                "order_after": e.get("order_after"),
                **common,
            })
        elif op == "PASS":
            events.append({
                "type": "pass",
                "actor": actor,
                "reason": str(e.get("reason") or ""),
                **common,
            })

    rejected = sum(1 for e in state.get("action_log") or [] if e.get("accepted") is False)

    record = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "source_module": "shared_ordering",
            "award_name": args.award,
            "played_at": played_at,
            "school_name": args.school or None,
            "player_name": args.player or None,
            "model": args.model or None,
            "prompts_digest": args.prompts_digest or None,
        },
        "participants": [
            {"name": map_name(n, overrides)} for n in state.get("player_names") or []
        ],
        "candidates": candidates,
        "events": events,
        "outcome": {
            "final_order": state.get("order"),
            "shortlist": [],
            "winner": None,
        },
    }
    return record, rejected


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="shared_ordering.json → 对局记录 JSON")
    parser.add_argument("state", help="shared_ordering_simulation 落盘的 JSON")
    parser.add_argument("-o", "--output", required=True, help="输出记录 JSON 路径")
    parser.add_argument("--award", default="有志少年奖", help="奖项名")
    parser.add_argument("--school", default="", help="校名（玩家设置）")
    parser.add_argument("--player", default="", help="玩家称呼")
    parser.add_argument("--played-at", default="", help="ISO 8601；缺省取输入文件修改时间")
    parser.add_argument("--model", default="", help="LLM 名称（登记簿用）")
    parser.add_argument("--prompts-digest", default="", help="prompts 指纹（登记簿用）")
    parser.add_argument("--name-map", default="", help='覆盖委员名映射，如 "Dean Zhao=赵副主任"')
    args = parser.parse_args(argv)

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    record, rejected = convert(state, args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成记录：{out}（{len(record['events'])} 个有效操作，{rejected} 个被拒操作已剔除）")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
