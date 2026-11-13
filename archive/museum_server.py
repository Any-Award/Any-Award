#!/usr/bin/env python3
"""校史馆独立 Web 服务（早期 UI，纯标准库）。

  GET /                     馆藏目录（从各卷 session_meta.json 汇总）
  GET /volumes/<YYYY>/<dir>/  卷宗正文（volume.md 渲染为 HTML）

用法：
  python3 museum_server.py --museum-root museum [--port 8767]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

META_FORMAT = "anyaward-museum-meta"

CSS = """
:root{--paper:#fcfaf9;--ink:#141414;--red:#d0241c;--muted:#6b6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Source Han Sans","Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif}
.topbar{border-bottom:2px solid var(--ink);padding:18px 40px;display:flex;align-items:baseline;gap:20px}
.topbar h1{font-size:28px;letter-spacing:6px;margin:0;font-weight:normal}
.topbar h1 em{font-style:normal;color:var(--red)}
.topbar .sub{color:var(--muted);font-size:14px;letter-spacing:2px}
.topbar nav{margin-left:auto;display:flex;gap:16px}
a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--ink)}
a:hover{color:var(--red);border-color:var(--red)}
.wrap{max-width:1080px;margin:0 auto;padding:30px 24px 80px}
table.index{border-collapse:collapse;width:100%;font-size:17px}
table.index th,table.index td{border:1px solid var(--ink);padding:12px 14px;text-align:left}
table.index th{background:#f4f1ee;font-weight:normal;letter-spacing:2px}
h2.year{letter-spacing:4px;font-weight:normal;margin-top:36px}
.volume{background:var(--paper);border:2px solid var(--ink);padding:40px 52px;box-shadow:6px 6px 0 #e7e2dd}
.volume h1{font-size:26px;letter-spacing:4px;font-weight:normal;text-align:center}
.volume h2{font-size:22px;letter-spacing:2px;font-weight:normal;color:var(--red);text-align:center;border-bottom:3px solid var(--red);padding-bottom:14px;margin-bottom:28px}
.volume h3{font-size:21px;letter-spacing:3px;font-weight:normal;border-left:6px solid var(--red);padding-left:14px;margin-top:34px}
.volume p{line-height:1.95;font-size:17px}
.volume blockquote{margin:14px 0;padding:14px 20px;background:#f4f1ee;border-left:4px solid var(--ink);line-height:1.9;font-size:16px}
.volume blockquote strong{letter-spacing:1px}
.volume table{border-collapse:collapse;width:100%;font-size:15px;margin:16px 0}
.volume th,.volume td{border:1px solid var(--ink);padding:9px 12px;text-align:left;vertical-align:top;line-height:1.8}
.volume th{background:#f4f1ee;font-weight:normal;white-space:nowrap}
.volume hr{border:none;border-top:1px solid var(--ink);margin:26px 0}
.volume details{margin-top:18px;border:1px dashed var(--ink);padding:14px 20px}
.volume summary{cursor:pointer;letter-spacing:2px}
.volume ul{line-height:1.9}
.meta-line{color:var(--muted);font-size:14px;margin:0 0 24px}
.back{font-size:15px}
"""


# ---------------------------------------------------------------------------
# 卷宗 Markdown 子集 → HTML（只需覆盖 museum_writer 产出的语法）
# ---------------------------------------------------------------------------

def inline(text: str) -> str:
    s = html.escape(text, quote=True)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(<([^>]+)>\)", r'<a href="\2" target="_blank">\1</a>', s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    return s


def markdown_to_html(md: str) -> str:
    out: list[str] = []
    para: list[str] = []
    quote: list[str] = []
    table_rows: list[list[str]] = []
    in_table = False
    in_ul = False

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
            para = []

    def flush_quote() -> None:
        nonlocal quote
        if quote:
            out.append("<blockquote>" + "<br>".join(inline(x) for x in quote) + "</blockquote>")
            quote = []

    def flush_table() -> None:
        nonlocal table_rows, in_table
        if table_rows:
            parts = ["<table>"]
            for i, row in enumerate(table_rows):
                cell = "th" if i == 0 else "td"
                parts.append("<tr>" + "".join(f"<{cell}>{inline(c)}</{cell}>" for c in row) + "</tr>")
            parts.append("</table>")
            out.append("".join(parts))
        table_rows = []
        in_table = False

    def flush_all() -> None:
        flush_para()
        flush_quote()
        flush_table()

    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("<details>") or line.startswith("</details>") or "<summary>" in line:
            flush_all()
            out.append(line)
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_all()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        if line.strip() == "---":
            flush_all()
            out.append("<hr>")
            continue
        if line.startswith(">"):
            flush_para()
            flush_table()
            quote.append(line[1:].lstrip())
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_para()
            flush_quote()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r"[-: ]+", c or "-") for c in cells):
                continue  # 表格分隔行
            table_rows.append(cells)
            in_table = True
            continue
        if in_table:
            flush_table()
        if line.startswith("- "):
            flush_para()
            flush_quote()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if not line.strip():
            flush_all()
            continue
        para.append(line)
    flush_all()
    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def page(title: str, body: str, nav_right: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><div class="topbar"><h1><em>校史馆</em></h1>
<span class="sub">荣誉档案室 · 早期独立 UI</span>
<nav>{nav_right}<a href="http://localhost:8768/" target="_blank">树洞论坛 →</a></nav></div>
<div class="wrap">{body}</div></body></html>"""


def scan_volumes(museum_root: Path) -> list[dict]:
    entries = []
    for meta_path in sorted(museum_root.glob("volumes/*/*/session_meta.json")):
        try:
            m = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("format") != META_FORMAT:
            continue
        m["url"] = "/volumes/" + meta_path.parent.parent.name + "/" + meta_path.parent.name + "/"
        entries.append(m)
    entries.sort(key=lambda m: (m.get("year", 0), m.get("volume_no", "")))
    return entries


def catalog_page(museum_root: Path) -> str:
    entries = scan_volumes(museum_root)
    if not entries:
        body = "<p>馆内暂无卷宗。</p>"
    else:
        parts = []
        by_year: dict = {}
        for m in entries:
            by_year.setdefault(m.get("year"), []).append(m)
        for year in sorted(by_year, key=int):
            parts.append(f'<h2 class="year">{year} 年度</h2>')
            parts.append('<table class="index"><tr><th>卷宗号</th><th>奖项</th><th>获奖者</th><th>入馆日期</th><th>卷宗</th></tr>')
            for m in by_year[year]:
                winner = m.get("winner_display") or "（暂未裁定）"
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(str(m.get('doc_no', '')))}</td>"
                    f"<td>{html.escape(str(m.get('award_name', '')))}</td>"
                    f"<td>{html.escape(str(winner))}</td>"
                    f"<td>{html.escape(str(m.get('deposited_at', ''))[:10])}</td>"
                    f'<td><a href="{m["url"]}">展开卷宗</a></td>'
                    "</tr>"
                )
            parts.append("</table>")
        body = "\n".join(parts)
    body = '<p class="meta-line">凡入馆卷宗均按年度与入馆顺序编号；点击展开阅读。</p>' + body
    return page("校史馆 · 馆藏目录", body)


def make_handler(museum_root: Path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = unquote(urlsplit(self.path).path)
            if path == "/":
                self._html(200, catalog_page(museum_root))
                return
            m = re.fullmatch(r"/volumes/([^/]+)/([^/]+)/?", path)
            if m:
                volumes_root = (museum_root / "volumes").resolve()
                volume_path = (volumes_root / m.group(1) / m.group(2) / "volume.md").resolve()
                if not volume_path.is_relative_to(volumes_root) or not volume_path.is_file():
                    self._html(404, page("未找到", "<p>卷宗不存在。</p>"))
                    return
                md = volume_path.read_text(encoding="utf-8")
                body = '<p class="back"><a href="/">← 返回馆藏目录</a></p>'
                body += f'<article class="volume">{markdown_to_html(md)}</article>'
                self._html(200, page("校史馆 · 卷宗", body))
                return
            self._html(404, page("未找到", "<p>页面不存在。</p>"))

        def _html(self, code: int, content: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def log_message(self, fmt: str, *args) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="校史馆独立 Web 服务")
    parser.add_argument("--museum-root", default="museum")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Path(args.museum_root)))
    print(f"校史馆 UI: http://localhost:{args.port}/　馆藏：{Path(args.museum_root).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    sys.exit(main())
