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
from lexicon import banned_prompt_line

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
        banned_prompt_line(),
        "禁用句式：『不是A，而是B』翻案句、『不是A…不是B…是C』否定铺垫、『X。就是这样。』碎片装深沉、自问自答、排比对仗。",
        "禁用标点：用冒号引出列举或解释、破折号——做停顿、双引号\"\"强调概念（要强调用「」或直接写）。",
        "禁用格式：加粗、小标题、bullet 罗列、编号论证（除非该人设的说话样板里就这么说）。",
        "【effort 分布】像真论坛：大部分评论是低 effort，一个字到一句话（草/蹲/+1/笑死/插眼/确实/啊这），四五条里才有一条稍微长点的看法。允许敷衍、词穷、答非所问、说一半不说了、纯表情。\n"
        "【短】能一句话说完就别写两句，能几个字就别写一句。真人灌水很短，长篇大论是 AI 味。",
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


def post_block(include_reply_example: bool = True) -> str:
    """压轴风格指令（SillyTavern post_history_instructions）：复用 humanize_block，
    追加信息不对称（Stanford 对话 prompt）与单角色口吻重申。放在 user 末尾、生成点之前。"""
    base = humanize_block()
    if not include_reply_example:
        base = base.split("【盖楼范例】")[0].rstrip()
    extra = (
        "【信息不对称】你只知道本帖公开内容和你自己的近期足迹，不知道别人未公开的想法或材料里没写的事。\n"
        "【单角色口吻】每条只以对应昵称的口吻写，串味（像别的角色或像 AI 客服）即失败。\n"
        "【禁修辞弧】不要『个人经历→感悟升华→安慰/号召』的闭环，不要结尾给人生道理或安慰号召；话可以说一半、没结论、跑题。\n"
        "【禁金句】不要工整对仗的格言警句（如『匿名本来让人敢说，可也让人敢伤人』这种）。\n"
        "【口头禅是稀有品】你的标志句（如蚌/哥/先夸一句/没数我不说）十条里最多冒一两次，绝大多数时候就是普通说话；一条里堆好几个标志句=严重 AI 味。标志句不是你的身份。\n"
        "【接话不接词】回应别人时接他的意思，别复读他或楼主的原词；从你自己的经历和立场出发说。"
    )
    return base + "\n" + extra


def _is_night_owl(p: dict) -> bool:
    # 仅"严格夜行"角色受时段门控（白天从不出现/只在深夜/凌晨出没）；
    # "深夜也在线""深夜情感帖必到"这类只是兼在深夜，不算夜猫子。
    scene = str(p.get("scene", ""))
    return ("白天从不" in scene) or ("只在深夜" in scene) or ("凌晨出没" in scene)


def _night_ok(hour: int) -> bool:
    return hour >= 23 or hour < 7


def _weighted_sample(pool: list, weights: list, k: int) -> list:
    """加权无放回抽样。"""
    import random
    pool, weights = list(pool), list(weights)
    out = []
    for _ in range(min(k, len(pool))):
        chosen = random.choices(pool, weights=weights, k=1)[0]
        idx = pool.index(chosen)
        out.append(chosen)
        pool.pop(idx)
        weights.pop(idx)
    return out


def eligible_posters(personas: list, n: int, hour: int | None = None) -> list:
    """场景门控后的发帖人抽样：深夜/凌晨角色仅在 23–7 点可被抽中。"""
    from datetime import datetime
    hour = datetime.now().hour if hour is None else hour
    pool = [p for p in personas if not _is_night_owl(p) or _night_ok(hour)]
    if not pool:
        pool = list(personas)
    return _weighted_sample(pool, [1.0] * len(pool), min(n, len(pool)))


def pick_responders(personas: list, thread: dict, target_comment: dict | None = None,
                    n: int = 6, hour: int | None = None) -> list:
    """场景门控 + 关系加权的回应者抽样（廉价版 Stanford decide_to_talk）。
    relations 文本含楼主或目标评论者昵称者权重 +2，让互怼/饭搭子更易同框。"""
    from datetime import datetime
    hour = datetime.now().hour if hour is None else hour
    op = thread.get("nickname", "")
    target_nick = (target_comment.get("author") or {}).get("nickname", "") if target_comment else ""
    pool = [p for p in personas
            if p["nickname"] != op and (not _is_night_owl(p) or _night_ok(hour))]
    if not pool:
        pool = [p for p in personas if p["nickname"] != op]
    weights = []
    for p in pool:
        w = 1.0
        rel = str(p.get("relations", ""))
        if op and op in rel:
            w += 2
        if target_nick and target_nick in rel:
            w += 2
        weights.append(w)
    return _weighted_sample(pool, weights, min(n, len(pool)))


