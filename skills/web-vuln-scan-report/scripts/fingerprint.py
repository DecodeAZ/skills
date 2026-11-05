"""只读指纹脚本：抓取首页与静态产物，提取服务端与前端组件版本。

用法：python fingerprint.py <base_url> [--cache DIR] [--refresh]
仅做 GET 请求；已下载产物默认复用本地缓存，避免重复请求目标站点。
版本串规则见 references/fingerprint-rules.md；HTTP 层走 http_client（requests/urllib 自动降级）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import http_client as hc

# (字段名, 正则, 仅在该文件名包含 scope 时应用, 说明)
PATTERNS = [
    ("vue", r'var\s+er="(2\.\d+\.\d+)"', "chunk-libs", "Vue 2 内核版本串"),
    ("vue_router", r'Ht\.version="([\d.]+)"', "chunk-libs", "vue-router"),
    ("vuex", r'Store:\w+,install:\w+,version:"([\d.]+)"', "chunk-libs", "Vuex"),
    ("vue_i18n", r'K\.version="([\d.]+)"', "chunk-libs", "vue-i18n"),
    ("axios", r'\[Axios v([\d.]+)\]', "chunk-libs", "axios 调试串"),
    ("core_js", r'version:"(3\.\d+\.\d+)",mode:', "chunk-libs", "core-js 3"),
    ("core_js_2", r'\{version:"(2\.6\.\d+)"\}', "chunk-libs", "打包内含 core-js 2 遗留副本"),
    ("nprogress", r'n=\{version:"([\d.]+)"\}', "chunk-libs", "NProgress"),
    ("element_ui", r'version:"(2\.\d+\.\d+)"', "chunk-elementUI", "Element UI"),
]

HEADER_KEYS = {
    "server", "content-type", "content-security-policy", "strict-transport-security",
    "x-frame-options", "x-content-type-options", "referrer-policy",
    "permissions-policy", "via", "x-powered-by",
}


def load_asset(url: str, cache: Path, refresh: bool):
    cache.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("?")[0].rsplit("/", 1)[-1]) or "asset"
    path = cache / name
    if path.exists() and not refresh:
        return path.read_bytes(), "cached", True
    resp = hc.fetch(url, timeout=40)
    path.write_bytes(resp.content)
    return resp.content, str(resp.status_code), False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--refresh", action="store_true", help="忽略本地缓存重新下载")
    args = ap.parse_args()

    cache = Path(args.cache)
    index = hc.fetch(args.url, timeout=30)
    html = index.text

    report: dict = {
        "target": args.url,
        "http_backend": hc.HTTP_BACKEND,
        "status": index.status_code,
        "server": {
            "headers": {k: v for k, v in index.headers.items() if k.lower() in HEADER_KEYS},
            "nginx_version": None,
        },
        "frontend": {},
        "api": {"base_url": None, "paths": []},
        "assets": [],
    }

    # nginx 版本常在 404 页回显（server_tokens 未关闭时）
    try:
        probe = hc.fetch(urljoin(args.url, "fp-probe-" + "x" * 6), timeout=15)
        m = re.search(r"nginx/([\d.]+)", probe.text) or re.search(
            r"nginx/([\d.]+)", probe.headers.get("server", ""))
        if m:
            report["server"]["nginx_version"] = m.group(1)
        report["server"]["not_found_404"] = probe.status_code
    except Exception as exc:
        report["server"]["probe_error"] = f"{type(exc).__name__}: {exc}"

    refs, seen = [], set()
    for ref in re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html):
        absolute = urljoin(args.url, ref)
        if absolute not in seen:
            seen.add(absolute)
            refs.append(absolute)

    for url in refs:
        name = url.split("/")[-1]
        entry: dict = {"url": name}
        try:
            body, st, from_cache = load_asset(url, cache, args.refresh)
            entry.update({"status": st, "bytes": len(body),
                          "sha256": hashlib.sha256(body).hexdigest()[:16],
                          "from_cache": from_cache})
            text = body.decode("utf-8", "replace")
            matches: dict = {}
            for key, pattern, scope, _desc in PATTERNS:
                if scope not in name:
                    continue
                m = re.search(pattern, text)
                if m:
                    matches[key] = m.group(1)
            if "SockJS" in text:
                matches["sockjs"] = "present"
            if "stompClient" in text or "Stomp.over" in text:
                matches["stomp"] = "present"
            if name.startswith("Cesium") and "Cesium" in text[:400]:
                cm = re.search(r"Version\s+([\d.]+)", text[:800])
                if cm:
                    matches["cesium"] = cm.group(1)
            entry["matches"] = matches
            for key, value in matches.items():
                if key not in {"sockjs", "stomp"}:
                    report["frontend"][key] = value
            for base in re.findall(r'baseURL:"([^"]{1,60})"', text):
                report["api"]["base_url"] = base
            for path in re.findall(r'url:"(/[A-Za-z0-9_./-]{2,50})"', text):
                if path not in report["api"]["paths"]:
                    report["api"]["paths"].append(path)
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report["assets"].append(entry)

    report["api"]["paths"].sort()
    report["frontend"] = dict(sorted(report["frontend"].items()))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
