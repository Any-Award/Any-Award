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
    "口吻认真、可以带黑色幽默；允许荒诞，但要用最正经的笔法写。"
    "每条新闻都要有争议点或趣味点，能引出不同立场学生的讨论，不要清一色教育新闻。"
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
        f"生成 {count} 条新闻，类别从这些里分配：{CATEGORIES}（校园日常和网络热点也要占相当比例）。\n"
        f"每条给出标题、正文（3~6 句）、类别、来源（从 {SOURCES} 中选）。\n"
        f"标题像大学生会转发的那种，允许略带夸张但正文必须自洽。\n"
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
