"""只读路径探测：串行请求、固定速率，规避目标站点对高频短连接的 TLS 异常。

用法：python pathprobe.py <base_url> <wordlist> [--delay 0.4] [--out FILE]
仅发送 GET，记录状态码/长度/跳转；这是路径枚举的主路径（dirsearch 仅作可选对照）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import http_client as hc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("wordlist")
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--timeout", type=float, default=15)
    ap.add_argument("--out", default="reports/pathprobe.json")
    args = ap.parse_args()

    words = [
        line.strip()
        for line in Path(args.wordlist).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    base = args.base if args.base.endswith("/") else args.base + "/"
    results = []
    for word in words:
        url = base + word.lstrip("/")
        record: dict = {"path": word}
        try:
            resp = hc.fetch(url, timeout=args.timeout)
            record.update(
                status=resp.status_code,
                length=len(resp.content),
                content_type=resp.headers.get("Content-Type", ""),
                location=resp.headers.get("Location", ""),
                server=resp.headers.get("Server", ""),
            )
            if resp.status_code != 404:
                record["body_snippet"] = hc.mask(resp.text, 160)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        results.append(record)
        time.sleep(args.delay)

    interesting = [r for r in results if r.get("status") not in (None, 404)]
    out = {
        "base": base,
        "http_backend": hc.HTTP_BACKEND,
        "tested": len(results),
        "non_404": len(interesting),
        "results": results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    for r in interesting:
        print(f"{r.get('status')}  {r['path']:32} {r.get('length', ''):>6}  {r.get('content_type', '')[:40]}")
    print(f"\n[tested] {len(results)}  [non-404] {len(interesting)}  -> {args.out}  [backend] {hc.HTTP_BACKEND}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
