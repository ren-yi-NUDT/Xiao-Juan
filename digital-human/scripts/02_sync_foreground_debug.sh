#!/usr/bin/env bash
# 前台短时运行 uv sync，用于诊断
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
REPO="$HOME/opentalking-workspace/opentalking"
cd "$REPO" || exit 1
echo "== cwd: $(pwd)"
timeout 60 uv sync --extra dev --extra models --extra quicktalk-cuda --python 3.11.9 2>&1 | tail -n 25
echo "== 退出码(被 timeout 截断为 124 是正常的): ${PIPESTATUS[0]}"
