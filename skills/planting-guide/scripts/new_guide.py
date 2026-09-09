#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从模板生成一份植物种植指南骨架。

用法：
    python new_guide.py --out "C:/path/to/guide.html" \
                        [--theme bloom|leaf|harvest|orchid|aqua|frost] \
                        [--title "成都·露台庭院 · 蓝雪花种植指南"] \
                        [--flora petal|double|spike|umbel|composite|fern|split|succulent|none] \
                        [--flora-size 260] [--flora-rot -12] [--flora-sway]

行为：
    1. 复制 assets/guide-template.html 到 --out
    2. 替换 data-theme、<title>，并按 --flora 注入首屏装饰 SVG
    3. 打印剩余占位符清单，供逐项填写

装饰形态按植物的花序/叶形特征选择（映射规则见 SKILL.md 第 4 步）。
--flora-size 为像素宽（模板自带响应式区间，不传则用默认）；
--flora-rot 为旋转角度（度，负值逆时针）；--flora-sway 开启轻摆动画。

只做骨架生成，不生成正文内容——内容由 SKILL.md 的工作流驱动填写。
"""

import argparse
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "guide-template.html"
VALID_THEMES = ("bloom", "leaf", "harvest", "orchid", "aqua", "frost")

# 装饰形态库：key -> (viewBox, 内部SVG)。统一 fill=currentColor，跟随主题强调色。
FLORA = {
    "petal": ("0 0 100 100",  # 五瓣花：蔷薇科、三角梅、矮牵牛、芙蓉
        '<path d="M50 8c14 0 20 12 13 22 6 6 4 16-7 18-2 8-9 13-19 11-2 9-11 14-20 9-7-4-9-13-6-20-9-3-12-13-5-20 6-7 16-7 22-2 4-9 12-18 22-18z" opacity=".9"></path>'
        '<circle cx="50" cy="52" r="6" fill="var(--paper)"></circle>'),
    "double": ("0 0 100 100",  # 重瓣花：月季、牡丹、茶花、重瓣矮牵牛
        '<circle cx="50" cy="50" r="30" opacity=".28"></circle>'
        '<circle cx="50" cy="50" r="20" opacity=".55"></circle>'
        '<circle cx="50" cy="50" r="10" opacity=".9"></circle>'
        '<circle cx="50" cy="50" r="3.5" fill="var(--paper)"></circle>'),
    "spike": ("0 0 60 100",  # 穗状花序：薰衣草、鼠尾草、狐尾百合
        '<path d="M30 96V40" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"></path>'
        '<path d="M30 44c-9 0-13-6-13-11 5-4 13-2 13 4 0-6 8-8 13-4 0 5-4 11-13 11z"></path>'
        '<circle cx="30" cy="26" r="5"></circle><circle cx="23" cy="34" r="4.4"></circle><circle cx="37" cy="34" r="4.4"></circle>'
        '<circle cx="26" cy="17" r="4"></circle><circle cx="34" cy="17" r="4"></circle><circle cx="30" cy="9" r="3.4"></circle>'
        '<path d="M30 66c-8-2-13 2-15 8 7 3 14-1 15-8z"></path>'),
    "umbel": ("0 0 100 100",  # 球序/伞形：绣球、大花葱、百子莲
        '<path d="M50 98V62" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"></path>'
        '<circle cx="50" cy="38" r="26" opacity=".22"></circle>'
        '<circle cx="50" cy="16" r="4.6"></circle><circle cx="64" cy="21" r="4.6"></circle>'
        '<circle cx="73" cy="33" r="4.6"></circle><circle cx="71" cy="48" r="4.6"></circle>'
        '<circle cx="59" cy="58" r="4.6"></circle><circle cx="41" cy="58" r="4.6"></circle>'
        '<circle cx="29" cy="48" r="4.6"></circle><circle cx="27" cy="33" r="4.6"></circle>'
        '<circle cx="36" cy="21" r="4.6"></circle><circle cx="50" cy="37" r="5"></circle>'),
    "composite": ("0 0 100 100",  # 菊科头状：向日葵、雏菊、波斯菊、金光菊
        '<g opacity=".85">'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(45 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(90 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(135 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(180 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(225 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(270 50 50)"></ellipse>'
        '<ellipse cx="50" cy="19" rx="6.5" ry="15" transform="rotate(315 50 50)"></ellipse></g>'
        '<circle cx="50" cy="50" r="12"></circle>'
        '<circle cx="50" cy="50" r="5" fill="var(--paper)"></circle>'),
    "fern": ("0 0 80 100",  # 羽叶：蕨类、文竹、羽叶薰衣草
        '<path d="M40 98V30" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"></path>'
        '<path d="M40 34c0-16 10-28 24-30 2 16-8 28-24 30z"></path>'
        '<path d="M40 52c0-14-9-24-22-26-2 14 7 24 22 26z"></path>'
        '<path d="M40 70c0-12 8-21 19-23 2 12-6 21-19 23z"></path>'
        '<circle cx="40" cy="22" r="4" fill="var(--paper)"></circle>'),
    "split": ("0 0 90 100",  # 裂叶/孔叶：龟背竹、春羽、橡皮树等观叶
        '<path d="M45 98V56" stroke="currentColor" stroke-width="3" fill="none" stroke-linecap="round"></path>'
        '<path opacity=".88" d="M45 60C14 58 4 38 8 20c3-13 15-18 26-14 4-6 12-8 18-4 12-4 24 3 27 15 4 17-7 41-34 43z"></path>'
        '<ellipse cx="30" cy="28" rx="4" ry="7" transform="rotate(20 30 28)" fill="var(--paper)"></ellipse>'
        '<ellipse cx="55" cy="24" rx="4" ry="7" transform="rotate(-15 55 24)" fill="var(--paper)"></ellipse>'
        '<ellipse cx="66" cy="40" rx="3.4" ry="6" transform="rotate(-30 66 40)" fill="var(--paper)"></ellipse>'),
    "succulent": ("0 0 100 100",  # 莲座：多肉、仙人掌科、芦荟
        '<g opacity=".9">'
        '<path transform="rotate(0 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(45 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(90 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(135 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(180 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(225 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(270 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path>'
        '<path transform="rotate(315 50 55)" d="M50 55c-6-10-5-24 0-34 5 10 6 24 0 34z"></path></g>'
        '<circle cx="50" cy="55" r="5" fill="var(--paper)"></circle>'),
}
VALID_FLORA = tuple(FLORA.keys()) + ("none",)


def build_flora(key: str, size: int | None, rot: float, sway: bool) -> str:
    if key == "none":
        return ""
    vb, inner = FLORA[key]
    style = []
    if size:
        style.append(f"--fb-w:{size}px")
    if rot:
        style.append(f"--fb-rot:{rot}deg")
    style_attr = f' style="{";".join(style)}"' if style else ""
    cls = "flora-bloom fb-sway" if sway else "flora-bloom"
    return (f'<span class="{cls}"{style_attr} aria-hidden="true">'
            f'<svg class="fb" viewBox="{vb}" fill="currentColor">{inner}</svg></span>')


def main() -> int:
    ap = argparse.ArgumentParser(description="生成植物种植指南骨架")
    ap.add_argument("--out", required=True, help="输出 HTML 文件路径")
    ap.add_argument("--theme", default="bloom", choices=VALID_THEMES,
                    help="强调色主题（按主力植物花色/气质选，见 SKILL.md）")
    ap.add_argument("--flora", default="petal", choices=VALID_FLORA,
                    help="首屏装饰形态（按植物花序/叶形特征选，见 SKILL.md；none 为不显示）")
    ap.add_argument("--flora-size", type=int, default=None, metavar="PX",
                    help="装饰宽度像素（可选，默认模板响应式 120~220px）")
    ap.add_argument("--flora-rot", type=float, default=0.0, metavar="DEG",
                    help="装饰旋转角度（度，负值逆时针）")
    ap.add_argument("--flora-sway", action="store_true", help="装饰开启轻摆动画")
    ap.add_argument("--title", default="", help="网页 <title>")
    ap.add_argument("--force", action="store_true", help="目标文件已存在时覆盖")
    args = ap.parse_args()

    if not TEMPLATE.is_file():
        print(f"[error] 模板不存在：{TEMPLATE}", file=sys.stderr)
        return 1

    out = Path(args.out).expanduser().resolve()
    if out.exists() and not args.force:
        print(f"[error] 目标已存在：{out}（加 --force 覆盖）", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)

    html = TEMPLATE.read_text(encoding="utf-8")
    html = re.sub(r'(<html[^>]*data-theme=")[^"]+(")', rf"\g<1>{args.theme}\g<2>", html, count=1)
    if args.title:
        html = re.sub(r"<title>.*?</title>", f"<title>{args.title}</title>", html, count=1, flags=re.S)
    html = html.replace("{{FLORA_DECOR}}", build_flora(args.flora, args.flora_size, args.flora_rot, args.flora_sway))

    out.write_text(html, encoding="utf-8")

    placeholders = re.findall(r"\{\{([A-Z0-9_]+)\}\}", html)
    unique = sorted(set(placeholders))
    print(f"[ok] 已生成：{out}")
    print(f"[ok] 主题：{args.theme}   装饰：{args.flora}"
          + (f"（{args.flora_size}px" if args.flora_size else "")
          + (f", 旋转 {args.flora_rot}deg" if args.flora_rot else "")
          + (", 轻摆" if args.flora_sway else "") + ("）" if (args.flora_size or args.flora_rot or args.flora_sway) else ""))
    print(f"[ok] 占位符总数：{len(placeholders)}（去重 {len(unique)}）")
    print("\n待填写占位符：")
    print("  " + ", ".join(unique))
    print("\n提示：填写完成后全文搜索 '{{' 应无命中。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
