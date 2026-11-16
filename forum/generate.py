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
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

from render import render
import memory
from lexicon import BANNED_COOC, BANNED_WORDS, COMPILED_FRAMES, banned_prompt_line
import relations

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


def humanize_block() -> str:
    return "\n".join([
        "【去AI味·硬清单（命中即失败，全文搜索必须为0）】",
        banned_prompt_line(),
        "禁用句式：『不是A，而是B』及一切翻案变体（『不是A，是B』『不叫A，叫B』『与其说A不如说B』『表面A实则B』『以为是A，结果B』『退一步讲』）、让步表态（『话虽如此』『这个我认，但…』『各有利弊』）、『X。就是这样。』碎片装深沉、自问自答、排比对仗。",
        "禁用标点：用冒号引出列举或解释、破折号——做停顿、双引号\"\"强调概念（要强调用「」或直接写）。",
        "禁用格式：加粗、小标题、bullet 罗列、编号论证（除非该人设的说话样板里就这么说）。",
        "【effort 分布】像真论坛：大部分评论是低 effort，一个字到一句话（草/蹲/+1/笑死/插眼/确实/啊这），四五条里才有一条稍微长点的看法。允许敷衍、词穷、答非所问、说一半不说了、纯表情。\n"
        "【短】能一句话说完就别写两句，能几个字就别写一句。真人灌水很短，长篇大论是 AI 味。",
        "【最高原则】最像，而不是最好。宁可说得烂、说得短、说得跑题，也不要说得正确又完整。别端着，别升华，别总结。",
        "【对照】AI味（禁止）：『首先…其次…最后…综上所述』式分点总结腔；『我认，但…』式先让步再翻案；结尾拔高升华。",
        "真人味（学这个）：『?? 我室友天天泡实验室结果连入围都没有 他回来一句话没说 我都不敢问…这奖到底看啥啊』『草』『蹲一个 顺便二食堂还有糖醋里脊吗』",
        "反对就这么说（学这个）：『标准里服务时长占30%这条谁定的 站出来』『你这数四舍五入也太狠了』——直接指具体处，不铺垫、不先夸。",
        "同意就这么说（学这个）：『两百人次是真的 我一学期问不了十次』——只接一个具体数，别总结、别升华。",
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
        "【口头禅是稀有品】标志句十条里最多冒一两次，一条里堆好几个=严重 AI 味。标志句不是你的身份，绝大多数时候你就是正常说话。"
    )
    return base + "\n" + extra


def update_relation_from_reply(client, model, a_nick: str, b_nick: str,
                               title: str, target_text: str, reply_text: str) -> None:
    """LLM 评价一次 AI→AI 回帖互动对关系的影响（±3 分），写 relationships.json。
    失败静默跳过——关系更新是增强，绝不能让发帖主路径失败。"""
    try:
        edge = relations.ensure(a_nick, b_nick)
        r = chat(client, model,
                 "你是校园论坛的关系观察员。根据一次回帖互动，评估它对两人关系的影响，只输出 JSON。",
                 f"帖子：《{title}》\n{b_nick} 的原话：「{str(target_text)[:80]}」\n"
                 f"{a_nick} 回复说：「{str(reply_text)[:80]}」\n"
                 f"当前关系强度 {edge['strength']}/100。\n"
                 "输出 JSON：{\"delta\": -3到3的整数, \"note\": \"不超过20字的关系现状描述\"}",
                 0.3, max_tokens=100)
        delta = max(-3, min(3, int(r.get("delta", 0))))
        relations.update(a_nick, b_nick, delta, str(r.get("note", "")))
    except Exception:
        pass


def persona_system(persona: dict, rules: list[str]) -> str:
    """单角色 system 提示：身份 + 动态状态/倒计时 + 语气 + 抽样样板 + 全局规则。

    评论/主题帖/日常帖三条路径共用（HANDOFF 缺陷2 的根治点：以前只有评论注入
    状态与倒计时，帖子批量生成不注入 → 同一角色帖子说"七十来天"、评论说"三十来天"）。
    标志句不在此提示里显式出现（style 已迁移到 catchphrase 字段），只经说话样板
    以约 1/6 的占比被随机抽到——结构上保证稀有，不靠指令压。"""
    import random
    examples = persona.get("examples") or []
    sample = random.sample(examples, min(4, len(examples))) if examples else []
    ex = "\n".join(f"  · {e}" for e in sample)
    state = memory.get_state(persona["nickname"]) or {}
    state_lines = ""
    if state.get("currently"):
        cur = str(state["currently"]).rstrip("。！？~")
        state_lines += f"（背景心情：你最近{cur}。这只是底色，不是每条都要提，别硬拐到它。）\n"
    cd = _countdown(persona)
    if cd:
        state_lines += cd + "\n"
    insight = str(state.get("insight") or "").strip()
    if insight and not _insight_is_slop(insight):   # 加载时补过滤:存量污染在这里兜底
        state_lines += f"（你最近的心事：{insight}，相关时才用）\n"
    return (
        f"你就是{persona['nickname']}（{persona['tag']}）。{persona['personality']}\n"
        + (state_lines + "\n" if state_lines else "")
        + f"语气：{persona['style']}\n"
        + (f"表达缺陷（自然体现就好，别每条都触发）：{persona.get('flaw', '')}\n"
           f"边界（不越线）：{persona.get('boundary', '')}\n")
        + f"说话样板（学腔调，别照抄）：\n{ex}\n\n"
        + "全体规则：\n" + rules_block(rules)
    )


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
    """场景门控后的发帖人抽样：深夜/凌晨角色仅在 23–7 点可被抽中；
    presence 字段(默认1.0)控制话痨/潜水差异(Step4)。"""
    from datetime import datetime
    hour = datetime.now().hour if hour is None else hour
    pool = [p for p in personas if not _is_night_owl(p) or _night_ok(hour)]
    if not pool:
        pool = list(personas)
    return _weighted_sample(pool, [float(p.get("presence", 1.0)) for p in pool], min(n, len(pool)))


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
        rel = str(p.get("relations", ""))
        w = (1.0 + (2 if op and op in rel else 0) + (2 if target_nick and target_nick in rel else 0))
        w *= float(p.get("presence", 1.0))
        weights.append(w)
    return _weighted_sample(pool, weights, min(n, len(pool)))


# 微情境动机池：让话从具体处境长出来，而非"写个有趣帖子"（斯坦福情境驱动）。
# 刻意全部是"处境/动作"、没有抽象立场——「你不太同意楼主」这类态度型动机是
# 让步句式的温床：模型拿到立场却不知道不同意什么，只能套预训练里的让步模板。
_MOTIVES = [
    "你正好经历过类似的事，想说说你那次后来怎么样了",
    "楼主有个说法跟你自己碰到的情况对不上，你想把你那点情况甩出来",
    "你觉得这事挺好笑，想乐一下",
    "你只是想随手水一句，懒得长篇大论",
    "你想起自己的一件小事，顺嘴一提",
    "你懒得回，但忍不住接个话",
    "你有个具体的小问题想问楼主或楼里人",
]

# 接其他评论者的话（形成对话链，而非都回楼主复读关键词）
# 接其他评论者的话（形成对话链，而非都回楼主复读关键词）。
# 旧版 7 条里 3 条是站队/补充——57% 概率抽到表态动作，「先夸一句…我认…但」
# 三连就是这么被结构性地生产出来的。现在全是处境化动作。
_REPLY_MOTIVES = [
    "他说的跟你经历的对不上，你直接说你那次的情况，不用客气",
    "他说到你心坎里了，你只想补一句自己身上对得上的事",
    "你接着他的话往下说",
    "你被他逗乐了，接个梗",
    "你想追问他一个细节",
    "他话里有处细节你正好知道，顺嘴丢出来",
    "你没细想，就是想应一声",
]

# 开主题帖的动机（帖子侧微情境；评论侧见 _MOTIVES/_REPLY_MOTIVES）
_THREAD_MOTIVES = [
    "你对这事有话要说，忍不住开一帖",
    "你想吐槽其中一点，专门发帖说一下",
    "你有个具体的小选择拿不准（选A还是B那种），想看看别人怎么选",
    "你发现公开信息里有两个数对不上（或一处说不通），想把它们贴出来问",
    "这事跟你有切身关系，你有点上头",
    "你只是想凑个热闹，水一帖",
]

# 无事件时的日常水帖动机
_DAILY_MOTIVES = [
    "你正好碰上点日常小事，想说说",
    "你无聊刷论坛，想找人说两句",
    "你有个小问题想问问大家",
    "你今天状态有点特别，想记一笔",
    "你想接着论坛里最近的气氛聊两句",
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


def _violations(body: str, budget: int | None, persona: dict | None = None) -> list[str]:
    """生成后定向检查（mk49 式双保险，纯正则、零额外成本）。命中才触发一次
    返工重试；词表与 humanize_block 同源于 lexicon，改一处两边同步。
    只做正则可判的事：书面禁词/罗列共现/翻案句/标志句堆砌/超预算——
    不可正则化的（修辞弧、金句）不在此查，避免误伤。"""
    issues: list[str] = []
    nb = re.sub(r"\s+", "", str(body))
    for w in BANNED_WORDS:
        if w in nb:
            issues.append(f"冒出书面腔禁词『{w}』")
    for a, b in BANNED_COOC:
        if a in nb and b in nb:
            issues.append(f"『{a}…{b}』罗列腔")
    for pat in COMPILED_FRAMES:
        m = pat.search(nb)
        if m:
            issues.append(f"撞上禁用句式『{m.group(0)}』（让步/翻案/假权威类，换个说法直接讲）")
    if persona:
        hits = sum(nb.count(re.sub(r"\s+", "", ph))
                   for ph in (persona.get("catchphrase") or []) if ph)
        if hits >= 2:
            issues.append("一条里堆了多个标志句（标志句一条最多冒一个）")
    if budget is not None and len(nb) > max(budget + 20, int(budget * 1.6)):
        issues.append(f"超长（{len(nb)}字，预算约{budget}字），砍到一半")
    return issues


def _rework(client, model, system: str, user: str, first: dict,
            issues: list[str], temperature: float, max_tokens: int) -> dict:
    """带违规说明的定向重试；只试一次，失败保留原稿（防死循环）。"""
    retry_user = user.rstrip() + (
        f"\n\n【返工】你刚才那条：「{str(first.get('body', ''))[:60]}」\n"
        f"问题：{'；'.join(issues)}。重写一条，格式同上，更短更随意。"
    )
    try:
        second = chat(client, model, system, retry_user, temperature, max_tokens)
    except (json.JSONDecodeError, KeyError):
        return first
    return second if str(second.get("body", "")).strip() else first


def generate_one_comment(client, model, persona, rules, situation, motive, mem_block, temperature, budget=None, about=None) -> dict:
    """单角色单调用：只喂该角色的情境 + 自己的记忆，打破"一个编剧写群戏"。
    映射斯坦福 v2 一次一句 + 情境模板 + 信息不对称。
    about = 本条互动对象（楼主或被接的评论者），用于注入关系提示与「记得上次」。"""
    if budget is None:
        budget = _length_budget()
    system = (
        persona_system(persona, rules)
        + "\n你在刷校园论坛，随手评论。不是写作文，不是表演角色。\n"
    )
    user = (
        f"【你刚看到的】{situation}\n\n"
        f"【你此刻的动机】{motive}\n\n"
        + (relations.hint_line(persona["nickname"], about) + "\n\n" if about else "")
        + (f"【旧账】你和{about}之前在帖子里交过手/搭过话——可以自然提一句上次的事，或接着那个话头，别装初见。\n\n"
           if about and memory.has_interaction(persona["nickname"], about) else "")
        + (f"【你自己的近期记忆】{mem_block}\n\n" if mem_block else "")
        + (
            "【钩子】先在 point 字段填对方这句话里你唯一想接的那个词/数字/事实（不超过10字，"
            "没有想接的就空字符串）。body 直接从你的事、你的问题、你的梗开始——"
            "第一句不许是评价对方的话（不许「说得对/有道理/我认/确实，但…」这类开场）。\n\n"
            if budget > 15
            else "【直接说】短回复不需要任何铺垫，直接从你的事、你的问题、你的梗开始——"
                 "第一句不许是评价对方的话（不许「说得对/有道理/我认/确实，但…」这类开场）。\n\n"
        )
        + f"【字数硬约束】body 不超过 {budget} 字。你在手机上随手回一句，越短越像真人，别长篇大论、别解释、别铺垫。\n\n"
        f"以{persona['nickname']}的口吻回一句。可回复楼主（reply_to=楼主）"
        f"或上面某条评论者（reply_to=其昵称）；懒得回就 skip=true。\n"
        + (
            '输出 JSON：{"point": "...", "body": "...", "reply_to": "楼主或昵称或null", "skip": false}\n\n'
            if budget > 15
            else '输出 JSON：{"body": "...", "reply_to": "楼主或昵称或null", "skip": false}\n\n'
        )
        + post_block(include_reply_example=False)
    )
    first = chat(client, model, system, user, temperature, max_tokens=256)
    issues = _violations(str(first.get("body", "")), budget, persona)
    if issues:
        first = _rework(client, model, system, user, first, issues, temperature, 256)
    return first


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


def _insight_is_slop(text: str) -> bool:
    """insight 金句/让步句过滤（动机见 refresh_one_state docstring）。帧命中、
    破折号、格言式收束词一律丢弃——states 每天注回每一次生成，污染成本远大于
    一条背景信息的收益，宁可错杀。"""
    if not text:
        return False
    for pat in COMPILED_FRAMES:
        if pat.search(text):
            return True
    if "——" in text or re.search(r"总会|无非|不过是|才是(真正|最)|更像", text):
        return True
    return False


def refresh_one_state(client, model, persona, today) -> dict:
    """每生一次调用：基于近期足迹重写 currently + 一条具体近况（斯坦福 revise_identity + reflect-lite）。

    insight 口径是「具体近况/心事」而非旧版「想明白的一件事」——后者是升华任务，
    产出金句后经 persona_system 每天注回该角色的每一次生成，构成自污染回路
    （「与其干等着生气，不如直接点名」就是这么进的 prompt）。生成后仍过
    _insight_is_slop 过滤，宁可错杀：insight 只是背景补充，丢了不影响生成。"""
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
        f"\"insight\": \"一条具体的近况或心事（要有具体的人/事/时间，像跟熟人随口说的；"
        f"不许是感悟、总结、格言；没有就空字符串）\"}}"
    )
    r = chat(client, model, system, user, temperature=0.9, max_tokens=400)
    insight = str(r.get("insight", "")).strip()
    if _insight_is_slop(insight):
        insight = ""
    return {
        "currently": str(r.get("currently", "")).strip() or old_currently,
        "insight": insight,
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


_ANNOUNCE_SYSTEM = (
    "你是校园论坛的值班管理员。根据给定的公开信息写一条置顶公告："
    "只转述公开信息里的事实，语气官方、克制、简短，不加评论、不玩梗。"
)


def generate_announcement(client, model, title, public_text, temperature) -> dict:
    """公告独立一次调用。管理员是机构口吻，不套学生人设，也不套去AI味清单
    （公文本就是书面腔，套了反而怪）。"""
    user = (
        f"话题：{title}\n\n"
        f"公开信息（你的全部事实来源）：\n---\n{public_text}\n---\n\n"
        "写一条公告。JSON：{\"title\": \"...\", \"body\": \"...\"}。"
        "正文不超过 90 字，只写事实（结果/对象/依据），"
        "材料支持时才加一句程序性收尾（如『后续不再就评审细节作说明』）。"
    )
    return chat(client, model, _ANNOUNCE_SYSTEM, user, min(temperature, 0.8), max_tokens=250)


def generate_one_thread(client, model, persona, rules, title, public_text,
                        taken_titles, temperature) -> dict:
    """主题帖单角色单调用，与 generate_one_comment 同构：情境+动机+自己的
    记忆/状态/倒计时+信息不对称（HANDOFF 缺陷2 的修复点）。"""
    import random
    motive = random.choice(_THREAD_MOTIVES)
    mem_block = memory.footprints([persona["nickname"]], k=3, width=50)
    hot = memory.hot_topics()
    taken = "、".join(f"《{t}》" for t in taken_titles[-4:])
    user = (
        f"【论坛正在讨论的事】{title}\n\n"
        f"【公开信息（你的全部事实来源）】\n---\n{public_text}\n---\n\n"
        f"【你此刻的动机】{motive}\n\n"
        + (f"【你自己的近期足迹】\n{mem_block}\n\n" if mem_block else "")
        + (f"{hot}\n\n" if hot else "")
        + (f"【别撞车】已经有人发了：{taken}。你要换个角度或换个话题点。\n\n" if taken else "")
        + f"以{persona['nickname']}的口吻发一帖。JSON：{{\"title\": \"...\", \"body\": \"...\"}}。"
        "标题像随手起的，可以不完整；正文不超过 120 字，像真人在手机上打的，别写成通稿。\n\n"
        + post_block(include_reply_example=False)
    )
    system = persona_system(persona, rules)
    first = chat(client, model, system, user, temperature, max_tokens=300)
    issues = _violations(str(first.get("body", "")), 120, persona)
    if issues:
        first = _rework(client, model, system, user, first, issues, temperature, 300)
    return first


def generate_threads(client, model, personas, rules, title, public_text, n_threads, temperature) -> dict:
    """公告 + 各主题帖独立生成。

    原实现是一次批量"编剧式"调用（全员人设卡拼盘 + max_tokens=6000），不注入
    动态状态/倒计时 → 同一角色帖子与评论里倒计时互相矛盾（HANDOFF 缺陷2）。
    现在公告 1 次 + 每帖 1 次，帖子与评论走同一套单角色提示。成本：每快照
    +N 次调用，相对评论侧的 20-30 次是小头。"""
    announcement = None
    try:
        announcement = generate_announcement(client, model, title, public_text, temperature)
    except (json.JSONDecodeError, KeyError) as exc:
        print(f"警告：公告生成失败：{exc}", file=sys.stderr)
    threads: list[dict] = []
    titles: list[str] = []
    for p in eligible_posters(personas, n_threads):
        try:
            t = generate_one_thread(client, model, p, rules, title, public_text, titles, temperature)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"警告：{p['nickname']} 主题帖生成失败：{exc}", file=sys.stderr)
            continue
        body = str(t.get("body", "")).strip()
        if not body:
            continue
        thread_title = str(t.get("title") or "").strip() or "（无题）"
        titles.append(thread_title)
        threads.append({"nickname": p["nickname"], "title": thread_title, "body": body})
    return {"announcement": announcement, "threads": threads}


def _comment_crowd() -> int:
    """每帖评论数分布：真论坛不是每帖都整齐 5-7 条——有冷帖也有热帖。
    基线审计显示 26 份快照每帖恒为 5-7 条，是结构均匀性 AI 味（HANDOFF 缺陷4
    的可量化版）。三角分布、冷帖常见、偶发独帖。"""
    import random
    return random.choices([1, 2, 3, 4, 5, 6, 7, 8],
                          weights=[3, 7, 13, 18, 21, 18, 12, 8])[0]


def generate_comments(client, model, personas, rules, thread, temperature) -> dict:
    """逐条独立生成。前两条必为顶楼（独立反应帖子），之后约一半顶楼一半楼中楼，
    形成"多人各自回帖子 + 部分楼中楼分支"的真实结构，而非单链。"""
    import random
    responders = pick_responders(personas, thread, n=_comment_crowd())
    comments = []
    for i, p in enumerate(responders):
        go_lou = (i >= 2) and bool(comments) and random.random() < 0.55
        if go_lou:
            targets = comments[-4:]
            # 目标按关系强度加权——旧版只加权"谁被抽来",最后一步均匀随机,
            # 关系对同框率的提升实测只剩 1.08-1.33 倍 ≈ 随机
            weights = [relations.weight(p["nickname"], t.get("nickname", "")) for t in targets]
            target = random.choices(targets, weights=weights, k=1)[0]
            situation = (f"帖子《{thread.get('title', '')}》（楼主说：{str(thread.get('body', ''))[:80]}）的评论区。\n"
                         f"你刚看到 {target['nickname']} 说：「{target['body']}」")
            motive = random.choice(_REPLY_MOTIVES)
            forced_reply = target["nickname"]
            about = target["nickname"]
        else:
            # 顶楼视野: 本批已发评论优先, 否则帖内既有评论(玩家互动场景)——修盲选
            prior = comments or thread.get("comments") or []
            situation, motive = comment_situation(thread, prior[-2:])
            forced_reply = None
            about = thread.get("nickname", "")
        mem_block = memory.footprints([p["nickname"]], k=3, width=50)
        try:
            r = generate_one_comment(client, model, p, rules, situation, motive, mem_block, temperature, about=about)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"警告：{p['nickname']} 评论生成失败丢弃：{exc}", file=sys.stderr)
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
            r = generate_one_comment(client, model, p, rules, situation, motive, mem_block, temperature, about=player_nick)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"警告：{p['nickname']} 回应玩家评论生成失败丢弃：{exc}", file=sys.stderr)
            continue
        if r.get("skip"):
            continue
        body = str(r.get("body", "")).strip()
        if not body:
            continue
        comments.append({"nickname": p["nickname"], "body": body, "reply_to": r.get("reply_to") or player_nick})
    return {"comments": comments}


