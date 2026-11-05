---
name: travel-planner
description: 生成详细的多日旅行计划，输出为中文单文件 HTML 页面，按目的地定调专属配色、地标与展示字体，涵盖逐日天气、每日行程（景点+交通）、餐饮推荐（含人均）、酒店对比和分级预算。数据来自 FlyAI CLI（飞猪航班与机票实时报价、酒店与门票价格档位、火车车次）、Open-Meteo（免 Key 天气与地理编码）、mcporter（小红书真实住客反馈）与通用网络搜索，所有价格标注实查/参考/估算三级可靠度。目的地未知时先做候选发现、季节陷阱检查、人群适配与天气对比，再进入行程编排。适用于个人自由行、家庭出游（含婴幼儿/老人）、多人旅行。当用户提到旅行计划、旅游攻略、出行规划、行程安排、去哪里玩、假期安排、目的地推荐、holiday plan、travel itinerary、trip planning 时使用；用户只给了时间和人员、未定目的地时也触发。不适用于单点查询（如只问某景点票价）、已有机票酒店的纯预订操作，以及会议日程、搬家安排等非旅行排期。
version: "1.4.0"
agent_created: true
---

# Travel Planner

生成结构化、可操作的旅行计划，输出中文单文件 HTML 页面。信息来自实时检索，不靠记忆。

## 边界

**做**：多日行程编排、目的地推荐决策、天气与衔接风险核查、分级预算、单文件 HTML 交付。

**不做**：代订机票酒店；单点问答（"某景点门票多少"直接答，不走本流程）；把未核实的价格说成实时报价；在没有可用数据通道时凭记忆编行程。

## 第零步：依赖就绪检查

执行任何检索之前先跑只读自检。分两步：先收集**最小只读探测**结果（CLI 探针与 Key 有效性由宿主执行，检查器本身不跑探测、不碰凭据），再跑检查器。

```bash
python scripts/collect_self_probe.py --output "$TEMP/probe-results.json"
python scripts/check_environment.py --network --probe-results "$TEMP/probe-results.json"
```

- 第一步只做只读探测：`flyai keyword-search` 探针、`mcporter list` 探针、以及 `QWEATHER_API_KEY` / `AMAP_MAPS_API_KEY` 存在时的一次最小校验请求。**不回显、不落盘任何 Key 值。**
- 第二步按 `skill-dependencies.json` 校验并输出结构化状态；包含匿名 HTTPS 健康探测（Open-Meteo 等），所以需要 `--network`。
- 结果文件是脱敏状态码，不是凭据；写到技能包**外**的目录（示例用系统临时目录），避免产物被打包分发。采集器写到包内时会在 stderr 提示。

**探测判定口径（不要改回"看退出码"）**：

- FlyAI 的**进程退出码不可信**——参数非法、日期越界、风控等业务失败仍以退出码 0 结束。采集器只认 JSON 信封：`status == 0` 且 `data` 非 null 才算可用；`status != 0` 按 `message` 归类（配额 / 鉴权 / 参数）；`status == 0` 但 `data` 为 null（如 `message=empty`）保守记为不可用。
- `mcporter-probe` 只证明**命令行可执行**，不代表已注册小红书检索服务；服务是否可用要以 `mcporter list` 的实际输出为准。
- 未配置 Key 记为 `missing` + `configuration_invalid`（是"没配"，不是"Key 失效"）；配了但被拒才是 `unavailable` + `auth_expired_or_invalid`。

| 状态 | 含义 | 动作 |
|---|---|---|
| `ready` | 必需项全通（FlyAI、Open-Meteo、包内生成器） | 直接进入正常流程，不要讲配置教程 |
| `partial` | 必需项可用，但有可选项缺失（小红书通道、国内精度天气备源、POI 备源） | 照常执行，仅在缺失维度标注来源降级，不要把可选项当成故障 |
| `needs_setup` | 缺 flyai / node / Open-Meteo 不可达 | 只展示缺失项的配置步骤（见 `references/setup-guide.md`），并同时给出"仅用通用搜索"的降级选项 |
| `unavailable` | 包体不完整，或必需源探测失败 | 先分辨是否只是"探测未执行"（见下方提醒）；确认是真实故障再停止，并说明原因 |

