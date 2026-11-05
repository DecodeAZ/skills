# 依赖配置指南

核验日期：2026-09-13；数据源可用性实测 2026-10-05。入口与版本均来自 npm registry 与各项目官方主页，未使用记忆推断。

先跑只读自检，按它给出的状态决定配置哪一项：

```bash
python scripts/collect_self_probe.py --output "$TEMP/probe-results.json"
python scripts/check_environment.py --network --probe-results "$TEMP/probe-results.json"
```

第一步是宿主侧的最小只读探测（CLI 探针 + Key 有效性），第二步是清单驱动的检查器。检查器自身不执行探测、不读取凭据；两者都只读，输出为脱敏状态码。结果文件写到技能包**外**的目录，避免被打包分发。

**探测判定口径**（决定"配好了没有"的结论是否可信）：

- FlyAI 的**进程退出码不可信**：参数非法、日期越界、风控等业务失败仍以退出码 0 结束（实测 `search-flight --dep-date 1999-01-01` 返回 `status=1`）。采集器只认 JSON 信封——`status == 0` 且 `data` 非 null 才算可用。
- 未配置 Key 报 `missing` + `configuration_invalid`（是"还没配"）；配了但被服务端拒绝才报 `unavailable` + `auth_expired_or_invalid`（是"配错了或已失效"）。两者的处置完全不同，不要混为一谈。
- `mcporter-probe` 只证明命令行可执行，**不代表已注册小红书检索服务**；服务是否可用以 `mcporter list` 的实际输出为准。

- `ready`：必需项全通，跳过本文件直接执行。
- `partial`：必需项可用，但有**可选项**缺失（小红书通道、国内精度天气备源、POI 备源）。继续执行，仅标注来源降级，不要当成故障。
- `needs_setup`：只配置它列出的缺失项。
- `unavailable`：包体不完整，或必需源探测失败。**先排除"没传 `--probe-results`"**——那种情况下 CLI 与 Key 类探测会返回 `probe_required`，整体状态会被误判为 `unavailable`，补上探测重跑即可；确认是真实故障再按自检提示处理。

本文件按依赖是否必需分三类：**必需**（node / flyai / open-meteo / python / bundled-generator / host-web-search）、**可选**（mcporter / qweather / nominatim / amap）、**尽力而为**（overpass）。可选项与尽力而为项缺失都不影响主流程。

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

### 小红书 MCP 服务（可选，社区实现，无官方入口）

mcporter 本身只是 MCP 客户端，它**连接的是你已经配置好的服务**。小红书**没有官方 MCP 提供方**，但存在多个社区实现在运行，形态不一：

| 实现 | 形态 | 备注 |
|---|---|---|
| `xpzouying/xiaohongshu-mcp` | Go | 流传较广的原版 |
| `vmxmy/xiaohongshu-mcp` | Go + Docker | 同时提供 MCP 与 REST |
| `shanyang-me/xiaohongshu-mcp-server` | Python + Playwright | pip 安装 |
| `TimeCyber/mcp-xiaohongshu` | npm（`rednote-mcp`） | Node 生态 |

**本技能不硬编码任何端口、地址或凭据，也不把它列为必需依赖。** 你自己选一个实现部署，然后按 mcporter 的方式注册。

**必须先探测工具名再调用**：不同实现的工具名与参数不一致（常见 `search_feeds` / `get_feed_detail` / `user_profile`）。

```bash
mcporter list          # 先看有哪些服务
mcporter list <服务名>  # 再看该服务暴露了哪些工具与参数
# 然后按实际工具名调用，不要照抄任何固定命令
```

**风险声明（调用前必须告知用户并取得同意）**：上述实现均为「载入用户本人账号 Cookie + 用页面内置签名函数发内部 API 请求」，属**驱动真实账号**，存在平台 ToS 与封号风险，且涉及抓取用户生成内容。使用要求：**只读、低频、不得发布或互动**。风险由用户自担。

