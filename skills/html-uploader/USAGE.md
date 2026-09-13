# html-uploader 使用说明

面向使用者的快速上手文档。完整的流程约定与适配器规范见 [SKILL.md](SKILL.md)；各目标系统的接口细节见 [adapters/](adapters/)。

## 功能概览

将本地 `.html` / `.htm` 文件上传到目标文档系统。不同系统的差异（能力发现、认证、接口路径、字段名、成功判据）全部封装在**适配器文件**中；新增一个目标系统 = 新增一个 `adapters/<系统名>.md`，无需改动脚本。

内置适配器：

| 适配器 | 说明 |
|---|---|
| `htmlview-agent-api` | 密钥登录制文档系统（默认）。`/api/auth/login` 换令牌，`/api/agent/articles` 上传 |
| `generic-multipart` | 通用 REST multipart 上传模板，接入新系统时复制改造 |

## 前置条件

- Python 3.8+（脚本纯标准库，**零第三方依赖**，不使用 curl）
- 已确定两样东西（缺一会被脚本拦下并提示）：
  - **系统地址**：目标系统主机与端口，如 `http://localhost:8080` 或 `https://docs.example.com`
  - **访问密钥**：目标系统发放的 API Key / Token

### 环境变量

| 变量 | 用途 |
|---|---|
| `HTMLVIEW_BASE_URL`（或 `<系统名大写>_BASE_URL`） | 系统地址 |
| `HTMLVIEW_KEY` | 访问密钥（密钥只从环境变量或当次输入读取，**绝不落盘**） |

> 地址非敏感，可写入 `config.json` 以便下次免问；密钥一律不写入任何持久文件。

## 快速上手

### 1. 预检（每次任务先跑一次）

```bash
python "<本Skill目录>/scripts/check_config.py" [--system <适配器名>] [--base-url <地址>]
```

退出码：`0` 全部就绪 / `3` 有缺失需补全 / `4` 适配器文件不存在。

首次使用且缺少地址或密钥时，脚本会输出 `missing`（缺失项）与 `ask`（提问文案），此时按提示把缺失项一次性补齐（地址写入 `config.json`，密钥设为环境变量）。

### 2. 执行上传

```bash
python "<本Skill目录>/scripts/upload_skill.py" \
  --file "<源文件绝对路径>" \
  --system "htmlview-agent-api" \
  [--title "<标题>"] [--tags "<逗号分隔>"] [--summary "<摘要>"] \
  [--base-url "<地址>"] [--insecure]
```

- 不传 `--file` 时，脚本以本技能打包内容（SKILL.md + 适配器）为载荷做自上传自检。
- 成功：退出码 `0`，打印 `id`/`url`、标题与访问地址。
- 失败：退出码非 `0`，打印含错误码/字段的响应片段。

## 完整示例

### 上传单个报告

```bash
# 一次性设置（密钥不落盘，仅当前 shell 会话有效）
export HTMLVIEW_KEY="<你的密钥>"

python "<本Skill目录>/scripts/upload_skill.py" \
  --file "D:/reports/2026-Q3-经营分析.html" \
  --system htmlview-agent-api \
  --title "2026 Q3 经营分析报告" \
  --tags "经营,季度,2026Q3" \
  --summary "本季度营收与利润概览"
```

Windows PowerShell：

```powershell
$env:HTMLVIEW_KEY = "<你的密钥>"
python "<本Skill目录>\scripts\upload_skill.py" `
  --file "D:\reports\2026-Q3-经营分析.html" `
  --system htmlview-agent-api `
  --title "2026 Q3 经营分析报告" `
  --tags "经营,季度,2026Q3"
```

### 批量上传目录

```bash
for f in reports/*.html; do
  python "<本Skill目录>/scripts/upload_skill.py" \
    --file "$f" --system htmlview-agent-api --tags "批量"
done
```

> 批量上传共用同一次能力发现结果，逐文件执行。

### 读取与删除（htmlview-agent-api 的 web API，需鉴权头）

> 以下 curl 仅用于**人工排查**读取/删除已入库文档。**上传链路一律走 `upload_skill.py`**，不要用 curl 代替脚本上传。

```bash
# 元数据
curl -H "Authorization: Bearer <token>" "<base_url>/api/articles/<id>"
# 正文（入库会剥离 <script> 标签；响应经 gzip，客户端需自动解压）
curl -H "Authorization: Bearer <token>" "<base_url>/api/articles/<id>/content"
# 删除
curl -X DELETE -H "Authorization: Bearer <token>" "<base_url>/api/articles/<id>"
```

## 常见错误速查

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 `3`，提示缺地址/密钥 | 配置未就绪 | 按 `check_config.py` 的 `ask` 一次性补齐 |
| 退出码 `3`，提示「网络失败」 | 地址不可达：连接拒绝/超时/DNS/TLS | 核对基础地址与服务状态；本地可信测试可用 `--insecure` |
| 退出码 `1`，提示文件不存在 | 路径笔误或指向目录 | 核对源文件绝对路径与 `.html/.htm` 扩展名 |
| 退出码 `4` | 适配器文件不存在 | 复制 `adapters/generic-multipart.md` 改造后重试 |
| 401 `invalid_key` | 密钥错误 | 重新获取密钥后重试一次 |
| 403 `key_change_required` | 管理员仍用临时密钥 | 中止，先到网页端完成首次改密 |
| 429 `rate_limited` | 登录过于频繁 | 脚本读 `Retry-After` 自动等待，令牌复用 |
| 413 / 400 | 超限或字段不符 | 核对大小 ≤20MB、扩展名 `.html/.htm`、字段名与适配器一致 |
| 403 纯文本 `error code: 1010` | Cloudflare WAF 拦截默认 UA | 脚本已默认补浏览器 UA；若自行改动请确认请求带浏览器特征头 |
| 连接拒绝 / SSL 错误 | 服务未启动、端口错或证书不受信 | 核对基础地址；本地可信测试可用 `--insecure` |

## 接入新系统

1. 复制 `adapters/generic-multipart.md` 为 `adapters/<新系统名>.md`。
2. 逐项替换占位符：`base_url`、`auth`、`request`（端点/方法/字段映射）、`success`、`errors`。
3. 按 [SKILL.md](SKILL.md)「新增适配器」流程，用一次真实小文件上传验证后再视为适配完成。

## 文件结构

```
html-uploader/
├── SKILL.md                  # 技能主文档：流程约定 + 适配器规范
├── USAGE.md                  # 本文件：使用者快速上手
├── config.example.json       # 非敏感配置模板（复制为 config.json 使用）
├── config.json               # 本地配置（已 gitignore，不入库）
├── _user_meta.json           # 本地安装记录（已 gitignore，不入库）
├── adapters/                 # 各目标系统接口约定
│   ├── htmlview-agent-api.md
│   ├── generic-multipart.md  # 新系统模板
│   └── template.md
└── scripts/
    ├── check_config.py       # 预检：确认地址/密钥是否就绪
    ├── upload_skill.py       # 统一上传执行器（纯 Python 标准库）
    └── example_upload.py     # 可运行示例脚本
```
