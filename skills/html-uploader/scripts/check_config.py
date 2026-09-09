#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""html-uploader 预检脚本：判断"系统地址"与"访问密钥"是否已就绪，缺失则给出提问建议。

用法:
    python scripts/check_config.py [--system <适配器名>] [--base-url <地址>]
                                   [--key-env <环境变量名>] [--config <配置文件路径>] [--no-env]

参数:
    --system     适配器名（默认读 config.json 的 default_system，再退化为 htmlview-agent-api）
    --base-url   用户当次提供的系统地址（最高优先级，用于跳过提问）
    --key-env    覆盖密钥环境变量名
    --config     配置文件路径（默认 <本Skill目录>/config.json）
    --no-env     忽略环境变量，仅看配置与适配器声明（谨慎使用）

输出（UTF-8 JSON，打印到 stdout）:
    {
      "system": "htmlview-agent-api",
      "adapter": "<适配器文件绝对路径>",
      "adapter_found": true,
      "key_required": true,
      "auth_form": "login-bearer",
      "base_url": {"value": "", "source": "none|cli|env|config|adapter", "status": "ok|missing"},
      "key": {"env_name": "HTMLVIEW_KEY", "value_set": false,
              "source": "env|none", "status": "ok|missing|not_required"},
      "config_path": "...",
      "missing": ["base_url", "key"],
      "ask": [ {"item": "base_url", "question": "...", "options": [...], "free_text": true}, ... ],
      "hint": "..."
    }

退出码:
    0  全部就绪
    3  存在缺失项（missing 非空）—— 需按 ask 列表向用户提问获取
    4  适配器文件不存在

安全约定:
    本脚本只判断"密钥环境变量是否已设置"，绝不读取、回显或落盘密钥内容。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SYSTEM = "htmlview-agent-api"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_adapter(path: Path):
    """从适配器 markdown 中解析 base_url 与 auth 声明。"""
    info = {"base_url": "", "auth_form": "unknown", "env_name": "", "login_endpoint": ""}
    if not path.is_file():
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]\s*base_url\s*:\s*(.+?)\s*$", line)
        if m:
            val = m.group(1).strip()
            # 视为"未声明"的写法：空、以（空/空开头、尖括号占位符、纯占位说明
            if val and not val.startswith("<") and not val.startswith("（"):
                info["base_url"] = val
            continue
        m = re.match(r"^\s*[-*]\s*auth\s*:\s*(.+?)\s*$", line)
        if m:
            val = m.group(1).strip()
            parts = [p for p in val.split(":") if p]
            if not parts:
                continue
            form = parts[0]
            info["auth_form"] = form
            if form == "none":
                info["env_name"] = ""
            elif form in ("bearer", "login-bearer"):
                # login-bearer:HTMLVIEW_KEY         -> 环境变量在最后一段
                # login-bearer:/api/auth/login:ENV  -> 环境变量在最后一段，中间是登录端点
                if len(parts) >= 3:
                    info["login_endpoint"] = parts[1]
                info["env_name"] = parts[-1] if len(parts) >= 2 else ""
            elif form == "header":
                # header:<头名>:<环境变量名>
                info["env_name"] = parts[-1] if len(parts) >= 3 else ""
            elif form == "basic":
                info["env_name"] = ""
    return info


