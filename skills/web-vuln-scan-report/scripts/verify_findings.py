"""F-XX 复验脚本模板（只读、可重复、自动脱敏）。

用途：交付给客户/运维，在修复前后各跑一次，用同一套判定标准确认漏洞是否关闭。
本文件按「通用模板 + 站点定制检查」组织：CHECKS 列表按目标站点改造，
判定标准与 checklists/ 清单保持一致。

用法：
  python verify_findings.py --base https://host:port/dev-sys-api/ [--out reports/verify.json]
退出码：0 = 全部已修复；10 = 仍有 OPEN 项；2 = 参数/连通性错误。

约束：只发 GET / Range 请求；默认串行 + 间隔；证据自动脱敏（IP 末段、32 位 UUID）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import http_client as hc


class Client:
    def __init__(self, base: str, delay: float = 0.5, timeout: float = 15):
        self.base = base if base.endswith("/") else base + "/"
        parts = urlsplit(self.base)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.delay = delay
        self.timeout = timeout

    def api_url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    def get(self, url: str, headers: dict | None = None):
        time.sleep(self.delay)
        return hc.fetch(url, headers=headers, timeout=self.timeout)


# ---------- 站点定制检查（按目标改造这一段） ----------

def check_public_config(c: Client) -> dict:
    """F-09 类：公开配置接口未鉴权。OPEN = 200 且含敏感字段。"""
    r = c.get(c.api_url("common/config/data"))
    exposed = r.status_code == 200 and "appDownload" in r.text[:800]
    return {
        "id": "F-09", "name": "公共配置接口未鉴权",
        "url": c.api_url("common/config/data").replace(c.origin, ""),
        "status": r.status_code, "verdict": "OPEN" if exposed else "FIXED",
        "evidence": hc.mask(r.text[:300]),
        "app_download": (r.json().get("data", {}) or {}).get("appDownload") if exposed else None,
    }


def check_gis_config(c: Client) -> dict:
    """F-10 类：GIS 配置未鉴权（瓦片服务器地址/坐标）。"""
    r = c.get(c.api_url("common/config/gis/data"))
    exposed = r.status_code == 200 and ("offlineSatellite" in r.text or "addressLasa" in r.text)
    return {
        "id": "F-10", "name": "GIS 配置未鉴权（瓦片服务器地址/坐标）",
        "url": c.api_url("common/config/gis/data").replace(c.origin, ""),
        "status": r.status_code, "verdict": "OPEN" if exposed else "FIXED",
        "evidence": hc.mask(r.text[:300]),
    }


def check_object_storage(c: Client, apk_path: str | None) -> dict:
    """F-11 类：对象存储匿名可读。用 4 字节 Range 请求确认，不下载正文。"""
    if not apk_path:
        return {"id": "F-11", "name": "对象存储匿名可读", "verdict": "SKIP",
                "evidence": "上游配置接口未取得可下载路径（可能已修复）"}
    url = c.origin + apk_path
    r = c.get(url, headers={"Range": "bytes=0-3"})
    content_range = r.headers.get("Content-Range", "")
    exposed = r.status_code == 206 and bool(content_range)
    return {
        "id": "F-11", "name": "对象存储匿名可读（APK 可下载）",
        "url": url.replace(c.origin, ""),
        "status": r.status_code, "verdict": "OPEN" if exposed else "FIXED",
        "evidence": hc.mask(f"Content-Range={content_range} magic={r.content[:4].hex()}"),
        "total_bytes": content_range.split("/")[-1] if content_range else None,
    }


def check_sockjs(c: Client) -> dict:
    """F-12 类：SockJS 任意 Origin / cookie_needed。"""
    r = c.get(c.api_url("socket/info"), headers={"Origin": "https://verify.example.invalid"})
    try:
        data = r.json()
    except Exception:
        data = {}
    wildcard = any("*" in str(o) for o in data.get("origins", []))
    exposed = r.status_code == 200 and wildcard
    return {
        "id": "F-12", "name": "SockJS 任意 Origin / cookie_needed",
        "url": c.api_url("socket/info").replace(c.origin, ""),
        "status": r.status_code, "verdict": "OPEN" if exposed else "FIXED",
        "evidence": hc.mask(json.dumps(data, ensure_ascii=False)),
    }


def check_control(c: Client) -> dict:
    """对照组：受保护接口应当 401，用于证明鉴权链路本身正常。"""
    r = c.get(c.api_url("sys/config/data"))
    return {
        "id": "CTRL", "name": "对照组：受保护接口应 401",
        "url": c.api_url("sys/config/data").replace(c.origin, ""),
        "status": r.status_code,
        "verdict": "PASS" if r.status_code == 401 else "UNEXPECTED",
        "evidence": "401 表示鉴权链路正常" if r.status_code == 401 else hc.mask(r.text[:120]),
    }


CHECK_ORDER = [check_public_config, check_gis_config, check_object_storage, check_sockjs, check_control]
# 注意：check_object_storage 依赖 F-09 返回的 app_download，实际执行顺序见 run()


def run(c: Client):
    rows = []
    f09 = check_public_config(c)
    rows.append(f09)
    rows.append(check_gis_config(c))
    rows.append(check_object_storage(c, f09.get("app_download")))
    rows.append(check_sockjs(c))
    rows.append(check_control(c))
    return rows


def print_table(rows: list[dict]) -> None:
    icon = {"OPEN": "[OPEN] ", "FIXED": "[FIXED]", "SKIP": "[SKIP] ",
            "PASS": "[PASS] ", "UNEXPECTED": "[WARN] "}
    for row in rows:
        print(f"{icon.get(row['verdict'], '[????]')} {row['id']:4} {row['name']}")
        print(f"         URL    : {row.get('url', '-')}")
        print(f"         状态码 : {row.get('status', '-')}")
        print(f"         证据   : {row.get('evidence', '-')}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="例如 https://host:port/dev-sys-api/")
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--timeout", type=float, default=15)
    ap.add_argument("--out", default="reports/verify-findings.json")
    args = ap.parse_args()

    c = Client(args.base, args.delay, args.timeout)
    try:
        c.get(c.base)  # 连通性探测
    except Exception as exc:
        print(f"[error] 无法连接 {args.base}: {type(exc).__name__}: {exc}")
        return 2

    rows = run(c)
    print("\n=== 复验结果 ===\n")
    print_table(rows)

    out = {
        "base": args.base,
        "http_backend": hc.HTTP_BACKEND,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": rows,
        "open": [r["id"] for r in rows if r["verdict"] == "OPEN"],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"结果已写入 {out_path}")
    print(f"仍为 OPEN 的项：{out['open'] or '无'}")

    return 10 if out["open"] else 0


if __name__ == "__main__":
    sys.exit(main())
