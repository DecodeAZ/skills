# 指纹规则库（scripts/fingerprint.py 的 PATTERNS）

## 已验证规则（zmka 站点实测命中）

| 字段 | 正则 | 作用域（文件名包含） | 说明 |
|---|---|---|---|
| vue | `var\s+er="(2\.\d+\.\d+)"` | chunk-libs | Vue 2 内核版本串 |
| vue_router | `Ht\.version="([\d.]+)"` | chunk-libs | vue-router（minify 后变量名，换构建工具可能变） |
| vuex | `Store:\w+,install:\w+,version:"([\d.]+)"` | chunk-libs | Vuex 3.x |
| vue_i18n | `K\.version="([\d.]+)"` | chunk-libs | vue-i18n 8.x |
| axios | `\[Axios v([\d.]+)\]` | chunk-libs | axios 调试串，最可靠 |
| core_js | `version:"(3\.\d+\.\d+)",mode:` | chunk-libs | core-js 3 |
| core_js_2 | `\{version:"(2\.6\.\d+)"\}` | chunk-libs | 打包内 core-js 2 遗留副本 |
| nprogress | `n=\{version:"([\d.]+)"\}` | chunk-libs | NProgress（易误报，必须限作用域） |
| element_ui | `version:"(2\.\d+\.\d+)"` | chunk-elementUI | Element UI |
| cesium | `Version\s+([\d.]+)` | Cesium.js | 文件头 license 注释 |
| sockjs/stomp | 关键词 `SockJS` / `stompClient` | 任意 | 存在性标记 |

## 使用纪律（防止误报）

1. **必须限定作用域**：`version:"x.y.z"` 这类宽泛正则曾在 Cesium.js 里匹配出假 vue-router 版本（3.15.0 是误报）。新规则一律带 scope 字段。
2. **版本一致性交叉验证**：同一组件若在多个产物命中，取值不一致时以组件自身 chunk 为准（如 element-ui 以 chunk-elementUI 为准，chunk-libs 里的 2.6.12 实为 core-js 2）。
3. **生命周期标注**：报版本时同时标注 EOL 状态（Vue 2.7.16 EOL / Element UI 2.x 停更 / vue-i18n 8.x 停更）。

## 扩展新组件的方法

1. 先在产物里 `grep -ao "version" <bundle>` 定位版本串上下文，再写带锚点的正则（不要裸匹配 `version:"..."`）。
2. 加进 `PATTERNS`，scope 填该组件的 chunk 文件名片段。
3. 用同站点旧结果回归：新规则不得改变已有字段取值。
4. 后端栈识别不靠正则，靠行为：`{timestamp,status,error,message,path}` 错误体 + Whitelabel 页 → Spring Boot；`Vary: Origin` + 401 空体 → Spring Security。
