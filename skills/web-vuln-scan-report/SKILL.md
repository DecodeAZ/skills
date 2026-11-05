---
name: web-vuln-scan-report
version: "1.1.0"
description: 对指定网站做只读漏洞扫描并生成含修复方案的 HTML 报告。当用户要求「扫描网站漏洞」「给网站做安全评估」「渗透测试」「漏洞扫描报告」「安全整改报告」「网站安全检测」，或要求「复测/验证漏洞是否修复」时使用；也适用于"先指纹识别、再 CVE 比对、再出报告"类需求。执行前必须确认目标 URL 与授权范围，缺失时主动询问，未获授权不开始。
agent_created: true
---

# 网站漏洞扫描与修复报告

对目标网站执行：指纹识别 → 端点探测 → 额外安全测试 → 依赖 CVE 比对 → 生成 13 章 HTML 报告（含逐项修复方案与验收标准）→ 交付复验脚本。全程只读（GET/HEAD/OPTIONS），不使用任何利用模块。

## 硬性前置（不满足就停下来问）

1. **目标 URL**：入口地址（如 `https://host:port/service/`）；有独立 API 前缀时一并要（如 `/dev-sys-api/`）。
2. **授权确认**：明确"已获授权/自查资产"才继续；用户含糊时先问，把「探测方式只读、限速、不留数据」讲清楚。
3. **时间窗与边界**：生产站默认不做字典爆破、不下载大文件、不加压测。

## 依赖要求

**硬依赖**（由 `scripts/check_environment.py` 机器校验，缺失即 needs_setup / unavailable）：

| 依赖 | 已验证版本 | 缺失时 |
|---|---|---|
| Python | 3.14.7（≥3.10 可用） | 提示升级；旧解释器仅跑 pathprobe |
| 包内脚本与模板（`skill-dependencies.json` 的 bundled-toolkit 清单） | 随本技能分发 | 重装本技能 |

**其余依赖按需检查**（不进硬依赖清单，缺失走下方降级矩阵）：

| 依赖 | 检查方式 | 未就绪时 |
|---|---|---|
| requests / urllib3 | venv 内 `python -c "import requests"` 或看 fingerprint 输出 `http_backend` | **http_client.py 自动降级 urllib，脚本零改动** |
| python-Wappalyzer 0.3.1 + setuptools<81 | `python scripts/wapp_scan.py <url>`，exit 3 = 未安装 | 跳过通用对照，仅自建指纹 |
| dirsearch 0.5.0 | `dirsearch --version` | 主路径本就是 pathprobe 串行，不主动跑 |
| openssl CLI | `openssl version`（系统/Git Bash 自带） | security_checks 的 TLS 项判 SKIP |
| cve-scan MCP | 尝试列举一个 cve-scan 工具是否可见 | 按 references/cve-matching.md 手册降级 |

