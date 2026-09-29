# HTML 产物规范

## 一、两条路径

**主路径：直接生成。** Agent 按本文件的规范与验收标准撰写单文件 HTML，可以按目的地特征自由设计布局与配色，保留"每次视觉不重复"的能力。

**降级路径：模板渲染。** 需要确定性、可重复的产物时用包内生成器：

```bash
python scripts/generate.py <tripData.json> <输出.html>
```

退出码：`0` 成功 / `1` 输入问题（文件不存在、JSON 非法、输出不可写）/ `2` 模板问题（模板缺失或含未处理占位符）。

## 二、tripData 结构

餐饮以 `meal` 字段嵌在 `activities` 数组里，不是独立的 meals 对象——这与 `assets/template.html` 的渲染逻辑一致。

```javascript
const tripData = {
  title: "目的地 N日游",
  dateRange: "2026-04-05 ~ 04-10",
  travelers: "2大1小",
  generationDate: "2026-09-13",
  weather: {
    summary: "晴为主，偶有阵雨",
    avgHigh: 25, avgLow: 16,
    rainfall: "30%",
    clothing: "短袖+薄外套",
    tips: "注意防晒"
  },
  days: [
    {
      date: "04/05", weekday: "周六", theme: "初见京都",
      weather: { icon: "sunny", high: 24, low: 15 },
      activities: [
        { time: "09:00", name: "伏见稻荷大社", duration: "2h", cost: 0,
          transport: "JR奈良线", note: "千鸟居打卡" },
        { time: "12:00", name: "午餐",
          meal: { name: "餐厅名", cuisine: "日料", perPerson: 80,
                  recommended: "推荐菜", location: "步行5分钟" } }
      ]
    }
  ],
  hotels: [
    { name: "酒店名", area: "区域", pricePerNight: 600,
      highlights: "近地铁;含早餐" }
  ],
  budget: {
    transport:     { items: [{ name: "机票×2", cost: 2000 }], subtotal: 3000 },
    accommodation: { items: [], subtotal: 2400 },
    food:          { items: [], subtotal: 1800 },
    tickets:       { items: [], subtotal: 500 },
    other:         { items: [], subtotal: 300 },
    total: 8000, perPerson: 4000
  },
  tips: ["实用贴士1", "实用贴士2"]
};
```

`weather.icon` 可选值：`sunny`、`cloudy`、`overcast`、`rainy`、`stormy`、`snowy`、`partlyCloudy`。

`hotels[]` 只有 `name` / `area` / `pricePerNight` / `highlights` 四个字段会被 `assets/template.html` 渲染，其余字段被忽略。`pricePerNight` 取自 FlyAI 的脱敏档位价（如 `¥6xx`），填写时按参考价标注。FlyAI 不返回任何评分（`rate`、`score` 实测均为 null），**不要添加 `rating` 或用评分描述酒店**。

`assets/template.html` 使用的占位符共 7 个：`{{TRIP_DATA_JSON}}`、`{{TRIP_TITLE}}`、`{{DATE_RANGE}}`、`{{TRAVELERS}}`、`{{TOTAL_BUDGET}}`、`{{PER_PERSON}}`、`{{GENERATION_DATE}}`。修改模板时必须同步更新生成器的映射，否则生成器会以退出码 2 拒绝执行。新增能力（如 `theme`）**不得引入新占位符**，只能走 `tripData` 的可选字段。

### 可靠度标记的落位

模板把预算的"名称"与"金额"渲染进两个独立单元格（`<td>名称</td><td>¥金额</td>`），所以标记只能挂在**名称尾部**，不能拼进金额。约定：

| 等级 | 标记 | 落位示例 |
|---|---|---|
| 实查 | 无标记 | `{"name": "上海虹桥→成都天府 春秋 9C8819 ×2", "cost": 2396}` |
| 参考 | 尾部加 ` ~` | `{"name": "春熙路区域 3 晚（参考档位 ¥4xx）~", "cost": 1350}` |
| 估算 | 尾部加 ` ≈` | `{"name": "餐饮 人均 120 × 2 人 × 4 天 ≈", "cost": 960}` |

`hotels[].pricePerNight` 同样在值尾加空格与 `~`（如 `"4xx ~"`），渲染为 `¥4xx ~`。

### theme 字段（可选）

提供时覆盖模板的中性默认色板并注入地标；不提供时全部走内置默认、地标槽位自动隐藏。方法见 `references/city-design.md`。

```javascript
theme: {
  name: "成都",                      // 标识用，不渲染
  // 表面与文字
  bg: "#F3F0E7", surface: "#FFFFFF", ink: "#1F2A24", inkBody: "#3D4A42",
  muted: "#58635A", line: "#DFD9CB",
  // 主导色
  primary: "#3F6B4E", primaryStrong: "#2C4E38", primarySoft: "#E3EAE2",
  primaryFaint: "#F1F5F0", primaryLine: "#C3D3C6",
  // 强调色
  accent: "#C1552F", accentStrong: "#9C4223", accentSoft: "#F7EBE4", accentLine: "#E7CBBC",
  // 语义色
  ok: "#356E52", okSoft: "#E4EFE8", warn: "#A8443A", warnSoft: "#F6E7E5",
  sun: "#B8860B", sky: "#3E7C8C",
  // hero 渐变与光斑
  canvasA: "#3F6B4E", canvasB: "#22382C", orb1: "#C1552F", orb2: "#8A9A7B",
  // 预算图表与图例的取色序列
  seq1: "#3F6B4E", seq2: "#8A9A7B", seq3: "#C1552F", seq4: "#A8443A", seq5: "#6E7A70",
  // 地标与展示字
  landmark: '<svg viewBox="0 0 120 80" role="img">…</svg>',
  landmarkCaption: "望江楼 · 竹影 · 锦江",
  fontDisplay: '"Kaiti SC", "STKaiti", "KaiTi", "Noto Serif SC", serif'
}
```