# 微情境动机池：让话从具体处境长出来，而非"写个有趣帖子"（斯坦福情境驱动）
_MOTIVES = [
    "你正好经历过类似的事，想说两句",
    "你不太同意楼主，想抬个杠",
    "你觉得这事挺好笑，想乐一下",
    "你只是想随手水一句，懒得长篇大论",
    "你想起自己的一件事，顺嘴一提",
    "你懒得回，但忍不住接个话",
    "你有点感同身受，想说点实在的",
]

# 接其他评论者的话（形成对话链，而非都回楼主复读关键词）
_REPLY_MOTIVES = [
    "你不同意他说的，想反驳一句",
    "你挺同意他，再补一个相关的点",
    "你接着他的话往下说",
    "你觉得他说得不对，怼一下",
    "你被他逗乐了，接个梗",
    "你想追问他一个细节",
    "你帮他补充一个他没说的点",
]


def comment_situation(thread: dict, prior_comments: list) -> tuple:
    """构造"你刚看到的"微情境：本帖 + 已生成评论（供楼中楼）+ 随机动机。"""
    import random
    saw = f"帖子《{thread.get('title', '')}》：{str(thread.get('body', ''))[:200]}"
    if prior_comments:
        saw += "\n你刚看到这几条评论：\n" + "\n".join(
            f"  {c.get('nickname', '?')}：{str(c.get('body', ''))[:80]}"
            for c in prior_comments[-3:]
        )
    return saw, random.choice(_MOTIVES)


def _length_budget() -> int:
    """结构化字数预算：多数极短，少数短，偶尔稍长（真论坛的回复长度分布）。"""
    import random
    r = random.random()
    if r < 0.6:
        return random.randint(5, 15)    # 极短：草/笑死/蹲/确实
    if r < 0.9:
        return random.randint(16, 40)   # 短：一句话
    return random.randint(41, 80)       # 稍长：一小段看法


def generate_one_comment(client, model, persona, rules, situation, motive, mem_block, temperature, budget=None) -> dict:
    """单角色单调用：只喂该角色的情境 + 自己的记忆，打破"一个编剧写群戏"。
    映射斯坦福 v2 一次一句 + 情境模板 + 信息不对称。"""
    if budget is None:
        budget = _length_budget()
    examples = persona.get("examples") or []
    import random
    sample = random.sample(examples, min(4, len(examples))) if examples else []
    ex = "\n".join(f"  · {e}" for e in sample)
    state = memory.get_state(persona["nickname"]) or {}
    state_lines = ""
    if state.get("currently"):
        state_lines += f"（背景心情：你最近{state['currently']}。这只是底色，不是每条都要提，别硬拐到它。）\n"
    cd = _countdown(persona)
    if cd:
        state_lines += cd + "\n"
    if state.get("insight"):
        state_lines += f"（你最近想明白的事：{state['insight']}，相关时才用）\n"
    system = (
        f"你就是{persona['nickname']}（{persona['tag']}）。{persona['personality']}\n"
        + (state_lines + "\n" if state_lines else "")
        + f"语气：{persona['style']}\n"
        f"说话样板（学腔调，别照抄）：\n{ex}\n"
        f"你在刷校园论坛，随手评论。不是写作文，不是表演角色。\n\n"
        "全体规则：\n" + rules_block(rules)
    )
    user = (
        f"【你刚看到的】{situation}\n\n"
        f"【你此刻的动机】{motive}\n\n"
        + (f"【你自己的近期记忆】{mem_block}\n\n" if mem_block else "")
        + "【信息不对称】你只知道上面这些和你自己的记忆，不知道别人没公开的想法。\n\n"
        "【就事论事】紧扣对方这句话的具体内容来回应，别硬拐去说自己的事、别复读原词；你的背景心情只是底色，不必每条都提。\n\n"
        f"【字数硬约束】这条回复不超过 {budget} 字。你在手机上随手回一句，越短越像真人，别长篇大论、别解释、别铺垫。\n\n"
        f"以{persona['nickname']}的口吻回一句。可回复楼主（reply_to=楼主）"
        f"或上面某条评论者（reply_to=其昵称）；懒得回就 skip=true。\n"
        f"输出 JSON：{{\"body\": \"...\", \"reply_to\": \"楼主或昵称或null\", \"skip\": false}}\n\n"
        + post_block(include_reply_example=False)
    )
    return chat(client, model, system, user, temperature, max_tokens=200)


