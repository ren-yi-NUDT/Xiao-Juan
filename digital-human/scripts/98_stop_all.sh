#!/usr/bin/env bash
# 停止所有 OpenTalking 服务
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
REPO="$HOME/opentalking-workspace/opentalking"
cd "$REPO" || exit 1
bash scripts/quickstart/stop_all.sh
echo "== 停止完成"
pgrep -af "start_unified|opentalking" | head -5 || echo "(无残留进程)"