共 31 个字段，缺省不填的字段沿用中性默认。两条校验规则在模板内实现，手工撰写 HTML 时须复现：

- **颜色字段**：只接受 `#RRGGBB`／`#RGB`／`#RRGGBBAA` 形态，不匹配即丢弃该字段，**不做任何转义或净化**。因此色值里的 `;` `}` `url(...)` `expression(...)` 天然无法执行；预期为字符串的字段（如 `fontDisplay`）额外拒绝含 `; { } < >` 的值。
- **`theme.landmark`**：先要求整体以 `<svg` 开头，再依次拒绝
  1. 黑名单标签与属性：`<script`、`<style`、`<foreignObject`、`<iframe`、`<object`、`<embed`、`<link`、`<meta`、`on*=` 事件属性、`javascript:`、`expression(`
  2. 外部引用：`href` / `xlink:href` 的取值以 `//`、`http:`、`https:` 开头

  任一命中即整段弃用，回落为隐藏地标槽位。`landmarkCaption` 走纯文本赋值，不参与上述校验。

`assets/examples/` 下有四份已验证的成品示例（成都、厦门、重庆、北京，均为上海出发 4 日的真实采集数据），可横向比对配色、地标与字族差异，不是需要维护的模板。每份示例的源数据在 `assets/examples/sources/tripData-<城市>.json`，可用生成器原样复现：

```bash
python scripts/generate.py assets/examples/sources/tripData-成都.json 成都-2026-10/成都-4日旅行计划.html
```

最小配色清单与对比度门槛：正文类色值（`ink`、`inkBody`、`muted`、`primary`、`accent`）对 `bg` 与 `surface` 均须 ≥ 4.5:1；图形类（`sun`、`sky`）≥ 3:1；`ok`／`warn` 对各自的 `*Soft` 底须 ≥ 4.5:1；hero 的白字对 `canvasA` 与 `canvasB` ≥ 4.5:1。深色主题城市必须为暗底单独提亮主导色与强调色，不能沿用浅色主题的取值。

## 三、必须包含的区域

概览（标题、日期、人员、总预算、天气摘要）· 逐日天气 · 每日行程（景点/交通/餐饮，可展开折叠）· 住宿推荐（区域、价格档位、亮点、预订链接）· 预算明细（分类汇总 + 可查细项）· 实用贴士。

响应式覆盖 375px / 768px / 1024px，并保证打印友好。

## 四、技术注意（实际踩过的坑）

1. **禁止深层嵌套模板字符串**。JS 模板字符串内嵌 `.map()` 再嵌模板字符串再嵌 `${}` 会解析失败。复杂的 innerHTML 拼接改用 `+` 连接，或抽成独立函数返回片段。
2. **SVG 图标必须有尺寸约束**。裸 SVG 插入 HTML 时若无外部宽高限制会撑满父元素。用 `<span style="width:Npx;height:Npx;display:inline-flex">` 包裹，或直接在 `<svg>` 上加 `width` `height`。
3. **中文与特殊字符用 Unicode 转义**。字符串拼接中 `·` 用 `\u00b7`，`°` 用 `\u00b0`，`¥` 用 `\u00a5`，`→` 用 `\u2192`。
4. **内联数据必须防逃逸**。把 tripData 注入 `<script>` 前，所有 `</` 都要转成 `<\/`，否则数据里出现 `</script>` 会直接闭合脚本块。`scripts/generate.py` 已按此处理；手工撰写 HTML 时同样要处理。
5. **生成后必须验证脚本语法**。用 `node -e` 提取 `<script>` 内容再 `new Function()` 检查，确认无错后再打开浏览器。

## 五、验收标准

- 单文件，CSS 与 JS 全部内联，不引用任何外部 CDN，断网可打开。
- 无残留的 `{{...}}` 占位符。
- 内联数据中没有未转义的 `</`。
- 三个断点下无横向溢出。
- 脚本语法检查通过。
- 所有价格带可靠度标注（实查无标记 / 参考 `~` / 估算 `≈`）。
- 提供了 `theme` 时：全部色值通过第四节的对比度门槛；`landmark` 通过安全校验，且**渲染后的 DOM**（不是源码文本）中不含脚本、事件属性与外部引用。

两条测量口径需注意，否则会得到假结果：

- **三断点必须在真实视口宽度下测。** Windows 上 Chrome 有约 500px 的最小窗口宽度，直接 `--window-size=375` 会被抬高到 497，375 断点根本没被测到。用固定宽度 iframe 承载目标页，读 iframe 内部的 `scrollWidth` 与元素包围盒。判据取 `scrollWidth <= clientWidth`；元素级越界只对**未被 `overflow: hidden/auto` 祖先包裹**的元素有意义（hero 的装饰光斑本身定位在容器外，被 `overflow: hidden` 裁掉，属正常）。
- **地标校验要看渲染结果而非文件文本。** 注入的恶意串本来就该原样存在于内嵌的 `tripData` JSON 里（那是数据，不是 DOM），全文搜索必然误报。要检查的是 `applyTheme` / `renderLandmark` 执行之后，`.hero-landmark` 子树里有没有留下节点或属性。

## 六、输出目录

写入用户工作目录下的独立文件夹，不要把行程产物写进技能仓库：

```
[工作目录]/[目的地]-[出发年-月]/
├── tripData.json
├── [目的地]-[天数]天旅行计划.html
└── sources/            （可选，搜索原始数据快照）
```

文件夹命名：`[主要目的地]-[出发年-月]`，如 `弥勒建水-2026-04`。
