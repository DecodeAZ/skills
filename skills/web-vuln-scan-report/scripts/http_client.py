"""统一 HTTP 层：requests → urllib（stdlib）→ curl（Schannel TLS）三级传输。

所有 skill 脚本统一通过本模块发请求，禁止直接 import requests —— 这是降级矩阵的实现点：
requests 不可用时脚本零改动，输出 JSON 的 http_backend 字段会标注实际后端。

请求统一模拟浏览器行为（授权扫描的自标识改为「报备源 IP」，不再用 UA 自标识，
避免被目标 WAF 按 UA / 请求头 / TLS 栈指纹降权或拉黑，实测案例：安恒玄武盾-云）：

  - navigate 档：GET/HEAD 文档请求 —— Sec-Fetch-Dest: document，无 Referer/Origin
    （等价于浏览器地址栏直达）
  - cors 档：POST 数据请求 / OPTIONS 预检 / TRACE 等非文档方法 —— Origin + Referer +
    Sec-Fetch-Dest: empty；带 data 时补 X-Requested-With 与 form-urlencoded Content-Type
    （等价于 jQuery $.ajax / 预检）
  - 跨源：调用方传入的 Origin 与目标不同源时，自动 Sec-Fetch-Site: cross-site，
    Referer 改为该 Origin，不补 X-Requested-With（CORS 反射探测保真）

TLS 指纹对策：python（requests/urllib = OpenSSL 栈）会被部分云 WAF 按栈指纹限流；
触发（连接被断 / 420 黑名单页 / 正文乱码）后自动粘性切换到 curl 兜底
（Windows 下 curl 走 Schannel TLS，指纹与浏览器同族）。

host 守卫：仅允许 http/https，拒绝 localhost、环回、私有和保留地址（SSRF 加固）。

对外接口：
    HTTP_BACKEND                 "requests" | "urllib"（主传输；curl 为兜底，见 Response.transport）
    fetch(url, ...) -> Response  带重试退避；SSL/连接类错误或 420/乱码自动切 curl；4xx/5xx 不算失败
    mask_ip / mask_uuid / mask   证据脱敏工具（IP 末段、32 位 UUID）
"""
from __future__ import annotations

import gzip
import ipaddress
import json
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

try:
    import requests  # noqa: F401
    import urllib3

    urllib3.disable_warnings()
    HTTP_BACKEND = "requests"
except ImportError:  # stdlib 降级模式
    requests = None
    HTTP_BACKEND = "urllib"

# 真实浏览器 UA（Chrome 126 / Win10 桌面版）。授权与限流纪律见 SKILL.md：报备源 IP，不在 UA 自标识。
DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
# 只通告本传输栈确定能解码的压缩（gzip/deflate 全后端原生支持；zstd/br 逐栈能力不一）
ACCEPT_ENCODING = "gzip, deflate"

_FORCE_CURL = False  # 粘性：python 栈被 WAF 拉黑（SSL 断连/420/乱码）后全程走 curl

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------- host 守卫（SSRF 加固） ----------

def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"仅允许 http/https，收到 scheme={parts.scheme!r}")
    host = (parts.hostname or "").strip().rstrip(".")
    if not host:
        raise ValueError("URL 缺少主机名")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError(f"拒绝 localhost/本地域名: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url  # 域名目标（授权范围由调用方约束）
    if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified):
        raise ValueError(f"拒绝环回/私有/保留地址: {host}")
    return url


# ---------- 浏览器档位头 ----------