> ⚠️ 只跑 `check_environment.py` 而**没传 `--probe-results`** 时，CLI 与 Key 类探测会返回 `probe_required`，整体状态会被误判为 `unavailable`。这只是"探测未执行"，**不是环境故障**，不得据此停止流程——按上面的两条命令补齐探测后重跑即可。

依赖清单、版本与降级策略见 `skill-dependencies.json`。用户拒绝配置时按降级执行，不得改用推测数据顶替。

## 可用数据通道

| 通道 | 类型 | 调用方式 | 用途 |
|---|---|---|---|
| FlyAI CLI | npm CLI | `Bash: flyai ...` | 航班与机票实时报价、酒店与门票价格档位、火车车次。**仅机票 `ticketPrice` 是精确值**，预算"实查"等级只由它产生 |
| Open-Meteo 天气 | 免 Key HTTP | `Bash: curl "https://api.open-meteo.com/v1/forecast?..."` | **天气主源**。免 Key、结构化 JSON、≤16 天逐日预报。实测最稳最快 |
| Open-Meteo 地理编码 | 免 Key HTTP | `Bash: curl "https://geocoding-api.open-meteo.com/v1/search?..."` | **坐标主源**。中文地名 → lat/lon，供天气、POI、距离计算共用 |
| 和风天气（可选） | HTTP + API Key | 配置后调用 `devapi.qweather.com` | 中国城市精度备源；需实名 + Key |
| 高德 / Overpass（可选） | HTTP + API Key / 免 Key | 见 `references/setup-guide.md` | POI 与坐标备源；高德需 Key 且**原始地理数据不得落库**，Overpass 实测多数公共镜像不可用 |
| mcporter | npm CLI | `Bash: mcporter list` 后再调用 | 小红书笔记检索。**可选、需用户自配、默认降级** |
| 宿主通用网络搜索 | 宿主工具 | 直接调用 | 攻略、餐饮、市内交通与所有兜底检索 |

**关键取舍**：天气与坐标走 Open-Meteo（免 Key、实测可用），不要再用页面抓取或 wttr.in 主位；Overpass 只作尽力而为，失败即降级，不得阻塞流程。

**不得把任何包外 Skill 作为运行时依赖。** HTML 生成由本技能自带规范与包内生成器承担。

**委派给子 Agent 时**，prompt 里必须写明用 Bash 调 CLI，否则子 Agent 只会用通用搜索：

```
Use Bash to run these commands for real-time data:
- flyai search-flight --origin "成都" --destination "昆明" --dep-date 2026-04-02
- flyai search-train --origin "成都" --destination "昆明" --dep-date 2026-04-02
- flyai search-hotel --dest-name "弥勒" --check-in-date 2026-04-03 --check-out-date 2026-04-05
- curl -s --ssl-no-revoke "https://geocoding-api.open-meteo.com/v1/search?name=弥勒&count=5&language=zh"
- curl -s --ssl-no-revoke "https://api.open-meteo.com/v1/forecast?latitude=<lat>&longitude=<lon>&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=16&timezone=auto"
For community feedback, run `mcporter list` FIRST to discover the actual tool name,
then call it. Never hardcode xiaohongshu.search_feeds — implementations differ.
Fall back to the host web search when these fail or return nothing.
```

> 在 Windows 上 `curl` 走 Schannel，证书吊销检查离线时会报 `CRYPT_E_REVOCATION_OFFLINE`（`curl: (35)`，表现为 `http=000`）。这**不是对方服务故障**。所有 HTTPS 请求都必须带 `--ssl-no-revoke`，或改用 Python `urllib`。见到 `000` 一律换第二种方式复核后再判定"不可达"。

## 第一步：收集旅行要素

已知的跳过，缺失的向用户询问。

| 要素 | 说明 | 必需 |
|---|---|---|
| 出发地 | 决定交通方案与可达性筛选 | 是 |
| 出行日期 | 具体日期或月份 | 是 |
| 天数 | 行程总天数 | 是 |
| 人员构成 | 谁去、有无老人小孩（含年龄） | 是 |
| 目的地 | 城市或地区，**可为空**（进入推荐流程） | 否 |
| 预算范围 | 总预算或每日预算 | 否 |
| 偏好 | 饮食禁忌、兴趣方向、小众或热门、体力水平 | 否 |

