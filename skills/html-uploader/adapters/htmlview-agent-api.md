# htmlview-agent-api

密钥登录架构。接口约定供 `scripts/upload_skill.py` 解析执行，本文件**不使用 curl**。

> **路径前缀为 `/api/`（v1）**：能力发现端点 `/api/agent/capabilities` 返回 `version: 1`。若目标系统整体返回 404，说明服务端已升级，把本文件所有 `/api/` 替换为 `/api/v2/` 后重试。

- base_url: （空 → 按 SKILL.md 第 0 段解析：当次提供 → 环境变量 `HTMLVIEW_BASE_URL` → `config.json` → 提问获取；常见为 http://localhost:<端口> 或 https://<域名>）
- max_size: 20MB
- auth: login-bearer:/api/auth/login:HTMLVIEW_KEY（登录密钥经环境变量或用户当次输入提供，不落盘）
- discovery: 先登录（见下），再 GET `<base_url>/api/agent/capabilities`（带鉴权头），预期返回 JSON 且 `service` 字段为 `htmlview-agent-api`、`version` 为 1；返回中顶层 `authentication` 字段自描述鉴权要求，以实际发现为准。`submit_article` 工具的 `path`、`content_type`、`fields` 与本文件 request 段冲突时以发现结果为准。

## auth（密钥登录制）

平台 `/api/*`（含 capabilities）需 Bearer 会话令牌，登录流程由 `upload_skill.py` 执行：

1. `POST <base_url>/api/auth/login`，JSON `{"key": "<密钥>"}` → 200 返回 `{ "token": "...", "mustChange": bool }`。
2. 后续所有请求携带 `Authorization: Bearer <token>`。
3. **mustChange=true**：管理员尚未完成首次改密，业务接口一律 403 `key_change_required`——中止上传并提示用户先到网页端用临时密钥完成改密。
4. **令牌复用**：有效期 7 天，一次会话内复用；进程内不持久化到磁盘。
5. **401 重登**：收到 401（服务重启/管理员改密使会话失效）时自动重登一次，仍失败则报错终止。
6. **限流**：login/change 每 IP 默认 5 次/分钟，超限 429 + `Retry-After`——禁止每次上传都登录。

凭据规范：密钥只从环境变量 `HTMLVIEW_KEY` 或用户当次输入读取；**绝不写入适配器、`config.json`、脚本、日志或任何持久文件**。环境变量未设置时，按 SKILL.md 第 0 段以提问方式向用户获取。

访问形态补充：目标系统部署于 Cloudflare 等 WAF 之后，缺省脚本 UA（`python-urllib`）会被误判为机器人并返回 HTTP 403 `error code: 1010`（该响应体为纯文本、非 JSON）。`upload_skill.py` 已默认补充浏览器 User-Agent 与会话头，登录/上传请求均可正常通过；如用户自行改动或出现 403 非 JSON 响应，优先检查请求是否携带浏览器特征头，而非密钥错误。

## request

上传：`POST <base_url>/api/agent/articles`，Content-Type: multipart/form-data，带鉴权头：

- file → `file`（必填，.html/.htm）
- title → `title`（可选）
- tags → `tags`（可选，逗号分隔字符串）
- summary → `summary`（可选）

调用方式（由 `upload_skill.py` 执行，元数据以 UTF-8 直接编码进 multipart，无需中间文本文件）：

```powershell
python "<本Skill目录>/scripts/upload_skill.py" --file <报告路径> --system htmlview-agent-api `
  --title "<标题>" --tags "<a,b,c>" --summary "<摘要>"
```

## 读取与删除（web API，同样需鉴权头）

- 元数据：GET `<base_url>/api/articles/<id>` → JSON（id/title/summary/tags/word_count/added_at 等）。
- 正文：GET `<base_url>/api/articles/<id>/content` → text/html（入库后的最终 HTML，注意入库过程会剥离 `<script>` 标签）。⚠️ 该响应经 CDN gzip 压缩，客户端需自动解压（Python `urllib` 通过请求头 `Accept-Encoding: gzip` 处理），否则落盘 0 字节。
- 删除：DELETE `<base_url>/api/articles/<id>` → 204（成功）。agent API 本身无删除能力，删除走 web API。

## success

HTTP 201 Created，响应 JSON 含 `id`、`title`。向用户报告 id、标题、标签、`word_count` 与 `added_at`。

- reader_url: /reader.html?id={id}

## errors

- 401 `unauthorized` → 未登录/会话失效（服务重启或管理员改密）：脚本自动重登一次；`invalid_key` → 密钥错误，回到 SKILL.md 第 0 段重新向用户提问获取密钥后重试一次（注意临时密钥须先完成改密）。
- 403 `key_change_required` → 管理员仍在使用临时密钥：中止并提示先完成首次改密，不要重试。
- 429 `rate_limited` → 登录过于频繁：读 `Retry-After` 等待后重试一次，并改为令牌复用。
- 413/400 提示超限或格式错误 → 核对文件大小 ≤20MB、扩展名为 .html/.htm；400 "Unexpected field" 多为字段名与适配器声明不符，核对 request 段字段映射。
- 404（`not_found`）→ capabilities 返回的路径可能与本文件不同，以发现结果重试一次；若整体 404 且你确认服务器已升级 v2，将本文件中 `/api/` 批量替换为 `/api/v2/` 后重试。
- 连接拒绝/SSL 错误 → 服务未启动、端口错误或证书不受信（TLS `--insecure` 仅供本地可信测试，生产勿用），与用户核对基础地址。