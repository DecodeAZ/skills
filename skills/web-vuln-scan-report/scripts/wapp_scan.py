"""可选对照工具：python-Wappalyzer 通用技术栈识别。

用法：python wapp_scan.py <url> [url ...]
依赖 python-Wappalyzer + setuptools<81（可选依赖）。未安装时退出码 3，
按 SKILL.md 降级矩阵跳过本工具，仅保留自建指纹结果即可。

注意：请求统一走 http_client（浏览器档位头 + curl 兜底），再本地构造 WebPage 分析；
禁止用 WebPage.new_from_url —— 其内部 requests.get 不带头，会裸发 python-requests UA。
"""
from __future__ import annotations

import json
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    from Wappalyzer import Wappalyzer, WebPage
except ImportError:
    print("[skip] python-Wappalyzer 未安装（可选依赖），跳过通用技术栈对照。")
    print("       安装：pip install python-Wappalyzer==0.3.1 'setuptools<81'")
    sys.exit(3)

import http_client as hc


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: wapp_scan.py <url> [url ...]")
        return 2
    wapp = Wappalyzer.latest()
    total = 0
    for url in sys.argv[1:]:
        try:
            resp = hc.fetch(url, timeout=25)
            # 本地构造 WebPage（等价 new_from_response），请求层不再交由 Wappalyzer 发出
            page = WebPage(str(resp.url), html=resp.text, headers=dict(resp.headers.items())
                           if hasattr(resp.headers, "items") else dict(resp.headers))
            result = wapp.analyze_with_versions_and_categories(page)
        except Exception as exc:
            print(f"[error] {url}: {type(exc).__name__}: {exc}")
            continue
        print(f"=== {url}")
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        total += len(result)
    print(f"\n[detected] {total} technology hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
