# {{F_RANGE}} 验证与复验清单

| 项目 | 内容 |
|---|---|
| 适用资产 | {{TARGET_URL}} |
| 对应报告 | 《{{SITE_NAME}} 技术栈测绘与漏洞报告》第 {{CHAPTER}} 章 |
| 清单版本 | v1.0 · {{DATE}} |
| 执行方式 | 只读（GET / Range），串行限速，不下载完整文件 |
| 一键复验 | `python <skill>/scripts/verify_findings.py --base {{API_BASE}}` |

> **使用前提：** 执行前须取得资产方书面授权，并在约定时间窗口内进行。本清单刻意把请求数控制在最小集合。

---

## 一、执行顺序

```
{{DEPENDENCY_GRAPH}}
<!-- 示例（zmka 实际用例）：
F-09（公共配置）
  └── appDownload 路径 ──> F-11（对象存储匿名读）
F-10（GIS 配置）       独立
F-12（SockJS）          独立
CTRL（对照组）          独立，用于证明鉴权链路本身正常
-->
```

---

## 二、逐项验证

<!-- 每个发现复制以下模板块；「判定为漏洞」与「修复后通过标准」必须双向给出 -->

### {{F_ID}} {{F_TITLE}}

| 项 | 内容 |
|---|---|
| 严重级 | {{SEVERITY}} |
| 前置 | {{PREREQ}} |
| 请求 | `{{REQUEST}}` |
| 判定为漏洞 | {{OPEN_CRITERIA}} |
| 修复后通过标准 | {{FIXED_CRITERIA}} |
| 证据留存 | {{EVIDENCE_SPEC}} |

```bash
{{REPRO_COMMAND}}
```

---

### CTRL 对照组（必做）

| 项 | 内容 |
|---|---|
| 目的 | 证明鉴权链路本身工作正常，排除「所有接口都放行」的误判 |
| 请求 | `GET {{API_BASE}}/<受保护端点>` |
| 通过标准 | 返回 `401` |

若对照组不是 401，停止单项验证，升级为整体鉴权评估。

---

## 三、一键复验

```bash
# 修复前基线
python <skill>/scripts/verify_findings.py --base {{API_BASE}} --delay 0.6 --out reports/verify-before.json
# 修复后复验
python <skill>/scripts/verify_findings.py --base {{API_BASE}} --delay 0.6 --out reports/verify-after.json
```

**退出码语义：** `0` = 全部 FIXED（附 verify-after.json 关闭工单）；`10` = 仍有 OPEN 项（按 ID 退回）；`2` = 连接失败（不判定）。

---

## 四、修复建议映射

| ID | 最小修复动作 | 责任方 | 复验方式 |
|---|---|---|---|
| {{F_ID}} | {{FIX_ACTION}} | {{OWNER}} | {{VERIFY_HOW}} |

---

## 五、证据留存规范

- 命名：`{{F_ID}}_{{YYYYMMDD}}_before.txt` / `_after.txt`
- 内容：请求命令、完整响应头、脱敏后响应体、执行时间、执行人、源 IP
- 流转：对外材料中 IP 末段、UUID、坐标一律脱敏；原始证据仅授权人可见

---

## 六、边界与注意事项

1. **不要下载完整大文件**：Range 探测足以定性。
2. **不要在生产跑字典**：只覆盖清单内已知端点。
3. **保持限速**：`--delay ≥ 0.5`；高频短连接可能被目标 TLS 层异常关闭。
4. 修复要追根因：同一根因的多个发现（如配置接口暴露 → 存储匿名读）只改其一，复验仍会失败。
