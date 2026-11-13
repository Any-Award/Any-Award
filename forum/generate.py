#!/usr/bin/env python3
"""论坛生成器：事件简报 → 论坛快照（主题帖 + 评论）。

三个调用入口：
  CLI：   python3 generate.py --input pack.json [--threads 4]
          python3 generate.py --volume <volume.md>   （经 adapters/museum_volume 转换）
  API：   from generate import generate_snapshot
  HTTP：  见 server.py（POST /generate）

LLM 配置从 --env 的 OpenAI 兼容配置读取（默认 <工作区>/Any-Award-Backend/.env）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

from render import render
import memory

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent


def load_personas() -> dict:
    return json.loads((HERE / "personas.json").read_text(encoding="utf-8"))


def load_llm_env() -> dict:
    """读取 LLM 配置，密钥不落项目。

    优先级：环境变量 > 项目 .env（非空值）> 项目外私有密钥文件 ~/.anyaward-secrets.env。
    项目内 .env 只留占位即可分享；真实密钥放在私有文件（权限 600）。
    """
    keys = ("LLM_API_KEY", "LLM_API_BASE", "LLM_MODEL_NAME",
            "EMBED_API_KEY", "EMBED_API_BASE", "EMBED_MODEL_NAME")
    env = {}
    secret = Path.home() / ".anyaward-secrets.env"
    if secret.is_file():
        env.update({k: v for k, v in dotenv_values(str(secret)).items() if v})
    proj = WORKSPACE / "Any-Award-Backend" / ".env"
    if proj.is_file():
        env.update({k: v for k, v in dotenv_values(str(proj)).items() if v})
    env.update({k: os.environ[k] for k in keys if os.environ.get(k)})
    return env


def persona_card(p: dict) -> str:
    lines = [
        f"- 昵称：{p['nickname']}（{p['tag']}）",
        f"  身份：{p['personality']}",
        f"  语气与口癖：{p['style']}",
        f"  表达缺陷（要体现）：{p.get('flaw', '')}",
        f"  边界：{p['boundary']}",
        f"  出没场景：{p['scene']}",
        f"  关系：{p['relations']}",
    ]
    examples = p.get("examples") or []
    if examples:
        lines.append("  说话样板（照这个腔调和长短来，别照抄内容，学它的随意和碎）：")
        lines += [f"    · {e}" for e in examples]
    return "\n".join(lines)


def humanize_block() -> str:
    return "\n".join([
        "【去AI味·硬清单（命中即失败，全文搜索必须为0）】",
        "禁用词：综上所述/总的来说/总而言之/说白了/本质上/换句话说/值得注意的是/不难发现/众所周知/毋庸置疑/这意味着/由此可见/那么问题来了/你可能会问/首先其次最后/一方面另一方面/不得不说。",
        "禁用句式：『不是A，而是B』翻案句、『不是A…不是B…是C』否定铺垫、『X。就是这样。』碎片装深沉、自问自答、排比对仗。",
        "禁用标点：用冒号引出列举或解释、破折号——做停顿、双引号\"\"强调概念（要强调用「」或直接写）。",
        "禁用格式：加粗、小标题、bullet 罗列、编号论证（除非该人设的说话样板里就这么说）。",
        "【effort 分布】像真论坛：大部分评论是低 effort，一个字到一句话（草/蹲/+1/笑死/插眼/确实/啊这），四五条里才有一条稍微长点的看法。允许敷衍、词穷、答非所问、说一半不说了、纯表情。",
        "【最高原则】最像，而不是最好。宁可说得烂、说得短、说得跑题，也不要说得正确又完整。别端着，别升华，别总结。",
        "【对照】AI味（禁止）：『我认为这个评选存在三个问题：首先…其次…最后…综上所述…』",
        "真人味（学这个）：『不是 我室友天天泡实验室结果连入围都没有 他回来一句话没说 我都不敢问…这奖到底看啥啊』『草』『蹲一个 顺便二食堂还有糖醋里脊吗』",
        "【盖楼范例】（reply_to 这样用，要有人互相回复，别都只回楼主）：",
        "  梗先知（reply_to=楼主）：草 这也行",
        "  老蔡不姓蔡（reply_to=梗先知）：等下 我算算",
        "  阿穹（reply_to=老蔡不姓蔡）：蔡老师你别算了 人家图一乐",
        "  奶油小方（reply_to=楼主）：抱抱 没事的~",
    ])


def rules_block(rules: list[str]) -> str:
    return "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))


def chat(client: OpenAI, model: str, system: str, user: str, temperature: float, max_tokens: int) -> dict:
    for attempt in range(2):  # 模型偶发非法 JSON，重试一次
        resp = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        try:
            return json.loads(resp.choices[0].message.content)
        except json.JSONDecodeError:
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def generate_threads(client, model, personas, rules, title, public_text, n_threads, temperature) -> dict:
    import random
    posters = random.sample(personas, min(n_threads, len(personas)))
    system = (
        "你是校园论坛的学生扮演系统。你根据给定的公开信息和一批学生人设，"
        "以不同学生的口吻撰写论坛帖子。输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules) + "\n\n" + humanize_block()
    )
    cards = "\n".join(persona_card(p) for p in posters)
    footprints_block = memory.footprints([p["nickname"] for p in posters])
    hot = memory.hot_topics()
    user = (
        f"学生人设（本次发帖人，共 {len(posters)} 人）：\n{cards}\n\n"
        + (f"{footprints_block}\n\n" if footprints_block else "")
        + (f"{hot}\n\n" if hot else "")
        + f"话题：{title}\n\n"
        f"公开信息（你的全部事实来源）：\n---\n{public_text}\n---\n\n"
        f"任务：\n"
        f"1. 以『论坛管理员』身份写一个置顶公告帖（转述公开信息中的评选结果，语气官方、克制、简短）；\n"
        f"2. 写 {len(posters)} 个主题帖，按上述人设顺序每帖对应一位发帖人（用其昵称），"
        f"态度和文风必须符合人设，且彼此不同；可延续其近期足迹里的梗和话题，但不要与之前的自己矛盾；"
        f"帖子要像真的帖子：有标题，正文长短不一。\n\n"
        f"输出 JSON：{{\"announcement\": {{\"title\": \"...\", \"body\": \"...\"}}, "
        f"\"threads\": [{{\"nickname\": \"人设昵称\", \"title\": \"...\", \"body\": \"...\"}}]}}"
    )
    return chat(client, model, system, user, temperature, max_tokens=6000)


def generate_comments(client, model, personas, rules, thread, temperature) -> dict:
    system = (
        "你是校园论坛的学生扮演系统。给定一个论坛主题帖，你以其他学生的口吻撰写评论。"
        "输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules) + "\n\n" + humanize_block()
    )
    import random
    others = [p for p in personas if p["nickname"] != thread.get("nickname")]
    others = random.sample(others, min(6, len(others)))
    cards = "\n".join(persona_card(p) for p in others)
    footprints_block = memory.footprints([p["nickname"] for p in others], k=2, width=40)
    hot = memory.hot_topics()
    user = (
        f"学生人设（评论只能从这些人里选，不能是楼主本人）：\n{cards}\n\n"
        + (f"{footprints_block}\n\n" if footprints_block else "")
        + (f"{hot}\n\n" if hot else "")
        + f"主题帖（楼主：{thread.get('nickname')}）：\n标题：{thread.get('title')}\n正文：{thread.get('body')}\n\n"
        f"任务：写 4~6 条评论，像真实盖楼。必须出现至少一组楼中楼（有人回复楼主后，另一人回复那条 AI 评论，再有人接下去），"
        f"不要所有人都只回复楼主。reply_to 填『楼主』或对方昵称。要有歪楼、接梗、抬杠、纯情绪短评（有的就一个字），"
        f"长度长短不一，不要每条都完整论证。符合各自人设口吻和表达缺陷，可延续自己之前的立场；抬杠对事不对人。\n\n"
        f"输出 JSON：{{\"comments\": [{{\"nickname\": \"人设昵称\", \"body\": \"...\", \"reply_to\": \"楼主或对方昵称\"}}]}}"
    )
    return chat(client, model, system, user, temperature, max_tokens=3000)


def generate_replies_to_comment(client, model, personas, rules, thread, target_comment, recent_comments, temperature) -> dict:
    """针对玩家的一条具体评论生成学生回应（真正的对话，不是泛泛谈主帖）。"""
    system = (
        "你是校园论坛的学生扮演系统。玩家在帖子下发表了一条评论，"
        "你要让其他学生针对这条评论作出回应，形成真实对话。输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules) + "\n\n" + humanize_block()
    )
    import random
    others = [p for p in personas if p["nickname"] != thread.get("nickname")]
    others = random.sample(others, min(6, len(others)))
    cards = "\n".join(persona_card(p) for p in others)
    recent = "\n".join(
        f"- {c.get('author', {}).get('nickname', c.get('nickname', '?'))}：{c.get('body', '')}"
        for c in (recent_comments or [])[-6:]
    )
    footprints_block = memory.footprints([p["nickname"] for p in others], k=2, width=40)
    hot = memory.hot_topics()
    user = (
        f"学生人设（回应者只能从这些人里选）：\n{cards}\n\n"
        + (f"{footprints_block}\n\n" if footprints_block else "")
        + (f"{hot}\n\n" if hot else "")
        + f"主题帖背景（楼主：{thread.get('nickname')}）：\n标题：{thread.get('title')}\n正文：{thread.get('body')}\n\n"
        f"帖子下最近的评论：\n{recent or '（暂无）'}\n\n"
        f"玩家「{target_comment.get('author', {}).get('nickname', '?')}」刚刚发的评论：\n"
        f"「{target_comment.get('body', '')}」\n\n"
        f"任务：写 4~6 条学生回应，像真实盖楼。先有人针对玩家这条评论说话（reply_to 填玩家昵称），"
        f"然后必须出现至少一组楼中楼：其他 AI 互相回复、接话、抬杠、歪楼（reply_to 填对方昵称），不要所有人都只回玩家。"
        f"不要泛泛评论主帖，不要每条都完整论证。长度长短不一（有的就一个字『草』『蹲』），符合各自人设口吻和表达缺陷。\n\n"
        f"输出 JSON：{{\"comments\": [{{\"nickname\": \"人设昵称\", \"body\": \"...\", \"reply_to\": \"玩家昵称或对方昵称\"}}]}}"
    )
    return chat(client, model, system, user, temperature, max_tokens=3000)


def generate_daily(client, model, personas, rules, temperature, n_threads=3) -> dict:
    """日常水帖：没有新闻/评选事件时，学生靠记忆和热帖自发聊校园日常。"""
    import random
    from datetime import datetime
    posters = random.sample(personas, min(n_threads, len(personas)))
    system = (
        "你是校园论坛的学生扮演系统。现在论坛没有新的评选或新闻事件，"
        "学生们自发地聊校园日常。输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules) + "\n\n" + humanize_block()
    )
    cards = "\n".join(persona_card(p) for p in posters)
    footprints_block = memory.footprints([p["nickname"] for p in posters], k=3, width=50)
    hot = memory.hot_topics()
    hour = datetime.now().hour
    user = (
        f"学生人设（本次发帖人，共 {len(posters)} 人）：\n{cards}\n\n"
        + (f"{footprints_block}\n\n" if footprints_block else "")
        + (f"{hot}\n\n" if hot else "")
        + f"现在是 {hour} 点。没有新的评选结果或新闻。\n\n"
        f"任务：写 {len(posters)} 个日常帖，按上述人设顺序每帖对应一位发帖人。"
        f"话题限于校园日常：食堂、考试、宿舍、社团、天气、通勤、最近的生活小事、各自的近况。"
        f"不要编造任何评选结果、奖项或新闻事实；可以延续各自近期足迹里的梗、话题和关系。"
        f"帖子要像真人随手发的：有标题，正文长短不一，符合人设的口癖和出没场景。\n\n"
        f"输出 JSON：{{\"threads\": [{{\"nickname\": \"人设昵称\", \"title\": \"...\", \"body\": \"...\"}}]}}"
    )
    return chat(client, model, system, user, temperature, max_tokens=5000)


def generate_snapshot(pack: dict, *, threads: int | None = None, env_path: str | Path | None = None, temperature: float = 1.15) -> dict:
    """Python API：输入事件简报，返回论坛快照 dict。"""
    if pack.get("schema_version") != 1:
        raise ValueError("简报 schema_version 必须是 1")
    public_text = str(pack.get("public_text") or "").strip()
    title = str(pack.get("title") or "").strip()
    if not public_text or not title:
        raise ValueError("简报必须包含 title 和 public_text")

    env = load_llm_env() if env_path is None else dotenv_values(str(env_path))
    client = OpenAI(api_key=env["LLM_API_KEY"], base_url=env["LLM_API_BASE"])
    model = env["LLM_MODEL_NAME"]
    personas_data = load_personas()
    personas, rules = personas_data["personas"], personas_data["rules"]
    hints = pack.get("hints") or {}
    n = threads or int(hints.get("threads") or 4)

    first = generate_threads(client, model, personas, rules, title, public_text, n, temperature)
    thread_list = first.get("threads") or []
    known = {p["nickname"] for p in personas}
    for t in thread_list:
        if t.get("nickname") not in known:
            print(f"警告：主题帖昵称 {t.get('nickname')!r} 不在人设中", file=sys.stderr)
        try:
            second = generate_comments(client, model, personas, rules, t, temperature)
            t["comments"] = [
                c for c in (second.get("comments") or []) if c.get("nickname") in known
            ]
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"警告：{t.get('nickname')} 的评论生成失败：{exc}", file=sys.stderr)
            t["comments"] = []

    return {
        "schema_version": 1,
        "type": "forum_snapshot",
        "meta": {
            "title": title,
            "source": hints.get("source") or "unknown",
            "source_detail": hints.get("volume") or "",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "personas_file": "personas.json",
        },
        "announcement": first.get("announcement"),
        "threads": thread_list,
    }


def save_snapshot(snapshot: dict, pack: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"snapshot-{datetime.now():%Y%m%d-%H%M%S}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render(snapshot), encoding="utf-8")
    # 供 server 的"重新生成"复用同一份简报
    (out_dir / "last_pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="事件简报 → 论坛快照")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", help="事件简报 JSON 路径")
    src.add_argument("--volume", help="校史馆卷宗 volume.md 路径（经 adapter 转换）")
    parser.add_argument("--threads", type=int, default=None, help="主题帖数量（默认 4，或 hints.threads）")
    parser.add_argument("--temperature", type=float, default=1.15)
    parser.add_argument("--env", default=str(WORKSPACE / "Any-Award-Backend/.env"))
    parser.add_argument("--out-dir", default=str(HERE / "output"))
    args = parser.parse_args()

    if args.volume:
        from adapters.museum_volume import pack_from_volume
        pack = pack_from_volume(Path(args.volume))
    else:
        pack = json.loads(Path(args.input).read_text(encoding="utf-8"))

    snapshot = generate_snapshot(pack, threads=args.threads, env_path=args.env, temperature=args.temperature)
    json_path, md_path = save_snapshot(snapshot, pack, Path(args.out_dir))
    print(f"已生成：{md_path}")
    print(f"JSON：{json_path}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