未配置或探测失败时，技能走通用搜索替代，并在交付时声明来源降级，不会声称拿到了小红书原帖。

---

## open-meteo（必需，天气与地理编码主源）

实测日期 2026-10-05：Forecast / Geocoding / Archive 三个端点均返回 200，耗时 0.9–2.1s，结构化 JSON 字段完整。**免 Key，无需任何注册。**

| 项 | 说明 |
|---|---|
| 官方入口 | https://open-meteo.com/ |
| 官方文档 | https://open-meteo.com/en/docs |
| 鉴权 | 无（免 Key） |
| 限额 | 非商用 < 10,000 次/日；商用需订阅或自托管 |
| 数据许可 | **CC BY 4.0，必须署名** `Weather data by Open-Meteo.com` |
| 天气预报 | `https://api.open-meteo.com/v1/forecast?latitude=&longitude=&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=16&timezone=auto`（≤16 天） |
| 地理编码 | `https://geocoding-api.open-meteo.com/v1/search?name=&count=5&language=zh` |
| 历史 / 气候 | `https://archive-api.open-meteo.com/v1/archive?latitude=&longitude=&start_date=&end_date=&daily=temperature_2m_max,temperature_2m_min&timezone=auto` |
| 验证 | `curl -s --ssl-no-revoke "https://api.open-meteo.com/v1/forecast?latitude=30.27&longitude=120.15&daily=temperature_2m_max&forecast_days=3&timezone=auto"` 应返回含 `daily` 的 JSON |
| 权限 | 只读公开接口，不传任何凭据 |
| 撤销 | 无需撤销（免 Key）；自托管版自行停用容器 |

> Windows 上调用务必带 `--ssl-no-revoke`，否则会因证书吊销检查离线误报失败。

---

## qweather（可选，国内精度天气备源）

| 项 | 说明 |
|---|---|
| 官方入口 | https://www.qweather.com/ |
| 开发者入口 / 文档 | https://dev.qweather.com/ |
| 控制台 / 登录 | https://console.qweather.com/ |
| 凭据获取 | https://console.qweather.com/ 创建项目后生成 Key |
| 鉴权 | **需实名认证 + API Key**；免费版 endpoint `devapi.qweather.com` |
| 权限范围 | `weather`（读取天气预报）；不要申请与行程无关的权限 |
| 凭据存储 | 只存本机环境变量 `QWEATHER_API_KEY`，**不入仓库、不进产物、不写进技能文件** |
| 免费档 | 按月计数（官方 2025-03-01 公告为 5 万次/月，QPS 10；此后是否再调整请以控制台为准） |
| 署名 | 必须署名「数据由和风天气提供」 |
| 验证 | 配好 Key 后请求 7 天预报：`https://devapi.qweather.com/v7/weather/7d?location=101210101&key=<KEY>`；未带 Key 时实测返回 403 |
| 轮换 / 撤销 | 在控制台重新生成或删除该 Key；旧 Key 立即失效 |
| 未配置时 | 直接跳过，天气走 Open-Meteo + 兜底，不影响主流程 |

---

## nominatim（可选，坐标备源，免 Key）

| 项 | 说明 |
|---|---|
| 官方入口 | https://nominatim.org/ |
| 使用政策 | https://operations.osmfoundation.org/policies/nominatim/ |
| 鉴权 | 无（免 Key） |
| 验证 | `curl -s --ssl-no-revoke "https://nominatim.openstreetmap.org/search?q=杭州&format=json&limit=1"` 应返回 JSON 数组；实测 200 / 1.1–2.2s，3/3 成功 |
| 合规 | 数据 ODbL，**必须署名** `© OpenStreetMap contributors`；须设可识别 User-Agent |
| 限额 | 公开实例 fair use，建议 < 1 次/秒、不批量并发 |
| 撤销 | 无需撤销 |

---

## amap（可选，POI 与坐标备源）

