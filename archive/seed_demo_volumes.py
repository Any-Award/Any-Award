#!/usr/bin/env python3
"""从设计稿奖项库造几卷游戏内虚构评选档案，入校史馆（演示用）。

这些是游戏世界的虚构评选记录，用于让论坛有多个话题。
运行：python3 archive/seed_demo_volumes.py [--museum-root archive/museum]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import museum_writer

SCHOOL = "华清大学"
PLAYER = "吴主任"


def cand(cid, name, summary, materials):
    return {"id": cid, "name": name, "summary": summary, "materials": materials}


def record(award, premise, candidates, shortlist, qas, winner, citation, date):
    events = [{"type": "speech", "phase": "meeting", "actor": "郭校长", "text": premise}]
    events.append({"type": "shortlist", "item_ids": shortlist, "decided_by": PLAYER})
    for q in qas:
        events.append({"type": "qa", "phase": "defense", **q})
    if winner:
        events.append({"type": "decision", "winner": winner, "decided_by": PLAYER, "citation": citation})
    else:
        events.append({"type": "note", "phase": "ceremony", "text": citation})
    return {
        "schema_version": 1,
        "meta": {"source_module": "seed_demo", "award_name": award, "played_at": date,
                 "school_name": SCHOOL, "player_name": PLAYER},
        "participants": [{"name": "郭校长"}, {"name": "赵副主任"}, {"name": "钱教授"},
                         {"name": "孙处长"}, {"name": "李部长"}, {"name": "周处长"}],
        "candidates": candidates,
        "events": events,
        "outcome": {"final_order": None, "shortlist": shortlist, "winner": winner},
    }


VOLUMES = [
    record(
        "第十名奖学金",
        "有经验称第十名左右的学生既有学术能力又不为成绩所累，更可能作出成就。特设第十名奖学金，只奖励年级第8至第12名。",
        [
            cand("S01", "何岸", "经济学院 · 年级第10名", "姓名：何岸\n年级排名：10/210\n个人陈述：我正好第十，挺巧的。平时不算最拼，但也没掉队。\n导师意见：该生成绩稳定，心态松弛，均衡发展。"),
            cand("S02", "秦朗", "经济学院 · 年级第13名", "姓名：秦朗\n年级排名：13/210\n个人陈述：我第十三，差三名。这学期我故意少刷了两门课的绩点，想往区间里靠。\n导师意见：该生近期成绩波动，似有刻意控分迹象。"),
            cand("S03", "苏晚", "经济学院 · 年级第9名", "姓名：苏晚\n年级排名：9/210\n个人陈述：我第九，本来没想参评，辅导员说我符合就报了。\n导师意见：该生一贯稳定，非刻意控分。"),
        ],
        ["S01", "S02", "S03"],
        [{"candidate": "S02", "questioner": "钱教授", "question": "你这学期绩点下滑，是实力变化还是刻意控分？", "answer": "我承认少刷了两门课。但第十名奖学金奖的就是这个区间，我往区间靠，算不算违背初衷？"},
         {"candidate": "S01", "questioner": "孙处长", "question": "你正好第十，是巧合还是也算准了？", "answer": "真巧合。我要能算准，早去算彩票了。"}],
        "S01", "何岸，年级第10名，心态松弛、均衡发展，契合本奖理念。", "2026-11-10T10:00:00",
    ),
    record(
        "最有科研潜力情侣奖",
        "为让美好感情与科研热情交相辉映，设最有科研潜力情侣奖。须一对情侣两人组队参评，既考察科研能力，也要求感情好、默契好，双人一同上台答辩。",
        [
            cand("C01", "林知夏 & 顾行舟", "物理学院 · 真情侣科研搭档", "姓名：林知夏 & 顾行舟\n关系：情侣\n科研：合作发表SCI二区论文1篇，共同完成课题\n个人陈述：我们在一起两年，课题也是一起做的，分工明确。\n导师意见：两人合作真实，贡献相当。"),
            cand("C02", "陈默 & 周雨桐", "计算机学院 · 疑似假扮", "姓名：陈默 & 周雨桐\n关系：自称情侣\n科研：各自方向不同，无合作成果\n个人陈述：我们感情很好，科研潜力体现在各自领域。\n导师意见：两人无共同科研产出，关系存疑。"),
        ],
        ["C01", "C02"],
        [{"candidate": "C02", "questioner": "钱教授", "question": "你们没有合作成果，怎么证明科研潜力是'情侣'的？", "answer": "我们各自都很强，加起来更强。感情好不一定非要一起发论文吧。"},
         {"candidate": "C01", "questioner": "李部长", "question": "你们答辩时谁主谁次？贡献怎么分？", "answer": "论文我一作他二作，但实验他做得多。我们没分那么细，反正是一起的。"}],
        "C01", "林知夏 & 顾行舟，真实情侣科研搭档，合作成果扎实、默契自然。", "2026-11-11T14:00:00",
    ),
    record(
        "罗素奖",
        "大量学生终其大学生涯没能获得任何奖励，这实在让人遗憾。以罗素之名设罗素奖——罗素奖颁发给所有没有获得罗素奖的学生。",
        [
            cand("R01", "全体学生", "悖论对象", "姓名：全体学生\n说明：若某人获得罗素奖，则他属于'获得罗素奖的学生'，按规则不应获奖；若他不获奖，则他属于'没获得罗素奖的学生'，按规则应获奖。"),
        ],
        ["R01"],
        [{"candidate": "R01", "questioner": "赵副主任", "question": "这份获奖名单，逻辑上能成立吗？", "answer": "委员会退回名单三次。获奖当且仅当不获奖，无法形成一致名单。建议校长明确措辞，或允许歧义本身成为玩法。"}],
        None, "本届罗素奖因自指悖论无法形成一致获奖名单，暂缓颁发，留待解释权争议解决。", "2026-11-12T09:00:00",
    ),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--museum-root", default=str(Path(__file__).resolve().parent / "museum"))
    args = ap.parse_args()
    root = Path(args.museum_root)
    import json
    existing = set()
    for f in root.glob("volumes/*/*/session_meta.json"):
        try:
            existing.add(json.loads(f.read_text(encoding="utf-8")).get("award_name"))
        except (OSError, json.JSONDecodeError):
            pass
    n = 0
    for rec in VOLUMES:
        if rec["meta"]["award_name"] in existing:
            print(f"跳过已存在：{rec['meta']['award_name']}")
            continue
        tmp = root.parent / f"_seed_{rec['meta']['award_name']}.json"
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        museum_writer.deposit(tmp, root)
        tmp.unlink()
        n += 1
    print(f"新造 {n} 卷入馆")


if __name__ == "__main__":
    main()