## 第二步：目的地推荐（目的地未知时）

先筛选再规划。阶段间有严格依赖，不得跳步：

- **A**（按区域并行）：候选发现 + 季节陷阱检查 + 人群适配 → 候选短名单
- **B**（依赖 A）：仅对短名单搜交通 → 可行性排名
- **B2**（依赖 A，与 B 并行）：出行日期天气预报 → 降雨天数统计
- **C**（依赖 B + B2）：横向对比并给出明确排名，交用户决策

用户给的是区域（如"广西""云南"）而非具体城市时，必须先检索候选地，严禁凭一般知识预设。

**A1 候选发现**——用真实旅行产品反推目的地，而不是先想地名：

```bash
flyai keyword-search --query "[区域] [天数]天 自由行"
flyai keyword-search --query "[区域] [月份] [特殊人群]游 攻略"
flyai keyword-search --query "[出发地]出发 [区域] [天数]日游"
```

再用小红书记录真实用户验证过的目的地，最后用通用搜索补攻略型推荐。

**A2 季节陷阱**：核对核心吸引物在出行时段是否处于最佳状态（瀑布枯水期、花海花期、海滩台风季、雪场化雪）。

**A3 人群适配**：有婴幼儿时评估推车友好度、母婴设施、医疗距离、安全风险、节奏适配；有老人时额外评估海拔高反、无障碍设施、医疗可及性。

**B2 触发条件**：出发日距今 ≤ 16 天时强制执行（Open-Meteo 预报上限 16 天），超出则跳过并标注"超出预报范围"，改用历史同期均值；**淘汰规则**：降雨天数 ≥ 50% 降权，带婴幼儿或老人时连续降雨 ≥ 3 天建议排除。

对比维度与权重：交通可达性（最高）· 出行日期天气（最高）· 人群适配（高）· 季节时令（高）· 小众度（中）· 景点丰富度（中）· 费用（低）。

## 第三步：多维信息采集

目的地确定后进入深度采集，用子 Agent 并行提效。

### 天气（前置，影响穿衣与行程）

**B2 已取到就复用，不重复检索。** 未执行时按此优先级获取逐日预报，不得只靠搜索引擎的笼统描述：

**第 1 顺位 —— Open-Meteo（免 Key，实测最稳）**

先用地名换坐标（不要凭记忆估经纬度）：

```bash
curl -s --ssl-no-revoke "https://geocoding-api.open-meteo.com/v1/search?name=[城市]&count=5&language=zh"
# 取 results[0].latitude / longitude
curl -s --ssl-no-revoke "https://api.open-meteo.com/v1/forecast?latitude=[lat]&longitude=[lon]&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=16&timezone=auto"
```

返回 `daily.time` / `weather_code` / `temperature_2m_max` / `temperature_2m_min` / `precipitation_probability_max`，逐日对齐。

**第 2 顺位 —— 和风天气（国内精度备源，需 Key）**：`devapi.qweather.com`，中国城市精度更好；未配 Key 时直接跳过。

**第 3 顺位 —— 兜底（只标"参考"）**：宿主通用搜索，含中国天气网页面与 `curl "https://wttr.in/[城市]?format=j1"`。二者的已知局限必须一并说明——中国天气网是**页面抓取、无公开免费 API、DOM 变更即失效**；wttr.in 是**个人维护的社区服务、无 SLA、按 IP 限流**，NAT 环境下易被连带封禁。

> 不要把中国天气网或 wttr.in 放回主位；也不要引用 AccuWeather（需注册 Key，且本技能未配置）。

**取到后必须做日期覆盖校验**：核对 `daily.time` 是否覆盖出行区间。不覆盖即标注"超出 16 天预报范围"，改用 Open-Meteo Archive（`archive-api.open-meteo.com/v1/archive`）取同期历史均值，并明确写"历史同期均值，非预报"。

逐日输出：日期、天气状况、最高最低气温、降水概率、穿衣建议。

### 交通与衔接验证

