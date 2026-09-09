#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""html-uploader 统一上传执行器（仅 Python 标准库，零依赖，不使用 curl）

v1.1.1

本脚本是 html-uploader 技能包唯一的实际请求执行体。按适配器文件（adapters/<系统名>.md）
驱动的通用流程，所有 HTTP 请求均在本脚本内完成：

  预检/配置获取 → 认证 → 能力发现（可选）→ 上传（multipart 或 JSON）→ 结果判定/回查

适配器文件中的 request/success/errors 段由本脚本解析，字段名与端点差异全部在适配器内
声明，因此新增系统只需新增适配器文件，无需改本脚本。

安全约定：
  - 系统地址只存非敏感 config.json；密钥只从环境变量或 --key 读取，不落盘、日志脱敏；
  - 会话令牌仅存进程内存；401 自动重登一次；403 改密要求立即中止；429 按 Retry-After 等待。

用法：
  python upload_skill.py --help
  python upload_skill.py --version
  python upload_skill.py --file report.html [--system <适配器>] \
       [--title T] [--tags a,b] [--summary S]
  # 地址/密钥通过 --base-url、环境变量提供；或依赖外部 check_config.py 提问后写入环境变量
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

__version__ = "1.1.1"

SKILL_DIR = Path(__file__).resolve().parent.parent
MAX_DEFAULT_SIZE = 20 * 1024 * 1024

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def log(msg):
    print(f"[upload_skill] {msg}")


def mask(s):
    if not s:
        return "***"
    return (s[:2] + "***" + s[-2:]) if len(s) > 6 else "***"


# ---------- 适配器文件解析 ----------

def read_adapter(system: str) -> dict:
    """解析 adapters/<system>.md 的接口约定。"""
    path = SKILL_DIR / "adapters" / f"{system}.md"
    info = {
        "name": system,
        "path": str(path),
        "found": path.is_file(),
        "base_url": "",
        "max_size": MAX_DEFAULT_SIZE,
        "auth_form": "none",
        "env_name": "",
        "login_endpoint": "",
        "method": "POST",
        "endpoint": "/api/agent/articles",
        "content_type": "multipart/form-data",
        "fields": {"file": "file", "title": "title", "tags": "tags", "summary": "summary"},
        "success_status": 201,
        "success_field": "id",
    }
    if not path.is_file():
        return info
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]\s*base_url\s*:\s*(.+?)\s*$", line)
        if m and not m.group(1).strip().startswith(("<", "（")):
            info["base_url"] = m.group(1).strip()
            continue
        m = re.match(r"^\s*[-*]\s*max_size\s*:\s*(\d+)\s*[Mm]?B?\s*$", line, re.I)
        if m:
            info["max_size"] = int(m.group(1)) * 1024 * 1024
            continue
        m = re.match(r"^\s*[-*]\s*auth\s*:\s*(.+?)\s*$", line)
        if m:
            val = m.group(1).strip()
            parts = [p for p in val.split(":") if p]
            form = parts[0] if parts else "none"
            info["auth_form"] = form
            if form == "none":
                info["env_name"] = ""
            elif form in ("bearer", "login-bearer", "header"):
                if form == "login-bearer" and len(parts) >= 3:
                    info["login_endpoint"] = parts[1]
                # 环境变量名取段中形如 [A-Z0-9_]+ 的词（避免抓入中文说明）
                tail = parts[-1] if len(parts) >= 2 else ""
                m = re.search(r"[A-Z][A-Z0-9_]*", tail)
                info["env_name"] = m.group(0) if m else ""
                if form == "header":
                    hm = re.search(r"[A-Za-z][A-Za-z0-9-]*", parts[1]) if len(parts) >= 3 else None
                    info.setdefault("header_name", hm.group(0) if hm else "authorization")
            elif form == "basic":
                info["env_name"] = ""
            continue

    # 方法 + 端点
    req = _section(text, "## request")
    m = re.search(r"\b(POST|PUT|PATCH|GET)\b[^:]*[:，进行>]*\s*<base_url>(\S+)", req)
    if m:
        info["method"] = m.group(1).upper()
        info["endpoint"] = m.group(2).rstrip("，,）)")
    m = re.search(r"Content-Type:\s*([^\s，,；;]+)", req)
    if m:
        info["content_type"] = m.group(1).strip()

    # 字段映射：- file → `file`
    for fm in re.finditer(r"^\s*[-*]\s*(\w+)\s*→\s*`([^`]+)`", req, re.M):
        info["fields"][fm.group(1)] = fm.group(2).strip()

    # 成功判据
    succ = _section(text, "## success")
    m = re.search(r"\b(\d{3})\b", succ)
    if m:
        info["success_status"] = int(m.group(1))
    m = re.search(r"含\s*[`]?(\w+)[`]?", succ)
    if m:
        info["success_field"] = m.group(1)
    if re.search(r"contentBase64|base64", req):
        info["content_type"] = "json"
    return info