def _countdown(persona: dict) -> str:
    """考研倒计时：存考试日期、每次现算天数（根除硬编码不一致）。"""
    exam = persona.get("exam_date")
    if not exam:
        return ""
    from datetime import date
    try:
        y, m, d = map(int, str(exam).split("-"))
        days = (date(y, m, d) - date.today()).days
        return f"距离考研还有{days}天" if days >= 0 else "考研刚结束"
    except (ValueError, AttributeError):
        return ""


def refresh_one_state(client, model, persona, today) -> dict:
    """每生一次调用：基于近期足迹重写 currently + 一条洞察（斯坦福 revise_identity + reflect-lite）。"""
    nick = persona["nickname"]
    footprints = memory.footprints([nick], k=8, width=80)
    old = memory.get_state(nick) or {}
    old_currently = old.get("currently") or persona.get("personality", "")
    system = (
        f"你是{nick}（{persona['tag']}）。{persona['personality']}\n"
        f"根据你最近在论坛的足迹，更新你今天的当前状态。状态是具体的心情/近况，口语化，不是人设介绍。"
    )
    user = (
        f"你昨天的状态：{old_currently}\n"
        f"你最近的论坛足迹：\n{footprints or '（最近没说话）'}\n"
        f"今天是 {today}。\n\n"
        f"输出 JSON：{{\"currently\": \"一句话当前状态/心情（具体、口语）\", "
        f"\"insight\": \"你最近想明白的一件事（没有就空字符串）\"}}"
    )
    r = chat(client, model, system, user, temperature=0.9, max_tokens=400)
    return {
        "currently": str(r.get("currently", "")).strip() or old_currently,
        "insight": str(r.get("insight", "")).strip(),
        "updated_at": today,
    }


def ensure_fresh_states(client, model, personas) -> None:
    """按日期缓存：每生每天最多刷新一次状态。"""
    from datetime import date
    today = date.today().isoformat()
    states = memory.load_states()
    changed = False
    for p in personas:
        nick = p["nickname"]
        st = states.get(nick)
        if st and st.get("updated_at") == today:
            continue
        try:
            states[nick] = refresh_one_state(client, model, p, today)
            changed = True
        except (json.JSONDecodeError, KeyError):
            continue
    if changed:
        memory.save_states(states)


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
    posters = eligible_posters(personas, n_threads)
    system = (
        "你是校园论坛的学生扮演系统。你根据给定的公开信息和一批学生人设，"
        "以不同学生的口吻撰写论坛帖子。输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules)
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
        f"帖子要像真的帖子：有标题，正文控制在 120 字以内，像随手发的，别写长文。\n\n"
        f"输出 JSON：{{\"announcement\": {{\"title\": \"...\", \"body\": \"...\"}}, "
        f"\"threads\": [{{\"nickname\": \"人设昵称\", \"title\": \"...\", \"body\": \"...\"}}]}}\n\n"
        + post_block(include_reply_example=False)
    )
    return chat(client, model, system, user, temperature, max_tokens=6000)


