# Skills

可在线安装的 AI Agent 技能集合，兼容 [`npx skills`](https://www.npmjs.com/package/skills) CLI（支持 Trae、Claude Code、Codex、Cursor 等 40+ Agent）。

## 技能目录

| 技能 | 说明 |
|---|---|
| [html-uploader](skills/html-uploader/SKILL.md) | 将本地 HTML 文档上传到文档系统，多系统适配器架构（默认 htmlview-agent-api） |
| [planting-guide](skills/planting-guide/SKILL.md) | 生成城市与场景定制的植物种植/养护指南，输出为单文件 HTML 网页（需 Python 3.10+） |
| [property-report-chapter](skills/property-report-chapter/SKILL.md) | 生成楼盘评估报告的专题章节（户型/价格竞品/交通配套/总结展望），输出为自包含单文件 HTML（需 Python 3.10+，图表 CDN 不可用时降级为静态数据表） |
| [travel-planner](skills/travel-planner/SKILL.md) | 生成多日旅行计划，输出为单文件 HTML 网页，按目的地定调专属配色、地标与展示字体（逐日天气/行程/餐饮/酒店/分级预算，需 Python 3.9+ 与 Node.js 18+；实时报价依赖 FlyAI CLI，小红书反馈依赖 mcporter，缺失时降级为通用检索） |

## 在线安装

```bash
# 安装本仓库全部技能
npx skills add DecodeAZ/skills

# 只安装指定技能
npx skills add DecodeAZ/skills --skill planting-guide

# 先列出仓库内可用技能，不安装
npx skills add DecodeAZ/skills --list
```

常用选项：

- `-g, --global`：安装到用户目录，跨项目生效（默认装到当前项目）
- `-a, --agent <agents...>`：指定目标 Agent（如 `trae`、`claude-code`、`codex`）
- `-y, --yes`：跳过确认，适合脚本与 CI

手动安装（无法使用 Node.js 时的兜底）：把 `skills/<技能名>/` 整个目录复制到对应 Agent 的技能目录，如 `~/.trae/skills/`（Trae）、`~/.claude/skills/`（Claude Code）。

## 仓库结构

```
skills/
  <skill-name>/
    SKILL.md                # 必需：frontmatter 含 name / description，供 CLI 发现
    skill-dependencies.json # 依赖型技能：机器可读的依赖、检查项与功能降级映射
    scripts/                # 可选：技能执行脚本（含 check_environment.py 环境自检）
    references/             # 可选：领域参考与配置指南（如 setup-guide.md）
    assets/                 # 可选：产物模板与成品示例（如 template.html、examples/）
    adapters/               # 可选：配置或适配文件
    config.example.json     # 可选：非敏感配置模板（使用时复制为 config.json）
```

## 新增技能

1. 在 `skills/` 下新建目录，编写 `SKILL.md`（frontmatter 必填 `name`、`description`）。
2. 运行时产物（`config.json`、`_user_meta.json` 等）已在 `.gitignore` 中排除，只提交 `config.example.json` 模板。
3. 在本 README 的技能目录表中登记。
4. 推送后即可通过 `npx skills add DecodeAZ/skills --skill <skill-name>` 在线安装。