def _section(text, header):
    """返回从 header 到下一个二级标题之间的内容。"""
    match = re.search(rf"^##\s+{header}\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.M)
    return match.group(1) if match else ""


# ---------- HTTP（urllib，标准库） ----------

def make_opener(insecure: bool):
    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def http_request(opener, method, url, headers=None, data=None, timeout=120):
    headers = dict(headers or {})
    headers.setdefault("User-Agent", DEFAULT_USER_AGENT)
    headers.setdefault("Accept", "*/*")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def parse_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def extract_error(status, body):
    """从失败响应中提取 (错误码, 详情)，兼容 JSON 与纯文本体。"""
    data = parse_json(body) if isinstance(body, (bytes, bytearray)) else None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return err.get("code") or "", err.get("message") or ""
        if data.get("code") or data.get("message"):
            return data.get("code") or "", data.get("message") or ""
    msg = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
    return "", " ".join(msg.split())[:200]


class Client:
    """鉴权客户端：支持 none / bearer / login-bearer / header，401 自动重登一次。"""

    def __init__(self, adapter, base_url, key, insecure):
        self.a = adapter
        self.base = base_url.rstrip("/")
        self.key = key
        self.token = None
        self.opener = make_opener(insecure)

    def credential(self):
        return self.token or self.key or ""

    def auth_headers(self, extra=None):
        h = dict(extra or {})
        val = self.credential()
        if not val:
            return h
        a = self.a
        if a["auth_form"] == "login-bearer" or a["auth_form"] == "bearer":
            h.setdefault("authorization", f"Bearer {val}")
        elif a["auth_form"] == "header":
            h.setdefault(a.get("header_name", "authorization"), val)
        # basic / none：不注入
        return h

    def login(self):
        a = self.a
        if a["auth_form"] != "login-bearer":
            return
        payload = json.dumps({"key": self.key}).encode("utf-8")
        status, _, body = http_request(
            self.opener, "POST", self.base + a["login_endpoint"],
            {"content-type": "application/json"}, payload)
        data = parse_json(body) or {}
        if status == 429:
            retry = data.get("retryAfter") or 5
            log(f"登录限流，等待 {mask(str(retry))} 秒后重试一次")
            time.sleep(min(60, int(retry) if str(retry).isdigit() else 5))
            return self.login()
        if status != 200:
            code, detail = extract_error(status, body)
            hint = ""
            if status == 403 and not parse_json(body):
                hint = ("；服务端返回非 JSON（如 error code 1010 之类），多为 WAF/Cloudflare 拦截请求，"
                        "请确认请求带浏览器 User-Agent（本脚本已默认补充）或在浏览器实际访问"
                        " https://p3s.decodeaz.xyz/ 排查")
            raise RuntimeError(f"登录失败 {status} {code} {detail}{hint}（密钥 {mask(self.key)}）")
        if data.get("mustChange"):
            raise RuntimeError(
                "服务端仍在使用临时密钥（key_change_required）："
                "请先在目标系统网页端完成首次改密，再运行本脚本")
        self.token = data.get("token") or data.get("access_token") or ""
        log(f"登录成功，会话令牌 {mask(self.token)}（仅存内存）")

    def request(self, method, path, data=None, headers=None):
        h = self.auth_headers(headers)
        status, hdrs, body = http_request(self.opener, method, self.base + path, h, data)
        if status == 401 and self.a["auth_form"] == "login-bearer":
            log("会话失效（401），重新登录一次…")
            self.login()
            h = self.auth_headers(headers)
            status, hdrs, body = http_request(self.opener, method, self.base + path, h, data)
        return status, hdrs, body


def multipart(fields, file_field, file_name, file_bytes, ctype):
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        if value is None:
            continue
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode("utf-8")
        out += str(value).encode("utf-8") + b"\r\n"
    out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
            f"filename=\"{file_name}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
    out += file_bytes + b"\r\n"
    out += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# ---------- 上传主流程 ----------

def discover(client: Client):
    """可选能力发现：仅当适配器声明 discovery 非 none 时启用。"""
    a = client.a
    disc = _section(Path(a["path"]).read_text(encoding="utf-8"), "discovery")
    if not disc or "none" in disc:
        return a["endpoint"], a["method"]
    # 从 discovery 段找 GET 路径与期望 service/工具
    m = re.search(r"GET\s*<base_url>(\S+)", disc)
    if m:
        status, _, body = client.request("GET", m.group(1).rstrip("，,）)"))
        data = parse_json(body) or {}
        tool = next((t for t in data.get("tools", []) if t.get("name") == a.get("tool", "")), None)
        if tool:
            return tool.get("path", a["endpoint"]), tool.get("method", a["method"])
    return a["endpoint"], a["method"]


def upload(client: Client, pkg_bytes, title, tags, summary, content_type="text/html"):
    a = client.a
    f = a["fields"]
    meta = {"title": title, "tags": tags, "summary": summary}
    if a["content_type"] == "json":
        if f.get("file"):
            pass
        payload = {}
        for k, v in f.items():
            if k == "file":
                payload[f.get("fileName", "fileName")] = "report.html"
                payload[f.get("contentBase64", "contentBase64")] = base64.b64encode(pkg_bytes).decode("ascii")
            else:
                payload[v] = meta.get(k)
        body = json.dumps({k: v for k, v in payload.items() if v is not None}).encode("utf-8")
        headers = {"content-type": a["content_type"] if a["content_type"] != "json" else "application/json"}
        status, _, resp = client.request(a["method"], a["endpoint"], body, headers or {"content-type": "application/json"})
    else:
        body, ctype = multipart(
            {v: meta.get(k) for k, v in f.items() if k != "file"},
            f.get("file", "file"), "report.html", pkg_bytes, content_type)
        status, _, resp = client.request(a["method"], a["endpoint"], body, {"content-type": ctype})
    data = parse_json(resp) or {}
    if status == 429:
        log("上传限流，稍候重试一次")
        time.sleep(30)
        return upload(client, pkg_bytes, title, tags, summary, content_type)
    if status != a["success_status"]:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        raise RuntimeError(f"上传失败 {status} {err.get('code', '')} {err.get('message', '')} {resp[:300]}")
    return data


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="html-uploader 统一上传执行器（纯 Python，无 curl）")
    ap.add_argument("--version", action="store_true", help="显示版本号")
    ap.add_argument("--file", help="待上传的 HTML 文件路径（不传则以本技能打包内容为载荷）")
    ap.add_argument("--system", default="", help="适配器名（默认读 config.json 的 default_system）")
    ap.add_argument("--base-url", default="", help="目标系统地址（覆盖配置）")
    ap.add_argument("--key", default=os.environ.get("HTMLVIEW_KEY", ""), help="密钥（优先用环境变量，不推荐内联）")
    ap.add_argument("--title", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--insecure", action="store_true", help="跳过 TLS 证书校验")
    ap.add_argument("--content-type", default="text/html", help="文件 MIME")
    args = ap.parse_args()

    if args.version:
        print(f"html-uploader upload_skill.py version {__version__}")
        return 0

    # 确定适配器
    sys_default = ""
    cfg = {}
    cfg_path = SKILL_DIR / "config.json"
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    sys_default = args.system or cfg.get("default_system") or "htmlview-agent-api"
    adapter = read_adapter(sys_default)
    if not adapter["found"]:
        log(f"适配器文件不存在：{adapter['path']}")
        return 4

    # 系统地址
    env_base_name = sys_default.upper().replace("-", "_") + "_BASE_URL"
    base_url = (args.base_url
                or os.environ.get("HTMLVIEW_BASE_URL", "")
                or os.environ.get(env_base_name, "")
                or cfg.get("systems", {}).get(sys_default, {}).get("base_url", "")
                or adapter["base_url"])
    if not base_url:
        log("系统地址未提供（--base-url 或环境变量）。请先运行 scripts/check_config.py 完成预检并获取地址。")
        return 3

    # 密钥
    env_name = adapter["env_name"]
    key = args.key or os.environ.get(env_name, "")
    if adapter["auth_form"] not in ("none", "basic") and not key and env_name:
        log(f"密钥未提供（环境变量 {env_name}）。请先运行 scripts/check_config.py 完成预检并获取密钥。")
        return 3

    # 载荷：用户文件 或 技能自检打包
    if args.file:
        src = Path(args.file)
        if not src.is_file():
            log(f"文件不存在：{args.file}")
            return 1
        if src.suffix.lower() not in (".html", ".htm"):
            log(f"仅支持 .html/.htm，收到 {src.suffix}")
            return 1
        pkg = src.read_bytes()
        title = args.title or src.stem
        tags = args.tags
        summary = args.summary
    else:
        # 技能自上传（默认载荷 = SKILL.md + 适配器）
        pkg = _build_skill_package()
        title = args.title or "html-uploader 技能包（SKILL + 适配器）"
        tags = args.tags or "skill,html-uploader"
        summary = args.summary

    if len(pkg) > adapter["max_size"]:
        log(f"文件超过适配器上限 {adapter['max_size'] // (1024 * 1024)}MB")
        return 1

    client = Client(adapter, base_url, key, args.insecure)
    try:
        client.login()
        endpoint, method = discover(client)
        client.a["endpoint"] = endpoint
        client.a["method"] = method
        result = upload(client, pkg, title, tags, summary, args.content_type)
        fid = result.get("id") or result.get("url") or result.get("article_id") or ""
        log(f"上传成功：id/url={fid} 标题={result.get('title') or title}")
        if fid and str(fid).startswith("http"):
            log(f"访问地址：{fid}")
        elif fid:
            log(f"访问地址：{base_url.rstrip('/')}/reader.html?id={fid}")
        return 0
    except RuntimeError as e:
        log(f"失败：{e}")
        return 1


def _build_skill_package():
    """把 SKILL.md + adapters/*.md 打包为单个自包含 HTML（技能自我托管用）。"""
    import html as _html
    import time as _time
    skill_md = SKILL_DIR / "SKILL.md"
    adapters = sorted((SKILL_DIR / "adapters").glob("*.md")) if (SKILL_DIR / "adapters").is_dir() else []
    parts = [
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>html-uploader 技能包</title><style>",
        "body{max-width:900px;margin:0 auto;padding:32px 20px;color:#222;line-height:1.65}",
        "pre{background:#f6f7f8;border:1px solid #e3e5e8;padding:14px;overflow-x:auto}",
        "</style></head><body>",
        f"<h1>html-uploader 技能包</h1><p>打包时间：{_time.strftime('%Y-%m-%d %H:%M:%S')}</p>",
        "<h2>SKILL.md</h2><pre>", _html.escape(skill_md.read_text(encoding="utf-8")), "</pre>",
    ]
    for a in adapters:
        parts.append(f"<h2>adapters/{_html.escape(a.name)}</h2><pre>")
        parts.append(_html.escape(a.read_text(encoding="utf-8")))
        parts.append("</pre>")
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


if __name__ == "__main__":
    sys.exit(main())