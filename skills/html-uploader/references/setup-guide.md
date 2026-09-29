# 环境与凭据配置

本技能需要 **Python 运行环境**（`python-runtime`）与 **包内执行器**（`bundled-uploader`）两项就绪，另需用户自己提供一个目标文档系统的地址与访问密钥。已就绪的项不必重复配置。

## 1. python-runtime

上传执行器 `scripts/upload_skill.py` 为纯标准库实现，需要 Python 3.9 或更高版本。

- 官方主页：https://www.python.org/
- 官方文档：https://docs.python.org/3/
- 安装步骤：
  1. 从上述官方渠道安装 Python 3.9 或更高版本；
  2. 确认 `python --version` 可执行；
  3. 本技能不依赖任何第三方包，无需 `pip install`。
- 验证：`python --version`
- 安全：脚本只使用标准库；密钥只经环境变量或当次输入使用，不写入任何文件。
- 核验日期：2026-09-13；适用版本 `>=3.9`。

## 2. bundled-uploader

包内执行器与默认适配器是上传能力的载体。

- 官方主页：https://github.com/DecodeAZ/skills
- 官方文档：https://github.com/DecodeAZ/skills/tree/main/skills/html-uploader
- 需要存在的文件：`scripts/upload_skill.py`、`adapters/htmlview-agent-api.md`
- 验证：`python scripts/check_config.py` 返回退出码 `0` 或 `3`；返回 `4` 说明适配器缺失
- 安全：只读取待上传的 HTML 与适配器文件；不落临时文件，密钥仅存进程内存。
- 核验日期：2026-09-13；适用版本 `1.2.0`。

## 3. 目标系统地址与访问密钥

目标系统由用户自己部署或持有，本技能不预设其地址，也不内置任何密钥。

### 地址

- 解析优先级：当次提供 → 环境变量 `HTMLVIEW_BASE_URL` 或 `<SYSTEM>_BASE_URL` → `config.json` 的 `systems.<系统>.base_url` → 适配器声明。
- 地址非敏感，获取后可写入 `config.json` 与 `last_base_url`，下次免问。
- 验证：`python scripts/check_config.py` 的 `base_url.status` 为 `ok`。

### 密钥

- 环境变量名由适配器 `auth` 段声明，默认 `HTMLVIEW_KEY`。
- 存储：**只放在环境变量或当次输入中**，绝不写入 `config.json`、适配器、脚本或日志。
- 获取与轮换：在目标系统网页端登录换取会话令牌（htmlview 形态为 `POST /api/auth/login`，令牌有效期 7 天、仅存进程内存）；首次使用的临时密钥须先在网页端完成改密，否则业务接口返回 403 `key_change_required`。
- 撤销：在目标系统网页端改密或删除该密钥，即可使旧密钥与已签发会话失效。
- 验证：`python scripts/check_config.py` 的 `key.value_set` 为 `true`。脚本只报告"是否已设置"，不读取也不回显密钥内容。

## 4. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `check_environment.py` 返回 `needs_setup` | 缺 Python 3.9+，或包内执行器/适配器缺失 | 按第 1、2 节修复后重跑 |
| 退出码 `3` 且提示"网络失败" | 地址不可达：连接拒绝 / 超时 / DNS / TLS | 核对基础地址与服务状态；本地可信测试可加 `--insecure` |
| 退出码 `3` 且提示缺地址或密钥 | 配置未就绪 | 按 `check_config.py` 的 `ask` 列表一次性向用户获取 |
| 退出码 `4` | 适配器文件不存在 | 复制 `_generic-multipart.md` 改造为新适配器后重试 |
| 401 `invalid_key` | 密钥错误或会话失效 | 脚本自动重登一次；仍失败则重新向用户获取密钥 |
| 403 `key_change_required` | 仍在使用临时密钥 | 先在网页端完成首次改密，不要重试 |
| 403 且响应体非 JSON | 请求缺少浏览器特征头被 WAF 拦截 | 使用包内脚本发起请求，不要改用 curl |
