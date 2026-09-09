# generic-multipart

通用 REST multipart 上传系统模板。接入新系统时复制本文件为 `adapters/<新系统名>.md`，逐项替换尖括号占位符后，按 SKILL.md"新增适配器"流程验证。接口约定由 `scripts/upload_skill.py` 解析执行，**不使用 curl**。

- base_url: <默认基础地址，可为空>
- max_size: <单文件上限，如 20MB>
- auth: <none | bearer:<环境变量名> | login-bearer:<登录端点>:<环境变量名> | header:<名称>:<环境变量名> | basic>
- discovery: <GET 探活/能力路径与预期返回特征，或 none>

## request

<POST|PUT> `<base_url><上传端点>`，Content-Type: multipart/form-data：

- file → `<文件字段名>`（必填）
- title → `<标题字段名>`（可选）
- tags → `<标签字段名，含分隔约定>`（可选）
- summary → `<摘要字段名>`（可选）

若该系统要求 JSON 体而非 multipart，声明 `Content-Type: application/json`，文件以 base64 放进 `contentBase64`（配合 `fileName`）字段；若为两步上传（先传文件拿 URL/ID，再提交元数据），在字段映射里写明两步顺序与引用字段名。`upload_skill.py` 会按 Content-Type 自动选择 multipart 或 JSON 编码。

## success

<成功状态码> + 响应判定字段（如 200 + 响应含 `id` 或 `url`）。

## errors

- <错误码> → <原因与修复建议>