def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def profile_headers(url: str, method: str, data: bytes | None,
                    extra: dict | None = None) -> dict:
    """按请求形态生成浏览器等价请求头。extra 内的显式头永远优先。"""
    method = method.upper()
    extra = dict(extra or {})
    origin = _origin(url)
    ext_origin = extra.get("Origin") or extra.get("origin")
    cross = bool(ext_origin) and ext_origin != origin

    if method in ("GET", "HEAD") and not data and not cross:  # navigate 档
        hdrs = {
            "User-Agent": DEFAULT_UA,
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,*/*;q=0.8"),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": ACCEPT_ENCODING,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Connection": "keep-alive",
        }
        if method == "GET":
            hdrs["Upgrade-Insecure-Requests"] = "1"
        hdrs.update(extra)
        return hdrs

    # cors 档（POST 数据 / OPTIONS / TRACE / 跨源）
    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": ("application/json, text/javascript, */*; q=0.01"
                   if (data or method == "POST") else "*/*"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": ACCEPT_ENCODING,
        "Origin": ext_origin or origin,
        "Referer": (ext_origin or origin) + "/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors" if method != "OPTIONS" else "cors-preflight",
        "Sec-Fetch-Site": "cross-site" if cross else "same-origin",
        "Connection": "keep-alive",
    }
    if data and method == "POST" and not cross:  # jQuery $.ajax 同款
        hdrs["X-Requested-With"] = "XMLHttpRequest"
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    hdrs.update(extra)
    return hdrs


# ---------- Response ----------

class Response:
    """最小响应对象，三个后端共用同一接口。"""

    def __init__(self, status: int, headers: dict, content: bytes, url: str,
                 transport: str = HTTP_BACKEND):
        self.status_code = status
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.headers = _HeaderMap(self._headers)
        self.content = content
        self.text = content.decode("utf-8", "replace")
        self.url = url
        self.transport = transport

    def json(self):
        return json.loads(self.text)

    def close(self):  # 保持与 requests.Response 兼容
        pass


class _HeaderMap:
    def __init__(self, lower: dict):
        self._d = lower

    def get(self, key: str, default: str = ""):
        return self._d.get(key.lower(), default)

    def items(self):
        return self._d.items()


# ---------- 正文健全性（压缩协商失败的乱码检测） ----------

def _garbled(r: Response) -> bool:
    ct = r.headers.get("content-type", "")
    if not any(x in ct for x in ("text/", "json", "javascript", "xml")):
        return False
    head = r.text[:4000]
    if head.count("\ufffd") > 20:
        return True
    if len(r.content) > 500:
        if ("html" in ct or "xml" in ct) and "<" not in head:
            return True
        if "json" in ct and not any(c in head for c in "{}["):
            return True
    return False


# ---------- 传输 1：requests ----------

def _requests_once(url: str, hdrs: dict, timeout: float, method: str, data) -> Response:
    resp = requests.request(method, url, headers=hdrs, data=data, timeout=timeout,
                            verify=False, allow_redirects=False)
    r = Response(resp.status_code, dict(resp.headers), resp.content, resp.url, "requests")
    if (r.status_code == 420 or _garbled(r)) and hdrs.get("Accept-Encoding") != "identity":
        # 压缩协商失败兜底：强制 identity 重试一次
        hdrs2 = {**hdrs, "Accept-Encoding": "identity"}
        resp = requests.request(method, url, headers=hdrs2, data=data, timeout=timeout,
                                verify=False, allow_redirects=False)
        r = Response(resp.status_code, dict(resp.headers), resp.content, resp.url, "requests")
    return r


# ---------- 传输 2：urllib（stdlib），含手动解压 ----------

def _decode_body(content: bytes, headers: dict) -> bytes:
    enc = (headers.get("Content-Encoding") or headers.get("content-encoding") or "").lower()
    try:
        if enc == "gzip" and content[:2] == b"\x1f\x8b":
            return gzip.decompress(content)
        if enc == "deflate":
            try:
                return zlib.decompress(content)
            except zlib.error:
                return zlib.decompress(content, -zlib.MAX_WBITS)
    except OSError:
        return content
    return content


