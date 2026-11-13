#!/usr/bin/env python3
"""采集 adapter：校史馆卷宗 volume.md → 论坛事件简报（input pack）。

论坛系统本身不依赖校史馆；本 adapter 是"校史馆作为调用方"的转换入口。
用法：
  python3 adapters/museum_volume.py --volume <volume.md> -o pack.json
"""

import argparse
import json
import re
import sys
from pathlib import Path


def pack_from_volume(volume_path: Path) -> dict:
    text = Path(volume_path).read_text(encoding="utf-8")
    m = re.search(r"——「(.+?)」", text)
    award = m.group(1) if m else ""
    # 附录（报名材料原文）不进论坛素材；内部纪实章节保留给 prompt 里的"学生不可见"规则处理
    body = text.split("<details>")[0].rstrip()
    return {
        "schema_version": 1,
        "title": f"{award}评选相关舆情" if award else Path(volume_path).parent.name,
        "public_text": body,
        "hints": {
            "source": "museum_volume",
            "volume": str(Path(volume_path).resolve()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="volume.md → 论坛输入简报")
    parser.add_argument("--volume", required=True)
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    pack = pack_from_volume(Path(args.volume))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成简报：{out}")


if __name__ == "__main__":
    sys.exit(main())
