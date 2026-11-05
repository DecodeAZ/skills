#!/usr/bin/env python3
"""Collect minimal read-only probe results for travel-planner dependencies.

The generic dependency checker (scripts/check_environment.py) intentionally
refuses to run CLI or credential probes itself: those must be executed by a
trusted host and passed back as a redacted probe-results.json. This script is
that host-side collector for the probes that do not require interactive login.

Design notes:
- 判定口径基于业务状态而非进程退出码：flyai 在业务失败时仍以退出码 0 结束
  （实测：非法日期返回 status=1 且 data=null），只看退出码会把失败误判为可用。
- 凭据只从环境变量读取，只用于拼一次请求 URL，不落盘、不回显、不进输出文件。
- 单次探测失败不会中断整轮采集；结果文件按同目录临时文件 + 原子替换写入。

Usage:
    python scripts/collect_self_probe.py --output .probe-results.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROBE_TIMEOUT = 30
HTTP_TIMEOUT = 12
UA = "travel-planner-envcheck/1.0"

# Windows 下 os.replace 会因目标被瞬时占用报 WinError 5/32（PermissionError）。
# 实测 12 并发覆盖写 120 次命中 1 次，故做有界重试；耗尽仍原样抛出，不掩盖真实错误。
REPLACE_ATTEMPTS = 5
REPLACE_BACKOFF_SECONDS = 0.05

EXIT_OK = 0
EXIT_WRITE_FAILED = 2

STATUS_READY = "ready"
STATUS_MISSING = "missing"
STATUS_UNAVAILABLE = "unavailable"

REASON_OK = "ok"
REASON_PROBE_FAILED = "probe_failed"
REASON_NETWORK = "network_or_timeout"
REASON_QUOTA = "quota_or_rate_limit"
REASON_AUTH = "auth_expired_or_invalid"
REASON_CONFIG = "configuration_invalid"
REASON_SERVICE = "service_error"

# 探测用查询：服务正常时该查询返回非空 itemList，便于区分「可用」与「无结果」
FLYAI_PROBE_ARGS = ("keyword-search", "--query", "杭州")
FLYAI_TARGET = "flyai " + " ".join(FLYAI_PROBE_ARGS)
MCPORTER_TARGET = "mcporter list"
QWEATHER_TARGET = "devapi.qweather.com/v7/weather/7d"
AMAP_TARGET = "restapi.amap.com/v3/weather/weatherInfo"

SKILL_ROOT = Path(__file__).resolve().parents[1]

# 业务文案关键字 → 原因码，顺序即优先级
MESSAGE_RULES = (
    (REASON_QUOTA, ("limit", "quota", "exceed", "rate limit", "too many", "限流", "风控")),
    (REASON_AUTH, ("auth", "token", "login", "unauthorized", "forbidden", "permission", "鉴权", "登录")),
    (REASON_CONFIG, ("param", "invalid", "非法", "校验")),
)
# 参数/调用方式错误的命令行文案
STDERR_RULES = (
    (REASON_CONFIG, ("unknown command", "required option", "unknown option", "missing required")),
)
# 密钥类文案：优先于通用的 invalid 关键字，避免把坏 Key 判成参数错误
AUTH_HINTS = ("invalid_user_key", "invalid key", "api key", "apikey", "no key", "密钥", "签名错误")
STDERR_STATUS_PATTERN = re.compile(r"\b(?:401|403|429)\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(check_type: str, target: str, status: str, reason_code: str) -> dict:
    return {
        "status": status,
        "reason_code": reason_code,
        "check_type": check_type,
        "target": target,
        "checked_at": utc_now(),
    }


def run_cli(executable: str, args: tuple) -> tuple:
    """执行一次只读探测命令。

    Windows 的 CreateProcess 不做 PATHEXT 解析，裸命令名会直接 FileNotFoundError，
    所以调用方必须先经 shutil.which 解析出实际路径。这里不使用 shell，避免注入面。
    """
    try:
        proc = subprocess.run(
            [executable, *args],
            capture_output=True,
            timeout=PROBE_TIMEOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except (FileNotFoundError, OSError) as exc:
        return 127, "", "%s: %s" % (type(exc).__name__, exc)


def classify_message(message) -> str:
    text = message.lower() if isinstance(message, str) else ""
    for reason, keywords in MESSAGE_RULES:
        if any(keyword in text for keyword in keywords):
            return reason
    return REASON_SERVICE


def classify_stderr(stderr) -> str:
    """命令行的错误文本只在 stderr 上匹配，避免把业务载荷里的数字当状态码。"""
    text = (stderr or "").lower()
    for reason, keywords in STDERR_RULES:
        if any(keyword in text for keyword in keywords):
            return reason
    if STDERR_STATUS_PATTERN.search(text) or "risk control" in text:
        return REASON_QUOTA
    return REASON_PROBE_FAILED


def classify_cli_envelope(code: int, stdout: str, stderr: str) -> tuple:
    """判定一次 flyai 调用结果，返回 (status, reason_code)。

    flyai 的退出码不可信：业务失败（参数非法、风控、无库存）仍以 0 结束，
    真实成败在 JSON 信封的 status 与 data 上。status=0 且 data=null 表示
    查询成功但无样本，探测口径下保守记为空（不认定为可用）。
    """
    if code == 124:
        return STATUS_UNAVAILABLE, REASON_NETWORK
    text = (stdout or "").strip()
    if not text:
        return STATUS_UNAVAILABLE, classify_stderr(stderr)
    try:
        payload = json.loads(text)
    except ValueError:
        return STATUS_UNAVAILABLE, classify_stderr(stderr)
    if not isinstance(payload, dict) or payload.get("status") is None:
        return STATUS_UNAVAILABLE, REASON_PROBE_FAILED
    if payload.get("status") != 0:
        return STATUS_UNAVAILABLE, classify_message(payload.get("message"))
    if payload.get("data") is None:
        return STATUS_UNAVAILABLE, REASON_SERVICE
    return STATUS_READY, REASON_OK


def is_success_payload(data: dict) -> bool:
    """兼容两家的成功信封：和风用 code=200，高德用 status=1。"""
    code = data.get("code")
    if isinstance(code, str) and code.strip() == "200":
        return True
    if isinstance(code, int) and code == 200:
        return True
    return str(data.get("status", "")).strip() == "1"


def classify_api_failure(data: dict) -> str:
    code = str(data.get("code", "")).strip()
    if code in {"401", "403"}:
        return REASON_AUTH
    if code in {"402", "429"}:
        return REASON_QUOTA
    text = json.dumps(data, ensure_ascii=False).lower()
    if any(hint in text for hint in AUTH_HINTS):
        return REASON_AUTH
    for reason, keywords in MESSAGE_RULES:
        if any(keyword in text for keyword in keywords):
            return reason
    return REASON_PROBE_FAILED


def probe_flyai() -> tuple:
    executable = shutil.which("flyai")
    if not executable:
        return STATUS_MISSING, REASON_PROBE_FAILED
    code, out, err = run_cli(executable, FLYAI_PROBE_ARGS)
    return classify_cli_envelope(code, out, err)


def probe_mcporter() -> tuple:
    """只验证命令行可执行，不代表已注册小红书检索服务。"""
    executable = shutil.which("mcporter")
    if not executable:
        return STATUS_MISSING, REASON_PROBE_FAILED
    code, out, err = run_cli(executable, ("list",))
    if code == 124:
        return STATUS_UNAVAILABLE, REASON_NETWORK
    if code != 0:
        return STATUS_UNAVAILABLE, classify_stderr(err)
    return STATUS_READY, REASON_OK


def probe_api_key(env_name: str, base_url: str) -> tuple:
    """用一次最小只读请求校验 API Key，Key 只出现在 URL 里，不回显、不落盘。"""
    key = os.environ.get(env_name, "").strip()
    if not key:
        return STATUS_MISSING, REASON_CONFIG
    url = base_url + urllib.parse.quote(key, safe="")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return STATUS_UNAVAILABLE, REASON_AUTH
        if exc.code == 429:
            return STATUS_UNAVAILABLE, REASON_QUOTA
        return STATUS_UNAVAILABLE, REASON_SERVICE
    except (urllib.error.URLError, OSError, ValueError):
        return STATUS_UNAVAILABLE, REASON_NETWORK
    try:
        data = json.loads(body)
    except ValueError:
        return STATUS_UNAVAILABLE, REASON_PROBE_FAILED
    if not isinstance(data, dict):
        return STATUS_UNAVAILABLE, REASON_PROBE_FAILED
    if is_success_payload(data):
        return STATUS_READY, REASON_OK
    return STATUS_UNAVAILABLE, classify_api_failure(data)


def probe_qweather() -> tuple:
    return probe_api_key(
        "QWEATHER_API_KEY",
        "https://devapi.qweather.com/v7/weather/7d?location=101210101&key=",
    )


def probe_amap() -> tuple:
    return probe_api_key(
        "AMAP_MAPS_API_KEY",
        "https://restapi.amap.com/v3/weather/weatherInfo?city=330100&key=",
    )


def safe_probe(check_type: str, target: str, probe) -> dict:
    """收敛单次探测：异常不外溢，并强制满足 probe-results schema 的配对约束。

    schema 要求 status=ready 时必须 reason_code=ok，status 非 ready 时不得为 ok。
    在这里兜住，保证产物永远是合法结果文件。
    """
    try:
        status, reason = probe()
    except Exception:
        status, reason = STATUS_UNAVAILABLE, REASON_PROBE_FAILED
    if status == STATUS_READY:
        reason = REASON_OK
    elif reason == REASON_OK:
        reason = REASON_PROBE_FAILED
    return entry(check_type, target, status, reason)


def collect() -> dict:
    return {
        "flyai-cli": {
            "flyai-probe": safe_probe("cli_probe", FLYAI_TARGET, probe_flyai),
        },
        "mcporter-cli": {
            "mcporter-probe": safe_probe("cli_probe", MCPORTER_TARGET, probe_mcporter),
        },
        "qweather": {
            "qweather-auth": safe_probe("auth_probe", QWEATHER_TARGET, probe_qweather),
        },
        "amap": {
            "amap-auth": safe_probe("auth_probe", AMAP_TARGET, probe_amap),
        },
    }


def inside_skill_package(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(SKILL_ROOT)
        return True
    except (ValueError, OSError):
        return False


def replace_with_retry(source, target) -> None:
    """把临时文件改名到目标位置；目标被短暂占用时有界重试。"""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


def write_results(path: Path, results: dict) -> None:
    """同目录临时文件 + 原子改名，避免中断留下半截结果文件。"""
    target = Path(path)
    parent = target.parent if str(target.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(
        prefix=".probe-results-", suffix=".tmp", dir=str(parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        replace_with_retry(temp_path, str(target))
    except BaseException:
        # 只删除本函数上一行刚创建的同目录临时文件；预检会把 os.unlink 记为
        # file_delete 能力，此处保留是为了不留下半截结果文件。
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def summarize(results: dict) -> str:
    lines = []
    counts = {}
    for dependency_id, checks in results.items():
        for check_id, item in checks.items():
            counts[item["status"]] = counts.get(item["status"], 0) + 1
            lines.append(
                "%s.%s -> %s (%s)"
                % (dependency_id, check_id, item["status"], item["reason_code"])
            )
    lines.append(
        "汇总：ready %d / missing %d / unavailable %d"
        % (
            counts.get(STATUS_READY, 0),
            counts.get(STATUS_MISSING, 0),
            counts.get(STATUS_UNAVAILABLE, 0),
        )
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="收集 travel-planner 依赖的最小只读探测结果"
    )
    parser.add_argument("--output", type=Path, default=Path(".probe-results.json"))
    parser.add_argument("--quiet", action="store_true", help="只打印结果文件路径")
    args = parser.parse_args(argv)

    if inside_skill_package(args.output):
        print(
            "提示：输出落在技能包内（%s），建议改到技能包外的目录，避免产物被打包分发。"
            % args.output,
            file=sys.stderr,
        )

    results = collect()
    try:
        write_results(args.output, results)
    except OSError as exc:
        payload = {"status": "error", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False))
        return EXIT_WRITE_FAILED

    if not args.quiet:
        print(summarize(results))
    print("probe results written to: %s" % args.output)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