```bash
flyai search-flight --origin "[出发地]" --destination "[目的地]" --dep-date YYYY-MM-DD --sort-type 3
# 往返加 --back-date，直飞加 --journey-type 1，限价加 --max-price
flyai search-train --origin "[出发地]" --destination "[目的地]" --dep-date YYYY-MM-DD
# 返回真实车次号与时刻（实测 G963 北京南 10:35 → 厦门北 21:15，历时 640 分钟）
```

**响应必须先校验再解析。** 每次调用后先确认 `status == 0` 且 `data` 非 null，再解析 `data.itemList`。FlyAI 有两种失败模式，处置方式完全不同：

| 失败模式 | 特征 | 处置 |
|---|---|---|
| 查询偶发失败 | 返回 `{"data":null,"status":1,"message":"…"}` | 原样重试**一次**；仍失败即记为该查询"未取到"，转通用搜索并降级标注 |
| 风控限流 | HTTP 403，正文含 `Abnormal access behavior detected by risk control` | **不要立即重试**。这是短时间高频请求触发的限流，立刻重试只会延长封禁：停止查询，退避 ≥ 45 秒，之后把请求间隔放宽到 ≥ 12 秒再继续 |

两种模式都不得反复重试到出结果，也不得凭记忆补航班号或车次号。**批量查询时必须从一开始就限速**——多目的地 × 多品类的采集（如四城各查机票、火车、酒店、四类景点）很容易在 1 分钟内打满上百次请求而触发风控，逐次串行并留间隔，比事后退避省时间。

**事前节流（默认执行，不是可选）**：FlyAI 请求**串行**发送、两次之间间隔 **≥ 3 秒**；同一 (城市, 品类, 日期) 组合**批内去重**，命中即复用不重复查；单次行程的 FlyAI 请求总数控制在 **40 次以内**。命中风控后按上表退避，并把间隔放宽到 ≥ 12 秒。

根因（可观测结论）：该 CLI 每个请求都携带用于**风控与客户端环境一致性校验**的环境指纹，因此高频批量必然被判定异常；同时**不要去改设备标识**，那会影响鉴权与签名一致性。

火车票用 `search-train` 取真实车次与时刻（比通用搜索可靠），票价仍是脱敏档位，须到 12306 核对；市内交通用通用搜索。**涉及转机或转高铁时必做衔接验证**：A 的到达时间与 B 的末班时间、A→B 转场方式与耗时、缓冲是否 ≥ 1.5 小时。不可行时改更早班次、到达城市住一晚、或直接包车跳过。行程中必须显式标注衔接风险，如"末班高铁约 21:00，建议选 17:00 前落地的航班"。

### 景点

```bash
flyai search-poi --city-name "[目的地]" --category "历史古迹"
# --category 必须传中文值（历史古迹 / 自然风光 / 古镇古村 / 博物馆 / 温泉…）
# --help 打印的分类清单是英文，照抄会直接报错并返回可用中文值
# 可选 --keyword "景点名"、--poi-level 5
```

字段可用性（实测 2026-09-13 共 34 条样本；2026-10-05 复测 10 条）：

- `freePoiStatus`（`FREE` / `NOT_FREE` / `UNKNOWN`）可靠，可直接决定该项是否计入门票预算。
- `ticketInfo.price` **不可当精确价**：34 条中 28 条为空、4 条为脱敏档位（如 `¥2x`）、仅 1 条为精确值；10-05 复测为 1/10 有值。只能按参考价处理并加 `~`。
- `poiLevel`（景点等级）实测仅 2/10 有值，缺失时不要编造等级。
- `latitude` / `longitude` 直接支撑第四步的地理聚类，按坐标判断远近，不要凭记忆估。

**坐标必须交叉核对（坐标错了第四步聚类直接失真）**：
- 备源 1 —— **Nominatim（免 Key，实测可用）**：`curl -s --ssl-no-revoke "https://nominatim.openstreetmap.org/search?q=[景点名]&format=json&limit=1"`。须署名 `© OpenStreetMap contributors`。
- 备源 2 —— **高德（可选，需 Key）**：可补评分、营业时间，中文地址体系完善。**服务条款禁止存储原始地理数据**，只能当次使用、不写进缓存或 `sources/` 快照。坐标是 GCJ-02，与 Open-Meteo 的 WGS-84 若混用需注意偏移。
- 备源 3 —— **Overpass / OSM（尽力而为，不得阻塞流程）**：实测多数公共镜像不可用，只有在 15 秒内返回才采信，否则立即降级，不要重试风暴。

