#!/usr/bin/env bash
# check_docs.sh <项目根> — 文档结构确定性检查（机器可判定部分）
# 检查：目录布局 / README 断链 / README 索引覆盖率 / plans+specs 日期前缀命名
# 用法：bash check_docs.sh [项目根]   （默认当前目录）
# 退出码：0 = 全部通过，1 = 发现问题（明细打到 stdout）
# 输出约定：「-」开头为问题（计入退出码）；「·」开头为提示（不计入，仅供参考）

set -u
ROOT="${1:-.}"
cd "$ROOT" || { echo "错误：目录不存在: $ROOT"; exit 2; }

issues=0
hints=0
note() { printf '%s\n' "  - $*"; issues=$((issues+1)); }
hint() { printf '%s\n' "  · $*"; hints=$((hints+1)); }
section() { printf '\n== %s ==\n' "$*"; }

echo "文档结构检查：$(pwd)"

# ---------- 1. 目录布局 ----------
section "目录布局"
for f in README.md docs; do
  [ -e "$f" ] || note "缺少 $f"
done
if [ -d docs ]; then
  [ -d docs/modules ] || note "缺少 docs/modules/（代码按模块组织时必备）"
  # 可选分区：只提示不计数——空目录不如不建，有实际内容再建
  for d in manual plans specs reference; do
    [ -d "docs/$d" ] || hint "未建 docs/$d/（可选分区，有实际内容再建）"
  done
  # 七件主文档：NN-关键词….md 或英文关键词开头（architecture.md / API.md 等旧式命名均可）
  # 匹配规则：去掉 NN- 前缀后以关键词开头——GHSA镜像部署.md 这类前缀式补充文档
  # 不会被误认为主文档（否则 deployment 类会被它顶替而漏报）
  for pair in "architecture:架构" "features:功能" "usage:使用" "API:接口" \
              "configuration:配置" "deployment:部署" "development:开发"; do
    en="${pair%%:*}"; zh="${pair##*:}"
    found=""
    for f in docs/*.md; do
      [ -e "$f" ] || continue
      base=$(basename "$f"); title="$base"
      [[ "$base" =~ ^[0-9]{2}- ]] && title="${base#*-}"
      case "$(printf '%s' "$title" | tr '[:upper:]' '[:lower:]')" in "$en"*) found="$f"; break ;; esac
      case "$title" in "$zh"*) found="$f"; break ;; esac
    done
    [ -n "$found" ] || note "缺少主文档：${zh}类（建议命名 0x-${zh}….md，关键词开头）"
  done
fi

# ---------- 2. README 断链（本地 .md 链接目标是否存在） ----------
section "README 断链"
if [ -f README.md ]; then
  bad=0
  while IFS= read -r link; do
    [ -z "$link" ] && continue
    target="${link%%#*}"                    # 去掉 #anchor
    [ -z "$target" ] && continue            # 纯锚点链接跳过
    if [ ! -e "$target" ]; then
      lineno=$(grep -n -F "]($link)" README.md | head -1 | cut -d: -f1)
      note "断链 → $target (README.md:${lineno:-?})"
      bad=1
    fi
  done < <(grep -oE '\]\([^)]+\)' README.md | sed -E 's/^\]\(//; s/\)$//' \
           | grep -vE '^(https?://|mailto:|#)' | sort -u)
  [ "$bad" = 0 ] && echo "  ok（无断链）"
fi

# ---------- 3. README 索引覆盖率（应索引区域内未被引用的孤儿文档） ----------
# 应索引区域 = docs/ 顶层（md 与 html）+ modules/ + manual/；plans/specs/reference
# 是历史档案，按惯例不进 README 索引，不检查。
section "索引覆盖率（孤儿文档）"
if [ -f README.md ] && [ -d docs ]; then
  orphans=0
  while IFS= read -r doc; do
    rel="${doc#./}"
    # README 直接链接、或 basename 出现在 README 中的都算已索引
    if ! grep -rqF "($rel" README.md && ! grep -rqF "$(basename "$rel")" README.md; then
      note "未被 README 索引：$rel"
      orphans=1
    fi
  done < <(find docs -maxdepth 1 \( -name '*.md' -o -name '*.html' \); find docs/modules docs/manual -name '*.md' 2>/dev/null | sort)
  [ "$orphans" = 0 ] && echo "  ok（全部已索引）"
fi

# ---------- 4. plans/ 与 specs/ 日期前缀命名 ----------
section "plans/specs 命名"
for d in plans specs; do
  [ -d "docs/$d" ] || continue
  for f in docs/$d/*.md; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    # 豁免"活文档"（清单类）
    case "$base" in 待*清单*.md|TODO*.md|todo*.md) continue ;; esac
    [[ "$base" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}- ]] || note "缺日期前缀：$f（应为 YYYY-MM-DD-主题.md）"
  done
done

# ---------- 汇总 ----------
echo
if [ "$issues" -gt 0 ]; then
  echo "共 $issues 处问题（另有语义类问题需人工判断：索引描述是否过期、模块文档是否覆盖代码模块）。"
  [ "$hints" -gt 0 ] && echo "另有 $hints 条提示（·开头，非问题）。"
  exit 1
fi
echo "确定性检查全部通过。"
[ "$hints" -gt 0 ] && echo "另有 $hints 条提示（·开头，非问题）。"
exit 0
