#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""html-uploader 可运行示例。

演示如何以编程方式调用 upload_skill.py 完成一次 HTML 上传。
本脚本只做两件事：
  1. 准备一个最小示例 HTML（如 --file 未提供）
  2. 以子进程方式调用 upload_skill.py 执行上传，透传其退出码与输出

用法示例：
  # 用现成文件上传
  python example_upload.py --file D:/reports/report.html --title "示例报告"

  # 不传文件：自动生成一个示例 HTML 再上传（自检用）
  python example_upload.py --title "自检示例"

  # 指定系统与地址（密钥只从环境变量 HTMLVIEW_KEY 读取，绝不在此写死）
  python example_upload.py --system htmlview-agent-api --base-url http://localhost:8080

运行前需先完成预检：
  python check_config.py
  并把系统密钥设为环境变量（不落盘）：
    PowerShell: $env:HTMLVIEW_KEY = "..."
    bash:       export HTMLVIEW_KEY="..."
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
UPLOAD = SKILL_DIR / "scripts" / "upload_skill.py"

MINIMAL_HTML = (
    "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<title>{title}</title></head><body>"
    "<h1>{title}</h1><p>这是 html-uploader 示例脚本自动生成的最小 HTML 文档。</p>"
    "<ul><li>用于验证上传链路</li><li>包含 UTF-8 中文</li></ul>"
    "</body></html>"
)


def build_args(file_path: str, args: argparse.Namespace) -> list:
    """组装传给 upload_skill.py 的命令行参数。"""
    cmd = [sys.executable, str(UPLOAD), "--file", file_path]
    for flag, val in (("--system", args.system),
                      ("--base-url", args.base_url),
                      ("--title", args.title),
                      ("--tags", args.tags),
                      ("--summary", args.summary)):
        if val:
            cmd += [flag, val]
    if args.insecure:
        cmd += ["--insecure"]
    return cmd


def ensure_html(args: argparse.Namespace) -> str:
    """确定要上传的 HTML 路径；未提供文件时生成一个临时最小文档。"""
    if args.file:
        p = Path(args.file)
        if not p.is_file():
            print(f"[example] 文件不存在：{p}", file=sys.stderr)
            sys.exit(1)
        return str(p)

    title = args.title or "html-uploader 示例"
    fd, path = tempfile.mkstemp(suffix=".html", prefix="htmlup_example_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(MINIMAL_HTML.format(title=title))
    print(f"[example] 已生成临时示例文档：{path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="html-uploader 可运行示例")
    ap.add_argument("--file", help="待上传的 .html/.htm 文件；不传则自动生成最小示例文档")
    ap.add_argument("--system", default="", help="适配器名（默认 htmlview-agent-api）")
    ap.add_argument("--base-url", default="", help="目标系统地址（缺省走环境变量/config.json）")
    ap.add_argument("--title", default="", help="标题")
    ap.add_argument("--tags", default="", help="标签（逗号分隔）")
    ap.add_argument("--summary", default="", help="摘要")
    ap.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验（仅本地可信测试）")
    args = ap.parse_args()

    # 密钥只从环境变量读取；未设置时提醒用户，但不在此写死或回显
    if not os.environ.get("HTMLVIEW_KEY"):
        print("[example] 提示：环境变量 HTMLVIEW_KEY 未设置。"
              "请先完成预检（check_config.py）并设置密钥，"
              "否则 upload_skill.py 将返回退出码 3。", file=sys.stderr)

    file_path = ensure_html(args)
    cmd = build_args(file_path, args)
    print("[example] 执行上传：", " ".join(cmd))
    # 透传执行：upload_skill.py 自己处理登录/发现/上传/错误判定
    proc = subprocess.run(cmd)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