**多源去重规则**：坐标距离 < 100m 且名称相似 → 合并为一条；门票是否计入以 FlyAI 的 `freePoiStatus` 为准。

小众推荐用通用搜索补充。

### 住宿

```bash
flyai search-hotel --dest-name "[目的地]" --check-in-date YYYY-MM-DD --check-out-date YYYY-MM-DD
# 可选 --poi-name "景点名"、--hotel-stars "4,5"、--max-price 800、--sort price_asc
```

返回字段的可靠度并不一致，按实测口径使用：

- `price` 是**脱敏价格档位**（如 `¥6xx`），不是指定日期的精确报价 —— 只能按参考价处理并加 `~`，**不得标"实查"**。
- `star` 是档位描述（如"豪华型"），可用于筛选与对比。
- `detailUrl` 是可直接给用户的预订入口。
- 房源**没有评分字段**（`rate`、`score` 实测均为 null），交付时不要给出评分或"住客评分 4.5"之类的表述。

### 餐饮

通用搜索"必吃美食""当地人推荐"，取人均价格。

### 小红书真实反馈（可选，默认降级）

**配置口径**：本通道是**可选、用户自配、默认降级**。不硬编码任何端口、地址或凭据；由用户用 `mcporter` 注册自选的小红书 MCP 实现。若 `mcporter` 未安装或未注册服务，直接走下面的降级路径，**不要把可选项当成故障去排查**。

**工具探测口径**：不同实现的工具名与参数不一致（常见 `search_feeds` / `get_feed_detail` / `user_profile`）。**先探测再调用**：

```bash
mcporter list                                  # 先确认有哪些服务
# 再按实际服务名与工具名调用，不要照抄下面的示例
mcporter call <服务名>.<工具名> keyword="[目的地] 亲子游 带娃"
```

探测失败即转降级，**绝不硬编码 `xiaohongshu.search_feeds`**。

**风险声明（必须展示给用户后再调用）**：现有社区实现均为「载入用户本人账号 Cookie + 用页面内置签名函数发内部 API 请求」，属驱动真实账号，存在平台 ToS 与封号风险，且涉及抓取用户生成内容。使用要求：**只读、低频、不得发布或互动**。

**降级**：用通用搜索检索小红书公开内容与攻略站，交付时声明来源降级——**不得声称拿到了原帖内容或引用不存在的笔记**。

采集判据、计费口径与编排细则见 `references/research-playbook.md`。

## 缓存与限速

**每次生成行程都重打一遍接口是当前最大的浪费，也是风控的根因。** 所有外部请求前先查缓存。

| 项 | 约定 |
|---|---|
| 位置 | 用户工作目录 `[目的地]-[年-月]/.cache/`，与产物同目录，便于随行程归档。**不写进技能仓库** |
| 键 | `源 + 规范化参数 + 查询日期`（如 `open-meteo-forecast_30.29_120.16_2026-10-20.json`） |
| TTL | 天气 30 分钟；POI / 坐标 24 小时；车次时刻当日；价格 30 分钟；静态资产（12306 站名表、城市坐标）长期 |
| 范围纪律 | 只缓存本次行程相关的最小片段；**高德原始地理数据不落盘**；OSM 派生数据若落盘须保留署名 |

**限速**：FlyAI 请求串行 + 间隔 ≥ 3 秒 + 批内去重，单次行程总额 ≤ 40 次（详见"交通与衔接验证"一节）。Open-Meteo 免 Key 且非商用 < 10,000 次/日，正常使用远低于阈值，但也应走缓存避免重复请求。

**缓存读写必须容错（重复调用场景）**：

- 读缓存前先确认是完整 JSON 再采信。解析失败、字段缺失、文件为空一律**按未命中处理并覆盖重写**，不得因缓存损坏中断流程，也不得把半截数据当成实查结果。
- 写缓存用"先写临时文件再改名"的方式，避免中断留下半截 JSON 被后续误读。
- 同一行程内命中同一键直接复用，不再发请求；条目超出 TTL 时重新取数并整条覆盖，不做增量合并。
- 缓存与产物同目录随行程归档，属于用户数据；**不得写进技能仓库**，也不要誊抄进交付正文。

