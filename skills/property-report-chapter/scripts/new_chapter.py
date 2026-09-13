#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""楼盘报告章节脚手架：从模板生成一个章节 HTML 骨架。

用法：
    python new_chapter.py --out "C:/path/to/星洲文昌府户型分析.html" \
                          --chapter floor-type \
                          --project "星洲文昌府" \
                          --city "成都" \
                          [--title "户型产品分析"] \
                          [--force]

章节类型（--chapter）：
    floor-type   户型产品分析（蓝）
    price        价格与竞品分析（红橙）
    location     交通与配套分析（青）
    summary      总结与展望（深紫）

行为：
    1. 复制 assets/chapter-template.html 到 --out
    2. 注入主题色变量、页面标题与章节标识
    3. 打印剩余占位符清单，供逐项填写

只生成骨架，不生成正文内容——内容由 SKILL.md 的工作流驱动填写。
"""

import argparse
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_DIR / "assets" / "chapter-template.html"

# 章节类型 -> (中文名, 主色, 主色深, 辅助强调色)
CHAPTERS = {
    "floor-type": ("户型产品分析", "#2563eb", "#1d4ed8", "#60a5fa"),
    "price": ("价格与竞品分析", "#dc2626", "#b91c1c", "#f59e0b"),
    "location": ("交通与配套分析", "#0891b2", "#0e7490", "#06b6d4"),
    "summary": ("总结与展望", "#4338ca", "#3730a3", "#6366f1"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="楼盘报告章节脚手架")
    ap.add_argument("--out", required=True, help="输出 HTML 文件路径")
    ap.add_argument("--chapter", required=True, choices=sorted(CHAPTERS.keys()),
                    help="章节类型")
    ap.add_argument("--project", default="", help="楼盘名称")
    ap.add_argument("--city", default="", help="城市")
    ap.add_argument("--title", default="", help="章节标题（默认取章节类型名）")
    ap.add_argument("--force", action="store_true", help="目标已存在时覆盖")
    args = ap.parse_args()

    if not TEMPLATE.is_file():
        print(f"[error] 模板不存在：{TEMPLATE}", file=sys.stderr)
        return 1

    out = Path(args.out).expanduser().resolve()
    if out.exists() and not args.force:
        print(f"[error] 目标已存在：{out}（加 --force 覆盖）", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    chapter_name, accent, accent_deep, accent_soft = CHAPTERS[args.chapter]
    chapter_title = args.title or chapter_name
    project = args.project or "待填写楼盘名"
    meta_desc = f"{project} {chapter_title}｜数据来自公开渠道，仅供参考，不构成购房建议"

    html = TEMPLATE.read_text(encoding="utf-8")
    # 主题色：只替换变量值，不动 CSS 结构
    html = html.replace("{{ACCENT}}", accent)
    html = html.replace("{{ACCENT_DEEP}}", accent_deep)
    html = html.replace("{{ACCENT_SOFT}}", accent_soft)
    # 标题与元信息
    html = html.replace("{{DOC_TITLE}}", f"{project} · {chapter_title}")
    html = html.replace("{{META_DESC}}", meta_desc)
    html = html.replace("{{CHAPTER_NAME}}", chapter_title)
    html = html.replace("{{PROJECT}}", project)
    html = html.replace("{{CITY}}", args.city or "待填写城市")
    html = html.replace("{{CHAPTER_KEY}}", args.chapter)

    out.write_text(html, encoding="utf-8")

    placeholders = re.findall(r"\{\{([A-Z0-9_]+)\}\}", html)
    unique = sorted(set(placeholders))
    print(f"[ok] 已生成：{out}")
    print(f"[ok] 章节类型：{args.chapter}（{chapter_name}）  主色：{accent}")
    print(f"[ok] 占位符总数：{len(placeholders)}（去重 {len(unique)}）")
    if unique:
        print("\n待填写占位符：")
        print("  " + ", ".join(unique))
    else:
        print("\n所有占位符已注入完毕。")
    print("\n提示：填写完成后全文搜索 '{{' 应无命中。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