环境准备（在目标项目下）：

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -U pip          # POSIX 用 .venv/bin/python
./.venv/Scripts/python.exe -m pip install -r "<本Skill目录>/scripts/requirements.txt"
```

`requirements.txt` 已区分必需/可选并注明 `setuptools<81` 的原因（Wappalyzer 0.3.1 依赖 pkg_resources）。安装失败不要反复重试，直接走下面的降级矩阵。

## 降级矩阵（每次降级都要在报告里标注）

| 失败场景 | 动作 | 报告标注 |
|---|---|---|
| requests 不可用 | http_client 自动切 urllib（输出 JSON `http_backend=urllib`） | 「HTTP 层：stdlib 降级模式」 |
| Wappalyzer 装不上 | 跳过通用对照，仅自建指纹 | 第 11 章标"通用工具未运行" |
| dirsearch TLS 异常断连（实测：目标触发重协商） | 改 `pathprobe.py` 串行限速，保留失败记录 | 作为证据写进报告 |
| cve-scan MCP 不可用 | references/cve-matching.md 手册流程；仍不行输出"未比对" | 第 8 章盲区声明 |
| openssl 缺失 | TLS 检查 SKIP | 检查矩阵标 SKIP |
| WAF 按 UA/请求头/TLS 栈指纹降权（404 静默过滤 / 420 黑名单页 / SSL 断连） | http_client 已统一模拟浏览器（Chrome UA + Sec-Fetch/Referer/Origin 档位），触发后自动粘性切 curl（Windows=Schannel TLS）兜底 | 「HTTP 层：curl 兜底传输」（Response.transport 可查） |
| 目标断连 / WAF 拦截 / 限速（curl 兜底后仍失败） | 等待冷却（实测 15–30 分钟）或报备源 IP 后重试；`--delay` 加倍重试一次；仍失败→停止主动探测，转纯离线产物分析 | 「主动探测受限」 |
| Python < 3.10 | 仅跑 pathprobe（避免 3.10+ 语法），提示升级 | 环境节记录实际版本 |

## 工作流

### 第 0 步 · 环境自检（只读）

```bash
cd "<本Skill目录>" && python scripts/check_environment.py
```

`ready` / `partial` 进入第 1 步（`partial` 只需说明受影响能力与降级，不停止）；
`needs_setup` 只展示缺失项的修复步骤（装 Python 3.10+ 或重装本技能）；
`unavailable` 停止并说明原因。本自检只覆盖硬依赖（Python + 包内文件完整性）；
requests / Wappalyzer / dirsearch / openssl / cve-scan MCP 按「依赖要求」的
按需检查表逐项确认，缺失时走降级矩阵，不阻塞主流程。

### 第 1 步 · 指纹识别

```bash
./.venv/Scripts/python.exe "<本Skill目录>/scripts/fingerprint.py" "<url>" --cache cache
```

输出 JSON：`server`（响应头、nginx 版本）、`frontend`（组件版本）、`api`（baseURL + 端点清单）。规则库与扩展方法见 references/fingerprint-rules.md。后端框架靠行为判定（错误体结构、Whitelabel 页、401 语义），不靠正则。

### 第 2 步 · 通用工具对照（可选）

```bash
./.venv/Scripts/python.exe "<本Skill目录>/scripts/wapp_scan.py" "<url>"
```

已知局限：对 webpack 分包 SPA 基本只认 Nginx；exit 3 = 未安装，按降级矩阵跳过。dirsearch 仅在需要交叉验证时手动使用，本 skill 不主动跑（TLS 敏感站点必失败）。

### 第 3 步 · 端点探测

```bash
./.venv/Scripts/python.exe "<本Skill目录>/scripts/pathprobe.py" "<api_base>" "<本Skill目录>/scripts/wordlists/backend-mini.txt" --delay 0.5 --out reports/pathprobe.json
```

backend-mini.txt 覆盖 actuator/swagger/auth/上传/配置类 ~43 条。按第 1 步指纹换词表（如 PHP 站点换 adminer/phpinfo 类）。生产站保持 `--delay ≥ 0.5`。

### 第 4 步 · 额外网站测试（9 类检查）

```bash
./.venv/Scripts/python.exe "<本Skill目录>/scripts/security_checks.py" \
    --url "<url>" --base "<api_base>" --delay 0.4 --out reports/security-checks.json