## 第四步：行程编排

1. 地理聚类：相近景点同一天
2. 节奏交替：暴走日后接休闲日
3. 就近用餐
4. 每天留 1-2 小时缓冲
5. 到达日只安排入住与周边

婴幼儿场景：每日最多 2 个景点，13:00-15:00 不安排活动或安排车程，逐景点标注是否需要推车，餐厅优选有儿童座椅的。老人场景：每日步量 < 1.5 万步，避免海拔 > 3000m。

每日结构：上午景点 + 交通 / 午餐 / 下午景点或休闲 / 晚餐 / 夜间活动。

## 第五步：预算编制

**每项费用必须标注可靠度**，不得混用：

| 等级 | 来源 | 标注 |
|---|---|---|
| 实查 | 12306、景区官网，或 FlyAI 的机票 `ticketPrice` | 无标记 |
| 参考 | FlyAI 返回的酒店 / 门票 / 火车票档位价，检索所得区间价、起步价、往年价 | 价格后加 `~` |
| 估算 | 无直接数据源，按同类经验推断 | 价格后加 `≈` |

除机票外，FlyAI 返回的酒店、门票、火车票价格均为脱敏档位（`¥6xx`、`¥2x`、`9xx`），**不得标"实查"**。

分类：交通（大交通 + 市内）· 住宿（房价 × 间数 × 晚数）· 餐饮（人均 × 人数 × 餐数）· 门票 · 其他（保险、伴手礼）。

最后给出预估总费用与人均费用，并注明"含参考价成分，实际以预订为准"。

## 第六步：生成 HTML

完整结构、字段、技术注意与验收标准见 `references/html-spec.md`。

**先定调，再排版。** 城市定调的方法（三轴、色相推导四步、地标 SVG 规范、对比度门槛、反例清单）见 `references/city-design.md`。目标不是好看，而是**遮住标题后仍能认出这是哪座城市**。只换配色不换构成、或用通用线性图标充当地标，都算未完成定调。

**主路径**：按规范直接撰写单文件 HTML，按目的地特征自由设计布局与结构，不同目的地的页面应在**布局结构**上有明显差异，而非只换配色。

**降级路径**：需要确定性产物时用包内生成器。

```bash
python scripts/generate.py <tripData.json> <输出.html>
# 需要"数据不完整就不产出"时加 --strict；不想看结构告警加 --quiet
```

生成器走模板渲染，城市定调通过 `tripData.theme` 可选字段传入（色板 + 地标 SVG + 展示字族），不提供 theme 则产出中性页面。字段定义与地标安全校验规则见 `references/html-spec.md`；`assets/examples/` 下有四份成品可作参照。

生成器把校验分成两档，**先看清是哪一档再处理**：

| 退出码 | 含义 | 处置 |
|---|---|---|
| `0` | 产物已写出。可能同时打印结构告警（字段类型异常、区块缺失或为空） | 产物可用，按告警补齐数据后重跑；**不要因为看到告警就以为失败** |
| `1` | 输入问题：文件不存在、非 UTF-8（含 GB18030 / UTF-16）、JSON 非法、顶层非对象、输出目录不存在、输出与输入同路径、`--strict` 下存在告警 | 按 stderr 首行提示修数据或改路径 |
| `2` | 模板问题：模板缺失，或模板占位符与生成器映射不一致 | 改模板时必须同步更新生成器的映射 |

数据缺失**不会**让生成失败：模板按区块降级渲染，缺的区块显示空态提示（`暂无行程数据` 等），其余区块照常渲染；单个区块渲染异常也被隔离，不影响其他区块。想确认某份数据是否够完整，用 `--strict` 跑一次即可。

产物必须单文件、全部内联、不引外部 CDN、断网可打开。**内联数据必须转义**：生成器把 `&` `<` `>` 与 U+2028/U+2029 写成 `\uXXXX`（`</` 与 `<!--` 因此都不再出现），标量占位符走 HTML 转义、模板内插值统一走 `esc()`，且替换是**单遍**的——数据里出现的 `{{...}}` 字面量会被原样保留，不会被二次替换。手工撰写 HTML 时同样要处理这三件事。

