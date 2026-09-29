# 环境与依赖配置

本技能的自包含程度很高：生成骨架所需的一切都在包内，只要运行环境满足要求即可。已就绪的项不必重复配置。

## 1. python-runtime

骨架脚本 `scripts/new_guide.py` 为纯标准库实现，但使用了 `int | None` 联合类型语法，需要 **Python 3.10 或更高版本**；低于该版本会在解析阶段直接报 `SyntaxError`。

- 官方主页：https://www.python.org/
- 官方文档：https://docs.python.org/3/
- 安装步骤：
  1. 从上述官方渠道安装 Python 3.10 或更高版本；
  2. 确认 `python --version` 可执行；
  3. 本技能只用标准库，无需 `pip install`。
- 验证：`python --version`
- 安全：脚本无网络访问、无子进程，只读模板并写入用户指定的输出路径。
- 核验日期：2026-09-13；适用版本 `>=3.10`。

## 2. bundled-template

设计系统与骨架脚本都在包内，缺一不可。

- 官方主页：https://github.com/DecodeAZ/skills
- 官方文档：https://github.com/DecodeAZ/skills/tree/main/skills/planting-guide
- 需要存在的文件：`scripts/new_guide.py`、`assets/guide-template.html`
- 验证：`python scripts/new_guide.py --out <输出路径> --theme leaf` 返回退出码 `0`
- 安全：只读模板并写入指定输出路径；目标文件已存在时会拒绝覆盖，需显式加 `--force`。
- 核验日期：2026-09-13；适用版本 `1.1.0`。

## 3. 城市气候数据

城市气候档案收录在 `references/climate-zones.md`（中国 40+ 城市）。表中没有的城市或境外城市需要联网核查同一组变量（年均温、极端低温、耐寒区、年日照时数、湿度特征、气候事件）；无法联网时按降级处理，只输出与城市无关的通用要点并标注未核实，**不得用邻近城市气候外推**。

这一项不是可安装的依赖，因此不写入 `skill-dependencies.json`；它的降级路径记录在该清单的 `climate-lookup` 功能条目中。

## 4. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `check_environment.py` 返回 `needs_setup` | 缺 Python 3.10+，或包内脚本/模板缺失 | 按第 1、2 节修复后重跑 |
| `SyntaxError: invalid syntax` 指向 `int \| None` | Python 低于 3.10 | 升级到 3.10+ |
| 退出码 `2` 且提示 `invalid choice` | `--theme` 或 `--flora` 传了非法值 | 从 SKILL.md 的主题与装饰对照表里取值 |
| 退出码 `1` 且提示"目标已存在" | 输出文件已存在 | 换路径，或确认后加 `--force` 覆盖 |
