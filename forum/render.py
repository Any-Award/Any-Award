"""论坛快照 → 快照 Markdown 渲染（输出形态之一；UI 直接读 JSON，不经过本模块）。"""


def _time_label(clock: int) -> str:
    day = "次日 " if clock >= 24 * 60 else "今天 "
    h, m = divmod(clock % (24 * 60), 60)
    return f"{day}{h:02d}:{m:02d}"


def render(snapshot: dict) -> str:
    meta = snapshot["meta"]
    lines = [
        "# 华清大学校园论坛 · 舆论快照",
        "",
        f"> 话题：{meta.get('title', '')}　｜　生成时间：{meta.get('generated_at', '')[:16]}",
        "> 本快照由学生扮演系统生成，帖子只代表论坛内学生的发言。",
        "",
    ]
    ann = snapshot.get("announcement")
    if ann:
        body = ann.get("body", "")
        if body.rstrip().endswith("论坛管理员"):
            body = body.rstrip().removesuffix("论坛管理员").rstrip()
        lines += [
            f"## [置顶][公告] {ann.get('title', '')}",
            "",
            body,
            "—— 论坛管理员",
            "",
            "---",
            "",
        ]
    clock = 21 * 60 + 3  # 论坛水帖高峰：晚上九点起
    for i, t in enumerate(snapshot.get("threads") or [], 1):
        lines += [
            f"### 【{i}】{t.get('title', '')}",
            "",
            f"**{t.get('nickname', '?')}**　{_time_label(clock)}",
            "",
            t.get("body", ""),
            "",
        ]
        clock += 17 + 13 * i
        for floor, c in enumerate(t.get("comments") or [], 2):
            lines += [f"> **{floor}楼 · {c.get('nickname', '?')}**：{c.get('body', '')}", ""]
            clock += 7 + 5 * floor
        lines += ["---", ""]
    return "\n".join(lines).rstrip() + "\n"
