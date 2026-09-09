# _template —— 新系统适配器模板（复制本文件后填空，勿直接当适配器使用）

> 使用方法：复制本文件为 `adapters/<新系统名>.md`，逐项替换 `<尖括号占位符>`，删除不适用形态的说明，然后按 SKILL.md"新增适配器"流程用一次真实小文件验证。本文件**不含 curl 命令**——接口约定由 `scripts/upload_skill.py` 解析执行。

# <新系统名>

- base_url: <默认基础地址，如 https://docs.example.com；可为空，空则按 SKILL.md 第 0 段：环境变量 → config.json → 提问获取>
- max_size: <单文件上限，如 20MB>
- auth: <none | bearer:<环境变量名，如 MYDOC_TOKEN> | login-bearer:<登录端点>:<环境变量名，如 login-bearer:/api/v1/auth/login:MYDOC_KEY> | header:<头名>:<环境变量名> | basic>
- discovery: <GET 探活/能力路径与预期返回特征，如 GET `<base_url>/health` 返回 200；或 none；login-bearer 形态须先登录再发现>

> login-bearer 说明：环境变量存**登录密钥**（非静态令牌）。执行时脚本先 POST 登录端点（JSON）换取会话令牌，后续请求携带 `Authorization: Bearer <会话令牌>`；令牌进程内复用、不落盘，收到 401 自动重登一次。须参考 htmlview-agent-api.md 的 auth 段写明登录请求/响应字段与限流约定。

## request

声明接口方法与字段映射，供 `upload_skill.py` 解析（`file → \`字段\`` 行的 `file/title/tags/summary` 左值为约定语义，右值为目标系统字段名）。

### 形态 A：纯 multipart 表单（最常见）

<POST|PUT> `<base_url><上传端点，如 /api/v1/docs>`，Content-Type: multipart/form-data：

- file → `<文件字段名，如 file>`（必填）
- title → `<标题字段名，如 title>`（可选）
- tags → `<标签字段名，如 tags，分隔约定如逗号>`（可选）
- summary → `<摘要字段名，如 summary>`（可选）

### 形态 B：JSON 元数据 + 文件字段（单请求混合体）

`Content-Type: application/json   # 声明 application/json 即切换为 JSON 编码`
- file → `contentBase64`（文件 base64）＋ `fileName`（文件名）
- title → `<标题字段名>`
- tags → `<标签字段名>`
- summary → `<摘要字段名>`

> 注意：base64 会使体积增大约 1/3，确认 <max_size> 按编码后计算；超过限制时改用形态 A。

### 形态 C：两步上传（先传文件拿引用，再提交元数据）

字段映射里写明两步顺序与引用字段名，例如：

1. file → `<文件上传字段名>`（第一步，响应取 `<引用字段名，如 fileId / url>` 记为引用）
2. 元数据（第二步）：title → `<标题字段名>`、tags → `<标签字段名>`、summary → `<摘要字段名>`、引用 → `<引用字段名>`

## success

- 状态码：<如 200 / 201>
- 判定字段：<如响应 JSON 含 id 且非空，或含 url>
- 向用户报告：<如 id、标题、访问 URL、入库时间>

## errors

- <状态码，如 401> → <原因：凭据缺失/过期；修复：提示用户更新环境变量 <环境变量名>，或回到 SKILL.md 第 0 段重新提问获取>
- <状态码，如 413> → <原因：文件超过限制；修复：核对 max_size 或压缩/拆分>
- <状态码，如 409> → <原因：如同名文档已存在；修复：提示用户改名或覆盖策略>
- 连接拒绝 → 服务未启动或基础地址错误，与用户核对 <base_url>