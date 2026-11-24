#!/usr/bin/env bash
# 后台跑依赖安装并写日志（用于长时间下载，进程会脱离会话常驻）
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
LOG="$HOME/uv_sync.log"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$PROJECT_DIR/scripts/03_sync.sh"

# 清理可能残留的卡死 uv 进程
pkill -f "uv sync" 2>/dev/null || true
sleep 1
rm -rf "$HOME"/.cache/uv/.tmp* 2>/dev/null || true

: > "$LOG"
setsid nohup bash "$SELF" >> "$LOG" 2>&1 < /dev/null &
sleep 5
echo "== 已后台启动，日志: $LOG"
tail -n 5 "$LOG"