def _urllib_fetch(url: str, headers: dict, timeout: float, method: str, data) -> Response:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read()
            hdrs = dict(resp.headers)
            return Response(resp.status, hdrs, _decode_body(raw, hdrs), resp.geturl(), "urllib")
    except urllib.error.HTTPError as e:  # 4xx/5xx 是有效探测结果，不视为异常
        raw = e.read() or b""
        hdrs = dict(e.headers or {})
        return Response(e.code, hdrs, _decode_body(raw, hdrs), url, "urllib")


# ---------- 传输 3：curl 兜底（Windows = Schannel TLS，指纹与浏览器同族） ----------

def _curl_fetch(url: str, hdrs: dict, timeout: float, method: str, data) -> Response:
    global _FORCE_CURL
    cmd = ["curl", "-sS", "-i", "--compressed",
           "--connect-timeout", str(max(3, int(timeout) // 3)),
           "--retry", "2", "--retry-delay", "1",
           "--max-time", str(int(timeout))]
    if method == "HEAD":
        cmd.append("-I")
    elif method != "GET":
        cmd += ["-X", method]
    for k, v in hdrs.items():
        cmd += ["-H", f"{k}: {v}"]
    if data:
        cmd += ["--data-binary", data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if not p.stdout:
        raise ConnectionError(f"curl 无输出: {p.stderr.decode('utf-8', 'replace')[:200]}")
    head, sep, body = p.stdout.partition(b"\r\n\r\n")
    if not sep:
        head, sep, body = p.stdout.partition(b"\n\n")
    status, resp_headers = 0, {}
    for line in head.splitlines():
        line = line.decode("utf-8", "replace")
        m = re.match(r"HTTP/[\d.]+\s+(\d{3})", line)
        if m:
            status = int(m.group(1))
        elif ":" in line and not line.startswith("HTTP/"):
            k, _, v = line.partition(":")
            resp_headers[k.strip()] = v.strip()
    decoded = _decode_body(body if sep else p.stdout, resp_headers)  # --compressed 已解压，此处为双保险
    if status == 0:
        raise ConnectionError("curl 响应无法解析状态行")
    return Response(status, resp_headers, decoded, url, "curl")


# ---------- 对外入口 ----------

def fetch(
    url: str,
    headers: dict | None = None,
    timeout: float = 15.0,
    method: str = "GET",
    data: bytes | None = None,
    retries: int = 2,
    retry_delay: float = 1.5,
) -> Response:
    """带重试的只读探测请求。SSL/连接类错误退避后重试；HTTP 状态码错误不重试。

    触发 WAF 指纹限流（连接被断 / 420 / 正文乱码）时自动切 curl 兜底并粘性生效。
    """
    global _FORCE_CURL
    validate_url(url)
    hdrs = profile_headers(url, method, data, headers)

    def via_curl() -> Response:
        global _FORCE_CURL
        r = _curl_fetch(url, hdrs, timeout, method, data)
        if r.status_code not in (0, 420):
            _FORCE_CURL = True  # curl 可达 = python 栈已被拉黑，后续直接走 curl
        return r

    if _FORCE_CURL:
        return _curl_fetch(url, hdrs, timeout, method, data)

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if HTTP_BACKEND == "requests":
                r = _requests_once(url, hdrs, timeout, method, data)
            else:
                r = _urllib_fetch(url, hdrs, timeout, method, data)
            if r.status_code == 420 or _garbled(r):  # WAF 黑名单页 / 乱码 → curl 兜底
                return via_curl()
            return r
        except (ssl.SSLError, ConnectionError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(retry_delay * (attempt + 1))
    _FORCE_CURL = True  # python 栈被 WAF 断连 → 粘性切换
    return _curl_fetch(url, hdrs, timeout, method, data)


# ---------- 证据脱敏 ----------

def mask_ip(text: str) -> str:
    return re.sub(r"(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}", r"\1.x", text)


def mask_uuid(text: str) -> str:
    return re.sub(r"\b[0-9a-f]{32}\b", "<uuid>", text)


def mask(text: str, limit: int = 160) -> str:
    return mask_uuid(mask_ip(text))[:limit].replace("\n", " ").strip()
