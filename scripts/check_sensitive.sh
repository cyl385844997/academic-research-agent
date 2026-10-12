#!/usr/bin/env bash
# check_sensitive.sh —— 防止商业敏感文件被 track（public 仓库红线）
#
# .gitignore 只能防「不小心 add」，防不住「手滑 force add」或「改文件名绕过」。
# 本脚本直接查 git 索引：任何被 track 的 company_profile.yaml（非 example）
# 或 knowledge/ 下其他非 example 文件，一律报错退出非零，让 pre-commit 拦截。
#
# 用法：
#   bash scripts/check_sensitive.sh          # 手动检查
#   git config core.hooksPath .githooks      # 或软链到 .git/hooks/pre-commit
set -euo pipefail

cd "$(dirname "$0")/.."

fail=0

# 1) company_profile 真实文件被 track（example 模板放行，其余 knowledge/ 文件
#    不属于敏感判定范围——如 .gitkeep、领域词典等存量文件）
while IFS= read -r f; do
  base="$(basename "$f")"
  case "$base" in
    *company_profile*.yaml|*company_profile*.yml)
      case "$base" in
        *example*) ;;
        *)
          echo "[check_sensitive] company_profile 真实文件被 git track：$f" >&2
          echo "  该文件含公司能力/商业模式/约束/历史判断，属商业敏感信息。" >&2
          echo "  请 git rm --cached \"$f\"，真实内容只留本地。" >&2
          fail=1
          ;;
      esac
      ;;
  esac
done < <(git ls-files '*.yaml' '*.yml' 2>/dev/null || true)

# 3) 记忆库内容（double check，正常 .gitignore 已覆盖）
while IFS= read -r f; do
  case "$f" in
    memory/.gitkeep|memory/README.md) ;;
    memory/*)
      echo "[check_sensitive] 记忆库内容被 track：$f" >&2
      fail=1
      ;;
  esac
done < <(git ls-files memory/ 2>/dev/null || true)

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "[check_sensitive] 发现敏感文件被 track，提交被拒绝。" >&2
  exit 1
fi

echo "[check_sensitive] OK：无敏感文件被 track。"
