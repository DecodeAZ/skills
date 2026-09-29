# 依赖配置指南

核验日期：2026-09-13。入口与版本均来自 npm registry 与各项目官方主页，未使用记忆推断。

先跑只读自检，按它给出的状态决定配置哪一项：

```bash
python scripts/check_environment.py
```

- `ready`：全部就绪，跳过本文件直接执行。
- `partial`：FlyAI 可用、小红书通道缺失；继续执行，仅标注来源降级。
- `needs_setup`：只配置它列出的缺失项。
- `unavailable`：包体不完整，按自检提示重新安装本技能。

依赖清单的机器可读版本在 `../skill-dependencies.json`。

---

## node-runtime

| 项 | 说明 |
|---|---|
| 官方入口 | https://nodejs.org/ |
| 下载页 | https://nodejs.org/en/download |
| 版本要求 | FlyAI 需 >= 18；mcporter 需 >= 20，建议直接装 LTS |
| 安装 | 用官网安装包，或用系统包管理器（如 `winget install OpenJS.NodeJS.LTS`） |
| 验证 | `node --version` 应输出 `v20` 或更高 |
| 权限 | 全局 npm 安装写入 npm 全局目录；不要用 `sudo` 强行提权 |
| 撤销 | 卸载 Node.js，或仅卸载下节的全局包 |

---

## flyai-cli（必需，决定预算能否标注"实查"）

| 项 | 说明 |
|---|---|
| 包名 | `@fly-ai/flyai-cli` |
| 最新版本 | 1.0.16（2026-04-21 发布） |
| 许可证 / 发布者 | MIT / open-flyai@alibaba-inc.com |
| 官方入口 | https://open.fly.ai/ |
| 安装 | `npm i -g @fly-ai/flyai-cli` |
| 提供的命令 | `flyai` |
| 验证 | `flyai keyword-search --query "杭州"` 应输出单行 JSON |
| 权限 | 读取参数、访问飞猪接口；不修改本地文件 |
| 凭据 | 无需密钥即可试用；如需增强结果可 `flyai config set FLYAI_API_KEY "<key>"`。该 Key 由 CLI 自行存储，不要写进本技能或任何仓库文件 |
| 轮换 | 在 FlyAI 侧重新签发 Key 后，重复上面的 `config set` 覆盖即可 |
| 撤销 | `npm uninstall -g @fly-ai/flyai-cli`；如已设置 Key，同时在 FlyAI 侧吊销 |

### 参数核对（实测，CLI 1.0.16）

以下结论来自对 `flyai <子命令> --help` 与真实调用的逐条实测，不用文档推断：

- `search-hotel` 与 `search-hotels` 是**同一子命令的两个别名**，都可正常执行，输出的用法说明也一致。同理 `keyword-search` 与 `fliggy-fast-search` 互为别名。不要因为看到长短两种写法就认为其中一个不存在。
- `search-poi --category` 的合法取值是**中文**。`--help` 打印出来的分类清单是英文（`nature`、`historic site`、`ancient town` 等），但实际传入英文会直接报错并列出可用值，必须使用中文（如 `历史古迹`、`自然风光`、`古镇古村`、`博物馆`、`温泉`）。以报错信息里返回的中文清单为准。
- `search-flight --sort-type` 取值 1-8（1=价格降序、2=推荐、3=价格升序、4=耗时升序、5=耗时降序、6=最早出发、7=最晚出发、8=直达优先）。本技能用它按价格升序取最低价。
- 帮助信息里未列出但实际可用的还有 `search-train`（火车票），可用于替代通用搜索获取车次。

---

## mcporter-cli（可选）

| 项 | 说明 |
|---|---|
| 包名 | `mcporter` |
| 最新版本 | 0.13.12 |
| 许可证 | MIT |
| 官方入口 | https://github.com/steipete/mcporter |
| 文档 | https://github.com/steipete/mcporter#readme |
| 安装 | `npm i -g mcporter`，或不安装直接用 `npx mcporter` |
| 提供的命令 | `mcporter` |
| 验证 | `mcporter list` 应列出已配置的 MCP 服务 |
| 权限 | 连接 MCP 服务并发起调用；不修改本地文件 |
| 撤销 | `npm uninstall -g mcporter`，并移除你添加的服务配置 |

### 小红书 MCP 服务（无法核验官方入口）

mcporter 本身只是 MCP 客户端，它**连接的是你已经配置好的服务**。我没有找到可核验的官方小红书 MCP 提供方，因此：

- 本技能不硬编码任何端口、地址或凭据，也不把它列为必需依赖；
- 你需要自行提供一个具备小红书检索能力的 MCP 服务，并按 mcporter 的方式注册；
- 验证方式：`mcporter list` 输出的服务清单中出现对应服务名；
- 未配置时技能走通用搜索替代，并在交付时声明来源降级，不会声称拿到了小红书原帖。

---

## host-web-search（必需）

| 项 | 说明 |
|---|---|
| 用途 | 天气、12306 高铁时刻、攻略与所有兜底检索 |
| 依赖形态 | 由宿主 Agent 环境提供，无需安装 |
| 主要数据源 | https://www.weather.com.cn/ （中国天气网）；和风天气 qweather.com；12306 |
| 验证 | 在宿主环境中执行一次公开网页检索并确认返回内容 |
| 权限 | 只访问公开数据源，不传递凭据，不绕过登录或付费墙 |
| 撤销 | 由宿主环境统一管理网络策略 |

如所在网络需要代理，在宿主环境配置，不要写进本技能。

---

## python-runtime（必需）

| 项 | 说明 |
|---|---|
| 官方入口 | https://www.python.org/ |
| 官方文档 | https://docs.python.org/3/ |
| 版本要求 | >= 3.9 |
| 验证 | `python --version` |
| 权限 | 本技能脚本纯标准库，无网络、无子进程、不读取凭据 |
| 撤销 | 卸载 Python，或直接停用本技能的脚本功能（改由 Agent 直接撰写 HTML） |

---

## bundled-generator（必需，包内资源）

| 项 | 说明 |
|---|---|
| 来源仓库 | https://github.com/DecodeAZ/skills |
| 技能目录 | https://github.com/DecodeAZ/skills/tree/main/skills/travel-planner |
| 组成 | `scripts/generate.py` 与 `assets/template.html` |
| 用法 | `python scripts/generate.py <tripData.json> <输出.html>` |
| 退出码 | `0` 成功 / `1` 输入问题 / `2` 模板问题 |
| 验证 | 用任意合法 tripData 跑一次，返回退出码 0 且产物无残留占位符 |
| 权限 | 只读 tripData 与模板，只写指定输出路径；内联数据前会把 `</` 转义为 `<\/` |
| 恢复 | 缺失时重新安装本技能，或改由 Agent 按 `html-spec.md` 直接撰写 |

## 只读原则

以上任何一步都不由技能代为执行安装、登录或授权。技能只运行自检、报告缺失项，由你决定是否配置。
