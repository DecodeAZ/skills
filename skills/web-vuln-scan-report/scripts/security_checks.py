"""额外网站测试：9 类只读安全检查，输出 PASS/WARN/FAIL/SKIP/INFO 判定。

用法：
  python security_checks.py --url https://host:port/service/ [--base https://host:port/api/]
      [--checks headers,version,tls,cookie,sensitive,methods,cors,listing,spring]
      [--delay 0.4] [--out reports/security-checks.json]

设计约定：
  * 串行限速（默认 0.4s 间隔），SSL/连接错误退避重试一次（http_client 内置）；
  * 证据自动脱敏（IP 末段、32 位 UUID）；
  * 可选模块缺前置（如 openssl 缺失、无登录态）时判 SKIP 而不是 FAIL；
  * 退出码：0 正常；5 存在 FAIL 项；2 连接失败。
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import http_client as hc

ALL_CHECKS = ["headers", "version", "tls", "cookie", "sensitive", "methods", "cors", "listing", "spring"]

SENSITIVE_PATHS = [
    ".git/HEAD", ".git/config", ".env", ".DS_Store", ".svn/entries",
    "backup.zip", "backup.tar.gz", "dump.sql", "database.sql",
    "composer.lock", "package.json", "WEB-INF/web.xml",
]

DANGEROUS_200 = {".git/HEAD", ".git/config", ".env", "id_rsa", "dump.sql", "database.sql", "backup.zip", "backup.tar.gz"}

SENSITIVE_PATTERNS = {
    ".git/HEAD": re.compile(r"ref:\s*refs/", re.I),
    ".git/config": re.compile(r"\[core\]", re.I),
    ".env": re.compile(r"^[A-Z_]+=", re.M),
    "id_rsa": re.compile(r"BEGIN (RSA |OPENSSH )?PRIVATE KEY"),
}


def result(cid: str, name: str, verdict: str, evidence: str, recommendation: str = "", **extra) -> dict:
    row = {"id": cid, "name": name, "verdict": verdict,
           "evidence": hc.mask(evidence, 240), "recommendation": recommendation}
    row.update(extra)
    return row


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


# ---------- 1. HTTP 安全响应头 ----------

def check_headers(url: str, delay: float) -> dict:
    r = hc.fetch(url, timeout=15)
    time.sleep(delay)
    required = {
        "strict-transport-security": "HSTS（强制 HTTPS）",
        "content-security-policy": "CSP（内容安全策略）",
        "x-frame-options": "X-Frame-Options（防点击劫持）",
        "x-content-type-options": "X-Content-Type-Options（防 MIME 嗅探）",
        "referrer-policy": "Referrer-Policy",
        "permissions-policy": "Permissions-Policy",
    }
    missing = [label for key, label in required.items() if not r.headers.get(key)]
    present = {k: r.headers.get(k) for k in required if r.headers.get(k)}
    verdict = "PASS" if not missing else ("WARN" if len(missing) <= 2 else "FAIL")
    return result("H-01", "HTTP 安全响应头", verdict,
                  f"缺失：{', '.join(missing) if missing else '无'}；已有：{json.dumps(present, ensure_ascii=False)[:200]}",
                  "补齐 HSTS / CSP / XFO / XCTO；CSP 至少 frame-ancestors 'self'")


# ---------- 2. 版本回显 ----------

def check_version(url: str, delay: float) -> dict:
    probe_url = urljoin(url if url.endswith("/") else url + "/", "sc-probe-" + "x" * 6)
    r = hc.fetch(probe_url, timeout=15)
    time.sleep(delay)
    m = (re.search(r"(nginx|apache|IIS|Tomcat)[/\s]([\d.]+)", r.text, re.I)
         or re.search(r"(nginx|apache|IIS|Tomcat)[/\s]([\d.]+)", r.headers.get("server", ""), re.I))
    if m:
        return result("H-02", "服务器版本回显", "WARN",
                      f"404 页/响应头泄露 {m.group(0)}",
                      "nginx 加 server_tokens off；应用层去掉 Server 版本")
    return result("H-02", "服务器版本回显", "PASS", "未发现版本回显", "")


# ---------- 3. TLS 协议与证书（依赖 openssl CLI，缺失则 SKIP） ----------

def check_tls(url: str, delay: float) -> dict:
    p = urlsplit(url)
    host, port = p.hostname, p.port or 443
    try:
        subprocess.run(["openssl", "version"], capture_output=True, check=True)
    except Exception:
        return result("H-03", "TLS 协议与证书", "SKIP", "本机无 openssl CLI，跳过", "安装 openssl 后重跑本项")

    def run(args: list[str]) -> str:
        proc = subprocess.run(["openssl", "s_client", "-connect", f"{host}:{port}",
                               "-servername", host] + args,
                              input=b"", capture_output=True, timeout=20)
        return (proc.stdout + proc.stderr).decode("utf-8", "replace")

    findings, verdict = [], "PASS"
    for proto in ("tls1", "tls1_1"):
        out = run([f"-{proto}"])
        # 本机 openssl 不支持旧协议时会报 "no protocols available"，属环境限制而非目标配置
        if "no protocols available" in out:
            findings.append(f"{proto}: 本机 openssl 不支持，无法判定")
        elif "Cipher is (NONE)" in out or "alert" in out.lower():
            findings.append(f"{proto}: 已拒绝（好）")
        else:
            findings.append(f"{proto}: 仍可协商（差）")
            verdict = "FAIL"
    out = run(["-alpn", "h2,http/1.1"])
    alpn = "h2" if "ALPN protocol: h2" in out else ("http/1.1" if "ALPN protocol" in out else "未知")
    findings.append(f"ALPN: {alpn}")
    cert = subprocess.run(["openssl", "s_client", "-connect", f"{host}:{port}", "-servername", host],
                          input=b"", capture_output=True, timeout=20).stdout
    try:
        x509 = subprocess.run(["openssl", "x509", "-noout", "-subject", "-dates"],
                              input=cert, capture_output=True, timeout=10).stdout.decode()
        m = re.search(r"notAfter=(.+)", x509)
        if m:
            expire = datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (expire - datetime.now(timezone.utc)).days
            findings.append(f"证书剩余 {days} 天")
            if days < 21:
                verdict = "WARN" if verdict == "PASS" else verdict
        else:
            findings.append("证书解析失败")
    except Exception as exc:
        findings.append(f"证书解析异常 {type(exc).__name__}")
    time.sleep(delay)
    return result("H-03", "TLS 协议与证书", verdict, "; ".join(findings),
                  "禁用 TLS1.0/1.1，证书到期前 30 天续签")


# ---------- 4. Cookie 安全属性 ----------

def check_cookie(url: str, delay: float) -> dict:
    r = hc.fetch(url, timeout=15)
    time.sleep(delay)
    cookies = [v for k, v in r.headers.items() if k.lower() == "set-cookie"]
    if not cookies:
        return result("H-04", "Cookie 安全属性", "INFO",
                      "首页未下发 Set-Cookie；会话 Cookie 需登录态复查",
                      "用测试账号登录后复跑本项")
    problems = []
    for ck in cookies:
        low = ck.lower()
        if "httponly" not in low:
            problems.append("缺 HttpOnly")
        if "secure" not in low:
            problems.append("缺 Secure")
        if "samesite" not in low:
            problems.append("缺 SameSite")
    verdict = "FAIL" if problems else "PASS"
    return result("H-04", "Cookie 安全属性", verdict,
                  "; ".join(problems) or "属性齐全",
                  "服务端下发 HttpOnly; Secure; SameSite=Strict")


# ---------- 5. 敏感文件探测 ----------

def check_sensitive(url: str, delay: float) -> dict:
    base = url if url.endswith("/") else url + "/"
    hits, blocked, misses = [], 0, 0
    for path in SENSITIVE_PATHS:
        try:
            r = hc.fetch(urljoin(base, path), timeout=12)
        except Exception:
            continue
        time.sleep(delay)
        if r.status_code == 200 and len(r.content) > 0:
            pat = SENSITIVE_PATTERNS.get(path)
            if pat and not pat.search(r.text):
                misses += 1
                continue
            hits.append(f"{path} → 200（{len(r.content)}B）")
        elif r.status_code == 403:
            blocked += 1
    if hits:
        verdict = "FAIL" if any(h.split(" →")[0] in DANGEROUS_200 for h in hits) else "WARN"
    else:
        verdict = "PASS"
    note = f"；另有 {blocked} 个路径被 403 拦截（说明有防护规则）" if blocked else ""
    return result("H-05", "敏感文件探测", verdict,
                  ("；".join(hits) if hits else "未发现可读敏感文件") + note,
                  "Web 根禁放 .git/.env/备份文件；对象存储路径不对外")


# ---------- 6. HTTP 方法 ----------

def check_methods(url: str, delay: float) -> dict:
    r = hc.fetch(url, timeout=12, method="OPTIONS")
    time.sleep(delay)
    allow = r.headers.get("allow") or r.headers.get("access-control-allow-methods") or ""
    trace = hc.fetch(url, timeout=12, method="TRACE")
    time.sleep(delay)
    findings = [f"OPTIONS Allow={allow or r.status_code}"]
    verdict = "PASS"
    if trace.status_code == 200 and "TRACE" in trace.text.upper()[:200]:
        findings.append("TRACE 回显开启（可被 XST 利用）")
        verdict = "FAIL"
    if allow and ("PATCH" in allow and "PUT" in allow and "DELETE" in allow):
        findings.append("写方法全量放开，建议收敛")
        verdict = "WARN" if verdict == "PASS" else verdict
    return result("H-06", "HTTP 方法", verdict, "; ".join(findings),
                  "只保留 GET/HEAD/POST/PUT/DELETE 实际使用的方法，禁用 TRACE")


# ---------- 7. CORS 反射 ----------

def check_cors(url: str, delay: float) -> dict:
    evil = "https://cors-probe.example"
    r1 = hc.fetch(url, timeout=12, headers={"Origin": evil})
    time.sleep(delay)
    acao = r1.headers.get("access-control-allow-origin", "")
    acac = r1.headers.get("access-control-allow-credentials", "")
    r2 = hc.fetch(url, timeout=12, method="OPTIONS",
                  headers={"Origin": evil, "Access-Control-Request-Method": "POST"})
    time.sleep(delay)
    p_acao = r2.headers.get("access-control-allow-origin", "")
    findings = [f"简单请求 ACAO={acao or '无'} ACAC={acac or '无'}",
                f"预检 ACAO={p_acao or '无'}"]
    if acao == evil and acac.lower() == "true":
        return result("H-07", "CORS 反射", "FAIL", "; ".join(findings),
                      "ACAO 不得反射任意 Origin 且携带凭据；改显式白名单")
    if p_acao == evil:
        return result("H-07", "CORS 反射", "WARN", "; ".join(findings),
                      "预检反射了任意 Origin，改显式白名单")
    return result("H-07", "CORS 反射", "PASS", "; ".join(findings),
                  "Origin 白名单保持显式枚举")


# ---------- 8. 目录列表 ----------

def check_listing(url: str, delay: float) -> dict:
    base = url if url.endswith("/") else url + "/"
    hits = []
    for path in ("", "static/", "assets/", "img/"):
        try:
            r = hc.fetch(urljoin(base, path), timeout=12)
        except Exception:
            continue
        time.sleep(delay)
        if r.status_code == 200 and ("Index of /" in r.text or "Directory listing for" in r.text):
            hits.append("/" + path)
    if hits:
        return result("H-08", "目录列表", "FAIL", f"开启目录列举：{', '.join(hits)}",
                      "nginx 加 autoindex off;（默认即为 off，排查显式开启）")
    return result("H-08", "目录列表", "PASS", "未发现目录列举", "")


# ---------- 9. Spring 专项组 ----------

def check_spring(url: str, base: str | None, delay: float) -> dict:
    if not base:
        return result("H-09", "Spring 专项", "SKIP",
                      "未提供 --base（API 前缀），跳过；可先用 fingerprint.py 的 api.base_url",
                      "提供 API 前缀后重跑")
    api = base if base.endswith("/") else base + "/"
    findings, verdict = [], "PASS"

    for path in ("actuator", "actuator/health", "actuator/env", "actuator/heapdump",
                 "v3/api-docs", "v2/api-docs", "doc.html"):
        try:
            r = hc.fetch(urljoin(api, path), timeout=10)
        except Exception:
            continue
        time.sleep(delay)
        if r.status_code == 200:
            findings.append(f"/{path} → 200（{'heapdump 暴露!' if 'heapdump' in path else '文档/端点暴露'}）")
            verdict = "FAIL"
        elif r.status_code in (401, 403):
            findings.append(f"/{path} → {r.status_code}（已防护）")

    try:
        r = hc.fetch(urljoin(api, "socket/info"), timeout=10,
                     headers={"Origin": "https://cors-probe.example"})
        time.sleep(delay)
        if r.status_code == 200:
            try:
                info = r.json()
                origins = info.get("origins", [])
                if any("*" in str(o) for o in origins):
                    findings.append(f"socket/info origins={origins}（任意 Origin + cookie_needed={info.get('cookie_needed')}）")
                    verdict = "FAIL" if verdict != "FAIL" else verdict
                else:
                    findings.append(f"socket/info origins={origins}")
            except Exception:
                findings.append("socket/info 返回非 JSON")
        elif r.status_code == 404:
            findings.append("socket/info 不存在")
    except Exception:
        pass

    try:
        r = hc.fetch(urljoin(api, "error"), timeout=10)
        time.sleep(delay)
        try:
            body = r.json()
            if str(body.get("status")) not in (None, "404", "500", ""):
                findings.append(f"/error 返回非标准 status={body.get('status')}")
                verdict = "WARN" if verdict == "PASS" else verdict
        except Exception:
            if "whitelabel" in r.text.lower():
                findings.append("Whitelabel Error Page 对外可见")
                verdict = "WARN" if verdict == "PASS" else verdict
    except Exception:
        pass

    return result("H-09", "Spring 专项", verdict,
                  "; ".join(findings) or "未发现暴露端点",
                  "actuator 仅暴露 health；swagger 文档生产关闭；SockJS 收敛 allowedOrigins")


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="站点入口，如 https://host:port/service/")
    ap.add_argument("--base", default=None, help="API 前缀（Spring 专项用），如 https://host:port/dev-sys-api/")
    ap.add_argument("--checks", default="all", help="逗号分隔，默认 all")
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--timeout", type=float, default=15)
    ap.add_argument("--out", default="reports/security-checks.json")
    args = ap.parse_args()

    want = ALL_CHECKS if args.checks == "all" else [c for c in args.checks.split(",") if c in ALL_CHECKS]
    unknown = set(args.checks.split(",")) - set(ALL_CHECKS) - {"all"}
    if unknown:
        print(f"[warn] 未知检查项已忽略：{', '.join(sorted(unknown))}")

    try:
        hc.fetch(args.url, timeout=args.timeout)  # 连通性探测
    except Exception as exc:
        print(f"[error] 无法连接 {args.url}: {type(exc).__name__}: {exc}")
        return 2

    runners = {
        "headers": lambda: check_headers(args.url, args.delay),
        "version": lambda: check_version(args.url, args.delay),
        "tls": lambda: check_tls(args.url, args.delay),
        "cookie": lambda: check_cookie(args.url, args.delay),
        "sensitive": lambda: check_sensitive(args.url, args.delay),
        "methods": lambda: check_methods(args.url, args.delay),
        "cors": lambda: check_cors(args.url, args.delay),
        "listing": lambda: check_listing(args.url, args.delay),
        "spring": lambda: check_spring(args.url, args.base, args.delay),
    }

    results = []
    for cid in ALL_CHECKS:
        if cid not in want:
            continue
        try:
            results.append(runners[cid]())
        except Exception as exc:
            results.append(result(cid, f"检查项 {cid}", "SKIP",
                                  f"执行异常：{type(exc).__name__}: {str(exc)[:120]}",
                                  "检查网络/授权窗口后重跑"))

    icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]", "SKIP": "[SKIP]", "INFO": "[INFO]"}
    print(f"\n=== 额外网站测试（backend={hc.HTTP_BACKEND}）===\n")
    for row in results:
        print(f"{icon[row['verdict']]} {row['id']:5} {row['name']}")
        print(f"        证据 : {row['evidence']}")
        if row["recommendation"]:
            print(f"        建议 : {row['recommendation']}")
        print()

    summary: dict = {}
    for row in results:
        summary[row["verdict"]] = summary.get(row["verdict"], 0) + 1
    out = {
        "url": args.url, "base": args.base, "http_backend": hc.HTTP_BACKEND,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": summary, "results": results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"汇总：{summary}  -> {out_path}")

    return 5 if summary.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