| 项 | 说明 |
|---|---|
| 官方入口 | https://lbs.amap.com/ |
| MCP 文档 | https://lbs.amap.com/api/mcp-server/gettingstarted |
| 控制台 / 登录 | https://console.amap.com/dev/key/app |
| 凭据获取 | 在 https://console.amap.com/dev/key/app 创建应用并申请「Web 服务」类型的 Key |
| 接入方式 | 官方 MCP `https://mcp.amap.com/mcp?key=<KEY>`（Streamable HTTP，推荐）；或 `npx -y @amap/amap-maps-mcp-server`（env `AMAP_MAPS_API_KEY`）；或直连 Web 服务 REST |
| 鉴权 | **需实名认证 + API Key** |
| 权限范围 | 地理编码 / POI 搜索 / 周边搜索；不要开通与行程无关的服务 |
| 凭据存储 | 只存本机环境变量 `AMAP_MAPS_API_KEY`，**不入仓库、不进产物**；建议同时配置 IP 白名单 |
| 验证 | `curl -s --ssl-no-revoke "https://restapi.amap.com/v3/weather/weatherInfo?city=330100&key=<KEY>"`；未带 Key 时实测返回 `{"status":"0","info":"INVALID_USER_KEY"}` |
| 配额 | 个人开发者配额**按月计算**，公开资料口径不一致（5,000/日、1 万/月、15 万/月等多种说法），**以控制台实际显示为准** |
| 合规 | **服务条款禁止存储原始地理数据** —— 只能当次使用，不写进缓存、不写进 `sources/` 快照；坐标 GCJ-02；商用需购买授权 |
| 轮换 / 撤销 | 在 https://console.amap.com/dev/key/app 删除或重置该 Key |
| 未配置时 | 直接跳过，POI 走 FlyAI + Nominatim，不影响主流程 |

---

## overpass（可选，尽力而为，不要依赖）

实测日期 2026-10-05，**多数公共镜像在当前网络不可用**：

| 镜像 | 实测结果 |
|---|---|
| `overpass-api.de` | `/api/interpreter` 稳定返回 406；Python 侧 3/3 TLS 握手失败 |
| `overpass.kumi.systems` | 3/3 失败（连接被对端关闭 / 读超时） |
| `overpass.private.coffee` | 3/3 失败 |
| `maps.mail.ru/osm/tools/overpass` | 偶尔 200，但耗时 12–33 秒，复测出现 504 |

| 项 | 说明 |
|---|---|
| 官方入口 | https://overpass-api.de/ |
| 官方文档 | https://wiki.openstreetmap.org/wiki/Overpass_API |
| 鉴权 | 无（免 Key） |
| 调用 | `curl -s --ssl-no-revoke -X POST "https://overpass-api.de/api/interpreter" --data-urlencode 'data=[out:json][timeout:15];node[tourism=attraction] (around:2000, 纬度, 经度);out count;'`（`]` 与 `(` 之间的空格仅为文档可读性，实际请求去掉） |
| 使用纪律 | **超时设 ≤ 15 秒，超时即放弃**；多镜像依次尝试但**不并行**；带可识别 User-Agent；不得重试风暴 |
| 合规 | 数据 ODbL，署名 `© OpenStreetMap contributors`；派生数据库 share-alike；公开实例 fair use，建议 < 1 万次/日 |
| 说明 | 该源**只作尽力而为的补充**，失败即走 Nominatim / 高德 / 通用搜索，**不得阻塞流程** |

---

## host-web-search（必需）

| 项 | 说明 |
|---|---|
| 用途 | 攻略、餐饮、市内交通与所有兜底检索；天气仅在 Open-Meteo 不可达时兜底 |
| 依赖形态 | 由宿主 Agent 环境提供，无需安装 |
| 主要数据源 | 12306（时刻与站名）；攻略站与餐饮点评；天气兜底为 https://www.weather.com.cn/ （**页面抓取，无公开免费 API，DOM 变更即失效**）与 `https://wttr.in/`（**个人维护、无 SLA、按 IP 限流**） |
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