```

检查项：`headers`（安全响应头）`version`（版本回显）`tls`（协议/证书，openssl）`cookie`（HttpOnly/Secure/SameSite，无登录态判 INFO）`sensitive`（.git/.env/.DS_Store 等 12 条）`methods`（OPTIONS/TRACE）`cors`（伪造 Origin 反射）`listing`（目录列举）`spring`（actuator/swagger/socket-info/error 按指纹启停）。
判定 PASS/WARN/FAIL/SKIP/INFO，退出码 5 = 有 FAIL。每条结果都有「建议」一句话，直接喂给第 12 章。

### 第 5 步 · 依赖 CVE 比对

用 cve-scan MCP：`scan_dependencies`（提交 fingerprint 的 frontend 字典转 deps）→ `get_scan_result` 拉全量 → 按 references/cve-matching.md 做适用性重归类（仅 Node / 需原型污染 / 浏览器直接适用），nginx 等非包生态走 `search_cve`/`get_cve` + 人工比对。

### 第 6 步 · 生成报告

复制 `assets/report-template.html`，按 references/report-guide.md 填充 13 章：

- 发现按 F-01、F-02… 连续编号，跨第 7/10/11 章共用序列；每条 = 证据 + 影响 + 建议。
- 证据先脱敏（`http_client.mask`：IP 末段、32 位 UUID）。
- 第 12 章修复方案从 references/remediation-playbook.md 取代码片段，替换成目标真实路径/域名；每条带工作量与验收方式。
- 产出放项目 `reports/`，文件名 `<site>-vuln-report.html`。

### 第 7 步 · 交付三件套

1. **报告** HTML（第 12 章为修复方案）。
2. **复验清单**：复制 `assets/checklist-template.md`，为 OPEN 级发现逐条填判定标准与"修复后通过条件"；依赖关系要写明（如 F-11 依赖 F-09 的返回字段）。
3. **跟踪表**：`assets/findings-tracker.csv` 补齐全部发现；**复验脚本**：复制 scripts/verify_findings.py 按站点改 CHECKS 段，退出码 0=全修复 / 10=仍有 OPEN / 2=连接失败。

## 复测模式（用户说"复测/验证修复"时）

不重跑全流程，只做：`verify_findings.py`（新基线 vs 旧 JSON 对比 OPEN→FIXED）+ `security_checks.py` 对应检查项 + 对照组 CTRL 必须仍 PASS。结果回填 tracker 的复验日期/结果两列，报告新增"复测记录"小节。

## 参考文件

| 文件 | 用途 |
|---|---|
| `scripts/check_environment.py` | 硬依赖自检：Python 版本 + 包内脚本/模板完整性（读 `skill-dependencies.json`） |
| `scripts/http_client.py` | 统一 HTTP 层：requests→urllib→curl 三级传输、浏览器行为模拟、WAF 兜底、证据脱敏（`http_client.mask`） |
| `scripts/fingerprint.py` | 指纹识别：server 头 / 前端组件版本 / API 端点清单 → JSON |
| `scripts/pathprobe.py` | 端点探测：串行限速请求词表，记录状态码/长度/跳转 |
| `scripts/security_checks.py` | 9 类安全检查，判定 PASS/WARN/FAIL/SKIP/INFO，退出码 5 = 有 FAIL |
| `scripts/wapp_scan.py` | 可选对照：python-Wappalyzer 通用技术栈识别（exit 3 = 未安装） |
| `scripts/verify_findings.py` | 复验脚本模板：按站点改 CHECKS 段（退出码 0=全修复 / 10=仍有 OPEN / 2=连接失败） |
| `scripts/requirements.txt` | pip 依赖清单（必需/可选分档，含 `setuptools<81` 原因） |
| `scripts/wordlists/backend-mini.txt` | 后端探测词表 ~43 条（actuator/swagger/auth/上传/配置类） |
| `references/fingerprint-rules.md` | 指纹规则库与扩展方法 |
| `references/cve-matching.md` | CVE 比对流程：MCP 首选 → 适用性重归类 → 手册降级 |
| `references/remediation-playbook.md` | 修复方案代码库（第 12 章取材，替换成目标真实路径/域名） |
| `references/report-guide.md` | 13 章报告写作规范（F-xx 编号、CVSS 归类、证据脱敏、语言规范） |
| `assets/report-template.html` | 13 章 HTML 报告模板 |
| `assets/checklist-template.md` | 复验清单模板（逐项验证模板块 + CTRL 对照组） |
| `assets/findings-tracker.csv` | 发现跟踪表 CSV 模板 |
| `skill-dependencies.json` | 硬依赖清单与功能降级映射（机器可读，`check_environment.py` 校验对象） |

## 纪律

- 请求统一模拟浏览器行为（http_client 内置：Chrome UA + Sec-Fetch/Referer/Origin 档位 + curl 兜底）；**UA 不做脚本自标识**，授权审计与追溯改用「报备源 IP + 请求速率窗口」。
- 禁止绕过 http_client 发请求：Wappalyzer 等第三方库的内置 fetch（`WebPage.new_from_url`）会裸发 `python-requests` UA —— 一律先用 http_client 取响应再本地构造分析对象。
- 已知残留暴露：security_checks 的 TLS 协议/证书项走 openssl CLI，其 ClientHello（JA3）与浏览器不同、头层面无解；若目标 WAF 按 TLS 指纹限流，该项可能单独触发限流，必要时改 SSL Labs 外测并在报告第 8 章声明。
- 串行限速，`--delay ≥ 0.5`；遇 TLS 断连降并发，不换字典、不加线程。
- 大文件只发 Range（≤1KB）确认可读，不下载正文。
- 每个结论可复现：命令 + 预期输出写进附录；防护到位的点也写"正面信号"。
- 不确定的事标"待确认"，不写进结论段。
