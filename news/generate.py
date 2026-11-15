#!/usr/bin/env python3
"""新闻生成器：LLM 生成校园世界观下的虚构新闻，可选推送论坛发酵。

  生成：Any-Award-Backend/.venv/bin/python news/generate.py --count 3
  并推送论坛：加 --post-to-forum（每条新闻作为事件简报 POST 给 forum/server.py）

输出：news/output/news-<时间戳>.json / .md；推送时论坛自动围绕新闻产生帖子。

口径：全部为游戏内虚构消息，不影射真实机构、真实政策、真实人物；
事实约束在下游论坛侧生效（学生只能依据新闻正文说话）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent

CATEGORIES = ["校园动态", "教育议题", "网络热点", "隔壁大学与学界"]
SOURCES = ["校园快讯", "树洞晚报", "隔壁观察", "教育评论"]

SYSTEM = (
    "你是校园世界的虚构新闻编辑部，为一款校园沙盒游戏生成游戏内新闻素材。"
    "这些新闻会被学生论坛引用讨论，要求真实感强、有讨论空间。"
    "所有新闻必须是游戏内虚构消息：不影射真实大学、真实政策文件、真实人物、真实机构。"
    "像校园墙/树洞的吐槽帖，不是新闻联播：站在某个具体学生的视角说，可以片面、带情绪、八卦、夸张，"
    "不要『有人支持有人反对、各打五十大板』的平衡报道。允许荒诞，带黑色幽默。"
    "每条都要有槽点或趣味点，能让学生吵起来或玩梗，不要清一色教育新闻。"
    "【分类别要求】校园动态：必须有具体地点+人物+数字；教育议题：必须有明确槽点或争议；"
    "网络热点：必须有梗或情绪共鸣点；隔壁大学与学界：必须有可对比的做法或成果。"
    "【具体细节】每条正文必须包含：一个具体数字、一个具体地点或对象、一句直接引语（某人说的话）。空泛概述不合格。"
    "【讨论点】每条都要埋一个能让学生吵起来或玩梗的点（争议/反差/槽点），并在正文里自然呈现。"
)

EXAMPLES = (
    "【好新闻范例（学这个的具体感和讨论点，别照抄内容）】\n"
    "范例1（校园动态）《三食堂麻辣烫窗口推出『背论文致谢免费加料』，排队长达三十米》：\n"
    "今日中午，三食堂麻辣烫窗口贴出告示：凡能背诵一段自己论文致谢的同学，可免费加一份鹌鹑蛋。"
    "窗口前排起约三十米长队，有同学手持打印稿念念有词。一位排队的大四学生说：『我致谢写了八百字，比论文正文还长。』"
    "老板表示此举是为『鼓励学术感恩，顺便清库存』。已有三人因致谢内容雷同被要求重背。\n"
    "范例2（隔壁大学）《隔壁大学『早起打卡换早餐』，我校学生酸了：建议直接打钱》：\n"
    "隔壁大学宣布连续七天早六点半前到操场打卡可兑十元早餐券。我校一个熬夜党看完直接破防：『六点半打卡？我四点半才睡，这早餐给我我也吃不上。』"
    "底下全是在酸『建议我校直接学习后半句——打钱』。据该校学生会统计，打卡失败原因第一名是『闹钟响了但灵魂没醒』，我校学生表示过于真实。\n"
)


def load_llm_env() -> dict:
    """读取 LLM 配置，密钥不落项目（同 forum/generate.py 的约定）。

    优先级：环境变量 > 项目 .env（非空值）> 项目外私有密钥文件 ~/.anyaward-secrets.env。
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


def generate_news(client: OpenAI, model: str, count: int, temperature: float) -> list[dict]:
    user = (
        f"{EXAMPLES}\n"
        f"生成 {count} 条新闻，类别从这些里分配：{CATEGORIES}（校园日常和网络热点也要占相当比例）。\n"
        f"每条给出标题、正文（3~6 句）、类别、来源（从 {SOURCES} 中选）。\n"
        f"标题像大学生会转发的那种，允许略带夸张但正文必须自洽。\n"
        f"务必满足系统提示里的分类别要求、具体细节（数字+地点/对象+引语）和讨论点。\n"
        f"输出 JSON：{{\"items\": [{{\"title\": \"...\", \"body\": \"...\", \"category\": \"...\", \"source\": \"...\"}}]}}"
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=5000,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content).get("items") or []


def render_md(items: list[dict], generated_at: str) -> str:
    lines = ["# 校园新闻 · 虚构素材", "", f"> 生成时间：{generated_at}　｜　全部为游戏内虚构消息", ""]
    for i, item in enumerate(items, 1):
        lines += [
            f"## {i}. 【{item.get('category', '')}】{item.get('title', '')}",
            "",
            item.get("body", ""),
            "",
            f"—— 来源：{item.get('source', '')}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def pack_from_item(item: dict) -> dict:
    return {
        "schema_version": 1,
        "title": item.get("title", ""),
        "public_text": (
            f"【{item.get('category', '')}】{item.get('title', '')}\n\n"
            f"{item.get('body', '')}\n\n—— 来源：{item.get('source', '')}（游戏内虚构消息）"
        ),
        "hints": {"source": "news", "threads": 3},
    }


def post_to_forum(pack: dict, forum_url: str) -> bool:
    req = urllib.request.Request(
        forum_url,
        data=json.dumps(pack, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status == 200
    except Exception as exc:  # noqa: BLE001
        print(f"推送论坛失败：{exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="校园虚构新闻生成器")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=1.1)
    parser.add_argument("--env", default=str(WORKSPACE / "Any-Award-Backend/.env"))
    parser.add_argument("--post-to-forum", action="store_true", help="每条新闻作为简报推送论坛")
    parser.add_argument("--forum-url", default="http://localhost:8768/generate")
    args = parser.parse_args()

    env = load_llm_env()
    client = OpenAI(api_key=env["LLM_API_KEY"], base_url=env["LLM_API_BASE"])
    items = generate_news(client, env["LLM_MODEL_NAME"], args.count, args.temperature)

    out_dir = HERE / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    stem = f"news-{datetime.now():%Y%m%d-%H%M%S}"
    (out_dir / f"{stem}.json").write_text(json.dumps({"generated_at": ts, "items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(render_md(items, ts), encoding="utf-8")
    print(f"已生成 {len(items)} 条新闻：{out_dir / (stem + '.md')}")

    if args.post_to_forum:
        for item in items:
            ok = post_to_forum(pack_from_item(item), args.forum_url)
            print(f"  论坛发酵《{item.get('title', '')[:24]}》：{'OK' if ok else '失败'}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