输出到用户工作目录下的独立文件夹 `[目的地]-[出发年-月]/`，不要写进技能仓库。

## 停止条件

命中任一条立即停止，不得用记忆或推测填充：

- 自检返回 `unavailable`（且已排除"未传 `--probe-results` 导致探测未执行"这一情形）；
- 天气、交通、景点、住宿四类中**交通与天气两类都拿不到**任何可靠数据；
- 关键衔接无法验证且三条替代方案均不可行；
- 用户拒绝配置依赖且不接受"仅参考价"的降级标注。

**可选项不触发停止**：小红书通道、和风天气、高德、Overpass 属于可选或尽力而为的源，缺失或不可用时按降级路径继续，不得因此中断，也不得把它当作必需依赖去排查。

停止时说明已取得的部分、缺失的部分和恢复步骤，已获得的结果照常交付但逐项标注限制。

## 交付时必须声明

```
实查数据：天气预报（Open-Meteo）、12306 高铁票价、FlyAI 机票精确报价与航班号
参考数据：FlyAI 返回的酒店/门票/火车票档位价（已脱敏）、通用搜索得到的起步价与区间价
估算数据：无直接来源的市内交通与零散支出
需用户确认：出行当日的高铁衔接班次
```

**来源署名与合规（产物必须附带）**：用到哪个源就附哪一条，未使用的不要写。

| 源 | 署名 / 合规口径 |
|---|---|
| Open-Meteo | 数据 CC BY 4.0，署名 `Weather data by Open-Meteo.com`；非商用 < 1 万次/日，商用需订阅或自托管 |
| FlyAI | 飞猪 MCP；按 `detailUrl` 引导去飞猪 / 携程落实 |
| 和风天气 | 署名「数据由和风天气提供」 |
| 高德 | **不得存储原始地理数据**；需实名；商用需授权；坐标 GCJ-02 |
| OSM / Nominatim | ODbL，署名 `© OpenStreetMap contributors`，派生库 share-alike |
| 小红书 MCP | 平台 ToS 与账号风险，用户自担 |
| 12306 | 无官方开放 API，社区实现仅研究用途；票价以官方为准 |

并提醒用户两件事：通过 FlyAI 返回的 `detailUrl` 在飞猪或携程落实机票与酒店；到 12306 核对出行当日的衔接班次与票价，尤其是涉及机场到火车站转场的行程。

## 回归测试

改动生成器、模板或依赖清单后，跑这两条命令做回归。两条都**不联网、不启动子进程**，可在任何环境直接执行：

```bash
python -B scripts/selftest.py                  # 脚本层：输入校验、转义、单遍替换、原子写、探测判定、清单一致性
node tests/render_runtime_check.js             # 模板运行时：缺字段降级、注入拒绝、转义往返
node tests/render_runtime_check.js --extra-html <生成产物.html>   # 追加端到端冒烟
```

- `selftest.py` 覆盖：异常输入（非 UTF-8、BOM、空文件、顶层数组、截断 JSON、NaN 常量）、退出码契约、写入失败后的清理与幂等、探测器判定口径、结果文件对 `probe-results` schema 的合规性、以及清单与 `references/setup-guide.md`、采集器的三方一致性。末尾会打印断言总数与失败项。
- `render_runtime_check.js` 用最小 DOM 桩执行模板内联脚本，覆盖数据完整、仅有标题、字段类型错误、预算全零、主题净化、逃逸往返、嵌套字段转义七类场景。
- 必须用 `python -B`：否则导入会在 `scripts/` 下留下 `__pycache__`，预检会把它判为无法静态分析而阻塞打包。
- 四份示例成品是生成器的纯输出，可随时用 `assets/examples/sources/tripData-<城市>.json` 原样重生成；改模板后应重生成一次以保持包内一致。
- 两个测试自身的有效性也要看：`selftest.py` 里对结果校验器有反向断言（故意喂违规数据必须报错），避免出现"校验器永远通过"的假阳性。