def generate_comments(client, model, personas, rules, thread, temperature) -> dict:
    """逐条独立生成。前两条必为顶楼（独立反应帖子），之后约一半顶楼一半楼中楼，
    形成"多人各自回帖子 + 部分楼中楼分支"的真实结构，而非单链。"""
    import random
    responders = pick_responders(personas, thread, n=random.randint(5, 7))
    comments = []
    for i, p in enumerate(responders):
        go_lou = (i >= 2) and bool(comments) and random.random() < 0.55
        if go_lou:
            target = random.choice(comments[-4:])
            situation = (f"帖子《{thread.get('title', '')}》（楼主说：{str(thread.get('body', ''))[:80]}）的评论区。\n"
                         f"你刚看到 {target['nickname']} 说：「{target['body']}」")
            motive = random.choice(_REPLY_MOTIVES)
            forced_reply = target["nickname"]
        else:
            situation, motive = comment_situation(thread, [])  # 只看帖子，独立反应
            forced_reply = None
        mem_block = memory.footprints([p["nickname"]], k=3, width=50)
        try:
            r = generate_one_comment(client, model, p, rules, situation, motive, mem_block, temperature)
        except (json.JSONDecodeError, KeyError):
            continue
        if r.get("skip"):
            continue
        body = str(r.get("body", "")).strip()
        if not body:
            continue
        reply_to = forced_reply if forced_reply else (r.get("reply_to") or "楼主")
        comments.append({"nickname": p["nickname"], "body": body, "reply_to": reply_to})
    return {"comments": comments}


def generate_replies_to_comment(client, model, personas, rules, thread, target_comment, recent_comments, temperature) -> dict:
    """针对玩家具体评论，逐条独立生成回应（每条只喂该角色情境+自己的记忆）。"""
    import random
    responders = pick_responders(personas, thread, target_comment=target_comment, n=random.randint(3, 5))
    player_nick = (target_comment.get("author") or {}).get("nickname", "玩家")
    base = f"帖子《{thread.get('title', '')}》：{str(thread.get('body', ''))[:150]}"
    if recent_comments:
        base += "\n最近的评论：\n" + "\n".join(
            f"  {c.get('author', {}).get('nickname', '?')}：{str(c.get('body', ''))[:60]}"
            for c in recent_comments[-4:]
        )
    comments = []
    for p in responders:
        situation = base + f"\n玩家「{player_nick}」刚评论：「{target_comment.get('body', '')}」"
        motive = random.choice(_MOTIVES)
        mem_block = memory.footprints([p["nickname"]], k=3, width=50)
        try:
            r = generate_one_comment(client, model, p, rules, situation, motive, mem_block, temperature)
        except (json.JSONDecodeError, KeyError):
            continue
        if r.get("skip"):
            continue
        body = str(r.get("body", "")).strip()
        if not body:
            continue
        comments.append({"nickname": p["nickname"], "body": body, "reply_to": r.get("reply_to") or player_nick})
    return {"comments": comments}


def generate_daily(client, model, personas, rules, temperature, n_threads=3) -> dict:
    """日常水帖：没有新闻/评选事件时，学生靠记忆和热帖自发聊校园日常。"""
    from datetime import datetime
    ensure_fresh_states(client, model, personas)
    hour = datetime.now().hour
    posters = eligible_posters(personas, n_threads, hour=hour)
    system = (
        "你是校园论坛的学生扮演系统。现在论坛没有新的评选或新闻事件，"
        "学生们自发地聊校园日常。输出严格遵守用户要求的 JSON 格式。\n\n"
        "全体规则：\n" + rules_block(rules)
    )
    cards = "\n".join(persona_card(p) for p in posters)
    footprints_block = memory.footprints([p["nickname"] for p in posters], k=3, width=50)
    hot = memory.hot_topics()
    user = (
        f"学生人设（本次发帖人，共 {len(posters)} 人）：\n{cards}\n\n"
        + (f"{footprints_block}\n\n" if footprints_block else "")
        + (f"{hot}\n\n" if hot else "")
        + f"现在是 {hour} 点。没有新的评选结果或新闻。\n\n"
        f"任务：写 {len(posters)} 个日常帖，按上述人设顺序每帖对应一位发帖人。"
        f"话题限于校园日常：食堂、考试、宿舍、社团、天气、通勤、最近的生活小事、各自的近况。"
        f"不要编造任何评选结果、奖项或新闻事实；可以延续各自近期足迹里的梗、话题和关系。"
        f"帖子要像真人随手发的：有标题，正文控制在 100 字以内，符合人设的口癖和出没场景，别写长文。\n\n"
        f"输出 JSON：{{\"threads\": [{{\"nickname\": \"人设昵称\", \"title\": \"...\", \"body\": \"...\"}}]}}\n\n"
        + post_block(include_reply_example=False)
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

    ensure_fresh_states(client, model, personas)
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
    parser.add_argument("--env", default=None, help="LLM 配置 .env 路径；缺省走 load_llm_env() 回退（环境变量>项目.env>私有密钥文件）")
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