def generate_one_daily(client, model, persona, rules, hour, taken_titles, temperature) -> dict:
    """日常水帖单角色单调用（原为批量调用、不注入状态/倒计时，缺陷2 同源）。"""
    import random
    motive = random.choice(_DAILY_MOTIVES)
    mem_block = memory.footprints([persona["nickname"]], k=3, width=50)
    hot = memory.hot_topics()
    taken = "、".join(f"《{t}》" for t in taken_titles[-4:])
    user = (
        f"【现在】{hour} 点，论坛没有新的评选或新闻。\n\n"
        f"【你此刻的动机】{motive}\n\n"
        + (f"【你自己的近期足迹】\n{mem_block}\n\n" if mem_block else "")
        + (f"{hot}\n\n" if hot else "")
        + (f"【别撞车】已经有人发了：{taken}。你聊点别的。\n\n" if taken else "")
        + f"以{persona['nickname']}的口吻发一帖。JSON：{{\"title\": \"...\", \"body\": \"...\"}}。"
        "话题只限校园日常：食堂、上课、考试、作业、宿舍、社团、天气、通勤、各自近况。"
        "不要编造任何评选结果、奖项或新闻事实。标题像随手起的；正文不超过 100 字。\n\n"
        + post_block(include_reply_example=False)
    )
    system = persona_system(persona, rules)
    first = chat(client, model, system, user, temperature, max_tokens=300)
    issues = _violations(str(first.get("body", "")), 100, persona)
    if issues:
        first = _rework(client, model, system, user, first, issues, temperature, 300)
    return first


def generate_daily(client, model, personas, rules, temperature, n_threads=3) -> dict:
    """日常水帖：逐帖独立生成（保持原签名，server /daily 直接兼容）。"""
    from datetime import datetime
    ensure_fresh_states(client, model, personas)
    hour = datetime.now().hour
    threads: list[dict] = []
    titles: list[str] = []
    for p in eligible_posters(personas, n_threads, hour=hour):
        try:
            t = generate_one_daily(client, model, p, rules, hour, titles, temperature)
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"警告：{p['nickname']} 日常帖生成失败：{exc}", file=sys.stderr)
            continue
        body = str(t.get("body", "")).strip()
        if not body:
            continue
        thread_title = str(t.get("title") or "").strip() or "（无题）"
        titles.append(thread_title)
        threads.append({"nickname": p["nickname"], "title": thread_title, "body": body})
    return {"threads": threads}


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