def load_config(path: Path):
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="")
    ap.add_argument("--base-url", dest="base_url", default="")
    ap.add_argument("--key-env", dest="key_env", default="")
    ap.add_argument("--config", dest="config", default=str(SKILL_DIR / "config.json"))
    ap.add_argument("--no-env", action="store_true")
    args = ap.parse_args()

    config_path = Path(args.config)
    cfg = load_config(config_path)

    system = args.system or cfg.get("default_system") or DEFAULT_SYSTEM
    sys_cfg = (cfg.get("systems") or {}).get(system) or {}

    adapter_path = SKILL_DIR / "adapters" / f"{system}.md"
    adapter_found = adapter_path.is_file()
    adapter = parse_adapter(adapter_path)

    # ---- 系统地址：当次输入 > 环境变量 > config.json > 适配器声明 ----
    env_base_name = system.upper().replace("-", "_") + "_BASE_URL"
    base_url, base_source = "", "none"
    if args.base_url:
        base_url, base_source = args.base_url.strip(), "cli"
    elif not args.no_env and os.environ.get("HTMLVIEW_BASE_URL", "").strip():
        base_url, base_source = os.environ["HTMLVIEW_BASE_URL"].strip(), "env:HTMLVIEW_BASE_URL"
    elif not args.no_env and os.environ.get(env_base_name, "").strip():
        base_url, base_source = os.environ[env_base_name].strip(), "env:" + env_base_name
    elif sys_cfg.get("base_url", "").strip():
        base_url, base_source = sys_cfg["base_url"].strip(), "config"
    elif adapter["base_url"] and not adapter["base_url"].startswith("<"):
        base_url, base_source = adapter["base_url"], "adapter"

    # ---- 访问密钥 ----
    auth_form = adapter["auth_form"]
    key_required = not (auth_form == "none" and not sys_cfg.get("require_key", False))
    env_name = args.key_env or sys_cfg.get("key_env") or adapter["env_name"] or ""

    if not key_required:
        key_status, key_source, key_set = "not_required", "none", False
    elif env_name and not args.no_env and os.environ.get(env_name, "").strip():
        key_status, key_source, key_set = "ok", "env:" + env_name, True
    elif not env_name:
        # basic 等未声明环境变量名的形态：只能靠用户当次提供
        key_status, key_source, key_set = "missing", "none", False
    else:
        key_status, key_source, key_set = "missing", "none", False

    missing = []
    if not base_url:
        missing.append("base_url")
    if key_status == "missing":
        missing.append("key")

    # ---- 提问建议（供 agent 直接用 AskUserQuestion 发起）----
    ask = []
    if "base_url" in missing:
        opts = []
        if sys_cfg.get("last_base_url"):
            opts.append("上次使用：" + sys_cfg["last_base_url"])
        opts.append("本地服务 http://localhost:8080")
        opts.append("我手动填写系统地址（选“其他”输入，如 https://docs.example.com）")
        ask.append({
            "item": "base_url",
            "question": f"上传到 {system} 需要目标系统地址，当前未配置。请提供系统地址：",
            "options": opts,
            "free_text": True,
            "note": "地址非敏感信息，获取后可写入 config.json 以便下次免问。",
        })
    if "key" in missing:
        if env_name:
            ask.append({
                "item": "key",
                "question": (
                    f"访问 {system} 需要密钥。请选择提供方式（密钥属敏感信息，仅在本次任务内存中使用，不写入任何文件）："
                ),
                "options": [
                    f"我现在提供密钥（选“其他”直接粘贴）",
                    f"密钥已写入环境变量 {env_name}，直接读取",
                    "该目标系统无需鉴权（跳过密钥）",
                ],
                "free_text": True,
                "note": f"环境变量名：{env_name}。绝不把密钥写入 config.json、适配器或日志。",
            })
        else:
            ask.append({
                "item": "key",
                "question": f"适配器 {system} 声明的认证形态为 {auth_form}，需要凭据。请提供（选“其他”填写，如 user:password 或令牌）：",
                "options": ["我现在提供凭据（选“其他”直接粘贴）", "该目标系统无需鉴权（跳过）"],
                "free_text": True,
                "note": "凭据仅在本次任务内存中使用，不落盘。",
            })

    result = {
        "system": system,
        "adapter": str(adapter_path),
        "adapter_found": adapter_found,
        "auth_form": auth_form,
        "login_endpoint": adapter.get("login_endpoint", ""),
        "key_required": key_required,
        "base_url": {
            "value": base_url,
            "source": base_source,
            "status": "ok" if base_url else "missing",
            "env_name": "HTMLVIEW_BASE_URL / " + env_base_name,
        },
        "key": {
            "env_name": env_name,
            "value_set": key_set,
            "source": key_source,
            "status": key_status,
        },
        "config_path": str(config_path),
        "missing": missing,
        "ask": ask,
        "hint": (
            "全部就绪，直接进入五段流程。"
            if not missing else
            "缺失项请通过提问向用户一次性获取（可把多个问题放在同一轮提问中），切勿用示例值或猜测值直接尝试上传。"
        ),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not adapter_found:
        sys.exit(4)
    sys.exit(3 if missing else 0)


if __name__ == "__main__":
    main()
